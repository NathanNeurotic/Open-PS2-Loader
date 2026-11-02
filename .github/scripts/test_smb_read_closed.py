"""An SMB read whose reply is cut off mid-message fails instead of spinning forever.

smb_ReadAndX() (modules/iopcore/cdvdman/smb.c, USE_CUSTOM_RECV path) collects a reply that arrives in
several TCP segments with "rcv_size += r" until it has the whole message. SMSTCPIP's custom
lwip_recvfrom() returns 0 once the connection is closed and -1 on an error, so a reply cut off by the
server (a Samba share dropping an idle PS2) made that loop spin forever at the cdvdman thread's
priority while smb_ReadFile() held smb_io_sema: the game froze and IGR could not run.

This compiles the real smb_ReadAndX() with the real SMB_buf layout and session-header helpers against a
scripted transport and checks that a whole reply in one or several segments still returns its data
length, and that a close (0) or an error (-1) after the first segment returns -2 promptly.
It also checks that a reply with an error status returns -EIO. Such a reply is shorter than a READ_ANDX
reply, so its DataLength field still holds the request's bytes, and the read used to return them as its
length with nothing read: a game whose image could not be opened read whatever its buffer held.
The transport is SMSTCPIP's lwip_recvfrom() over the bytes the server sent, cut into TCP segments, so
replies whose first segment ends inside the header (before the length, inside the status, before the
data) are checked too: the read must return the server's status and data, and must take the whole of
an error reply off the socket, which would otherwise be read as the next reply.
Adapted from belomaxorka/YAOPL e16e2d15. This is a host regression check, not a console test.
"""
import errno
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
SMB = 'modules/iopcore/cdvdman/smb.c'
SMB_H = 'modules/iopcore/cdvdman/smb.h'


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)[^;{\n]*\n\{', source, re.M)
    if match is None:
        sys.exit('%s: %s...) not found' % (SMB, signature))
    return source[match.start():source.index('\n}', match.start()) + 2] + '\n'


def define(source, name, where):
    match = re.search(r'^#define\s+' + re.escape(name) + r'\b.*$', source, re.M)
    if match is None:
        sys.exit('%s: #define %s not found' % (where, name))
    return match.group(0) + '\n'


def packed_struct(source, name):
    end = source.find('} __attribute__((packed)) %s;' % name)
    if end < 0:
        sys.exit('%s: struct %s not found' % (SMB_H, name))
    return source[source.rfind('typedef struct', 0, end):end] + '} __attribute__((packed)) %s;\n' % name


smb = text(SMB)
smb_h = text(SMB_H)

# Keep only the USE_CUSTOM_RECV branch of smb_ReadAndX(), the one the build compiles.
read_andx = function(smb, 'static int smb_ReadAndX(')
if not re.search(r'^#define\s+USE_CUSTOM_RECV\b', smb, re.M):
    sys.exit('%s: USE_CUSTOM_RECV is no longer defined; update this check' % SMB)

source = r'''
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef short s16;
struct sockaddr;
typedef int socklen_t;
#define USE_CUSTOM_RECV 1
''' + ''.join(define(smb_h, name, SMB_H) for name in ('SMB_MAGIC', 'SMB_FLAGS2_32BIT_STATUS', 'SMB_COM_READ_ANDX', 'SMB_COM_NONE', 'STATUS_SUCCESS')) \
    + define(smb, 'ZERO_PKT_ALIGNED', SMB) + define(smb, 'SMB_STATUS', SMB) \
    + ''.join(packed_struct(smb_h, name) for name in ('SMBHeader_t', 'ReadAndXRequest_t', 'ReadAndXResponse_t')) + r'''
static u16 UID, TID;
static int main_socket = 3;
static struct
{
    u32 sessionHeader;
    union
    {
        u8 u8buff[1024];
        ReadAndXRequest_t readAndXRequest;
        ReadAndXResponse_t readAndXResponse;
    } smb;
} __attribute__((packed)) SMB_buf;
''' + function(smb, 'static void nb_SetSessionMessage(') + function(smb, 'static int nb_GetSessionMessageLength(') \
    + function(smb, 'static u8 nb_GetPacketType(') + r'''
static int SendData(int sock, char *buf, int size) { (void)sock; (void)buf; return size; }

#define DATA_LEN 3000
#define HDR 49
#define ERROR_REPLY 35 /* an error reply: the SMB header, WordCount 0 and ByteCount 0 */
/* The server's side of the socket: the bytes it sent (an NBSS keepalive first, when asked), cut into
   TCP segments. lwip_recvfrom() below is SMSTCPIP's (modules/network/SMSTCPIP/sockets.c): a call
   with a header index copies a segment of 63 bytes or more as a READ_ANDX header of DataOffset + 4
   bytes plus payload, and a shorter segment whole into the header; the rest of a segment stays for
   the next call. */
static unsigned char wire[8192];
static int wire_len, seg[16], seg_count, seg_pos, seg_off, wire_pos, end_code, calls;
static int recv_stub(int s, void *mem, int hlen, void *payload, int plen, unsigned int flags, struct sockaddr *from, socklen_t *fromlen)
{
    int avail, copylen = 0, index = hlen;
    (void)s; (void)flags; (void)from; (void)fromlen;
    if (++calls > 64) {
        printf("TIMEOUT: smb_ReadAndX kept receiving after the connection closed\n");
        exit(3);
    }
    if (seg_pos >= seg_count)
        return end_code;
    avail = seg[seg_pos] - seg_off;
    if (index) {
        if (avail >= 63) {
            memcpy(mem, &wire[wire_pos], 63);
            index = ((unsigned char *)mem)[index] + 4;
            if (index > avail) {
                printf("BAD TEST: DataOffset beyond the segment\n");
                exit(4);
            }
            memcpy(mem, &wire[wire_pos], index);
            copylen = index;
            avail -= index;
        } else {
            memcpy(mem, &wire[wire_pos], avail);
            copylen = avail;
            avail = 0;
        }
    }
    if (avail) {
        if (plen > avail)
            plen = avail;
        memcpy(payload, &wire[wire_pos + copylen], plen);
        copylen += plen;
    }
    wire_pos += copylen;
    seg_off += copylen;
    if (seg_off == seg[seg_pos]) {
        seg_pos++;
        seg_off = 0;
    }
    return copylen;
}
static int (*plwip_recvfrom)(int s, void *mem, int hlen, void *payload, int plen, unsigned int flags, struct sockaddr *from, socklen_t *fromlen) = recv_stub;
''' + function(smb, 'static int smb_RecvReplyRest(') + read_andx + r'''
int main(int argc, char **argv)
{
    /* argv: want status data_offset keepalive end_code segment sizes... (0 sizes: one segment) */
    static unsigned char readbuf[DATA_LEN + 64];
    int want = atoi(argv[1]), offset = atoi(argv[3]), keepalive = atoi(argv[4]), i, pos = 0, size;
    u32 status = (u32)strtoul(argv[2], NULL, 0);
    end_code = atoi(argv[5]);
    if (keepalive) { /* an NBSS session keepalive (type 0x85), its own segment */
        wire[pos++] = 0x85, wire[pos++] = 0, wire[pos++] = 0, wire[pos++] = 0;
        seg[seg_count++] = 4;
    }
    size = status != 0 ? ERROR_REPLY : offset + DATA_LEN;
    wire[pos] = 0, wire[pos + 1] = (unsigned char)(size >> 16), wire[pos + 2] = (unsigned char)(size >> 8), wire[pos + 3] = (unsigned char)size;
    {
        ReadAndXResponse_t *r = (ReadAndXResponse_t *)&wire[pos + 4];
        r->smbH.Magic = SMB_MAGIC;
        r->smbH.Cmd = SMB_COM_READ_ANDX;
        r->smbH.Eclass = (s16)(status & 0xffff);
        r->smbH.Ecode = (s16)(status >> 16);
        if (status == 0) {
            r->smbWordcount = 12;
            r->DataLengthLow = DATA_LEN;
            r->DataOffset = (u16)offset;
            for (i = 0; i < DATA_LEN; i++)
                wire[pos + 4 + offset + i] = (unsigned char)(i * 7 + 1);
        }
    }
    wire_len = pos + 4 + size;
    if (argc == 6) {
        seg[seg_count++] = wire_len - pos;
    } else {
        int sum = pos;
        for (i = 6; i < argc; i++) {
            seg[seg_count] = atoi(argv[i]);
            sum += seg[seg_count++];
        }
        if (sum > wire_len) {
            printf("BAD TEST: segments add up to %d of %d bytes\n", sum, wire_len);
            return 4;
        }
    }
    int r = smb_ReadAndX(1, 0, 0, readbuf, DATA_LEN);
    if (r != want) {
        printf("smb_ReadAndX = %d, expected %d\n", r, want);
        return 1;
    }
    if (r == DATA_LEN)
        for (i = 0; i < DATA_LEN; i++)
            if (readbuf[i] != (unsigned char)(i * 7 + 1)) {
                printf("readbuf[%d] = %d, not the server's data\n", i, readbuf[i]);
                return 1;
            }
    if (r >= 0 || r == -EIO)
        if (wire_pos != wire_len) {
            printf("%d of the reply's %d bytes left on the socket\n", wire_len - wire_pos, wire_len);
            return 1;
        }
    return 0;
}
'''

OK = 0
INVALID_HANDLE = 0xC0000008  # STATUS_INVALID_HANDLE: a read from an image that could not be opened
END_OF_FILE = 0xC0000011  # STATUS_END_OF_FILE: a read that starts past the end of the file
W = 4 + 59 + 3000  # a whole READ_ANDX reply with its data at DataOffset 59
E = 4 + 35  # a whole error reply
CLOSE, ERROR = 0, -1
# (name, expected result, status, DataOffset, keepalive first, what the socket returns once the
#  segments run out, segment sizes; [] is one segment)
cases = [
    ('whole reply in one segment', 3000, OK, 59, 0, CLOSE, []),
    ('reply in three segments', 3000, OK, 59, 0, CLOSE, [1063, 1000, 1000]),
    ('server closes after the first segment', -2, OK, 59, 0, CLOSE, [1063]),
    ('receive error after the first segment', -2, OK, 59, 0, ERROR, [1063]),
    ('server closes after two segments', -2, OK, 59, 0, CLOSE, [1063, 1500]),
    ('a keepalive before the reply', 3000, OK, 59, 1, CLOSE, []),
    ('first segment ends inside the length', 3000, OK, 59, 0, CLOSE, [2, W - 2]),
    ('first segment ends inside the status', 3000, OK, 59, 0, CLOSE, [11, W - 11]),
    ('first segment ends before DataOffset', 3000, OK, 59, 0, CLOSE, [40, W - 40]),
    ('header in four segments', 3000, OK, 59, 0, CLOSE, [3, 20, 30, 10, W - 63]),
    ('padding after the header, split before it', 3000, OK, 60, 0, CLOSE, [40, 4 + 60 + 3000 - 40]),
    ('server closes inside the header', -2, OK, 59, 0, CLOSE, [40]),
    ('server refuses the read: invalid handle', -errno.EIO, INVALID_HANDLE, 59, 0, CLOSE, []),
    ('server refuses the read: end of file', -errno.EIO, END_OF_FILE, 59, 0, CLOSE, []),
    ('refusal split inside the length', -errno.EIO, INVALID_HANDLE, 59, 0, CLOSE, [2, E - 2]),
    ('refusal split inside the status', -errno.EIO, INVALID_HANDLE, 59, 0, CLOSE, [11, E - 11]),
    ('refusal split after the status', -errno.EIO, INVALID_HANDLE, 59, 0, CLOSE, [20, E - 20]),
    ('server closes inside a refusal', -2, INVALID_HANDLE, 59, 0, CLOSE, [20]),
]
failures = []
with tempfile.TemporaryDirectory(prefix='smb-read-closed-') as folder:
    src = Path(folder) / 'test.c'
    src.write_text(source)
    binary = Path(folder) / 'test'
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-Wno-unused-variable',
                    '-Wno-unused-but-set-variable', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(src), '-o', str(binary)], check=True)
    for name, want, status, offset, keepalive, end, script in cases:
        result = subprocess.run([str(binary), str(want), str(status), str(offset), str(keepalive), str(end)]
                                + [str(s) for s in script],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            failures.append('%s: %s' % (name, (result.stdout + result.stderr).strip()))

if failures:
    print('FAIL:\n  ' + '\n  '.join(failures))
    sys.exit(1)
print('PASS: a cut-off SMB read reply fails with -2 and a refused one with -EIO, taken whole off the socket; '
      'whole and segmented replies, a header in pieces included, return their data')
