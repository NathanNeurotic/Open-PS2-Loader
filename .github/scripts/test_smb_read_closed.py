"""An SMB read whose reply is cut off mid-message fails instead of spinning forever.

smb_ReadAndX() (modules/iopcore/cdvdman/smb.c, USE_CUSTOM_RECV path) collects a reply that arrives in
several TCP segments with "rcv_size += r" until it has the whole message. SMSTCPIP's custom
lwip_recvfrom() returns 0 once the connection is closed and -1 on an error, so a reply cut off by the
server (a Samba share dropping an idle PS2) made that loop spin forever at the cdvdman thread's
priority while smb_ReadFile() held smb_io_sema: the game froze and IGR could not run.

This compiles the real smb_ReadAndX() with the real SMB_buf layout and session-header helpers against a
scripted transport and checks that a whole reply in one or several segments still returns its data
length, and that a close (0) or an error (-1) after the first segment returns -2 promptly.
Adapted from belomaxorka/YAOPL e16e2d15. This is a host regression check, not a console test.
"""
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
    + define(smb, 'ZERO_PKT_ALIGNED', SMB) \
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
static int script[8], script_len, script_pos, calls;
static int recv_stub(int s, void *mem, int hlen, void *payload, int plen, unsigned int flags, struct sockaddr *from, socklen_t *fromlen)
{
    (void)s; (void)payload; (void)plen; (void)flags; (void)from; (void)fromlen;
    if (++calls > 64) {
        printf("TIMEOUT: smb_ReadAndX kept receiving after the connection closed\n");
        exit(3);
    }
    if (mem != NULL && hlen == HDR) { /* first segment: header plus the first part of the data */
        u32 size = HDR - 4 + DATA_LEN;
        SMB_buf.sessionHeader = ((size & 0xff0000) >> 8) | ((size & 0xff00) << 8) | ((size & 0xff) << 24);
        SMB_buf.smb.readAndXResponse.DataOffset = HDR - 4;
        SMB_buf.smb.readAndXResponse.DataLengthLow = DATA_LEN;
        SMB_buf.smb.readAndXResponse.DataLengthHigh = 0;
        return HDR + script[script_pos++];
    }
    return script_pos < script_len ? script[script_pos++] : 0;
}
static int (*plwip_recvfrom)(int s, void *mem, int hlen, void *payload, int plen, unsigned int flags, struct sockaddr *from, socklen_t *fromlen) = recv_stub;
''' + read_andx + r'''
int main(int argc, char **argv)
{
    static u8 readbuf[DATA_LEN + 64];
    int want = atoi(argv[1]), i;
    script_len = argc - 2;
    for (i = 0; i < script_len; i++)
        script[i] = atoi(argv[i + 2]);
    int r = smb_ReadAndX(1, 0, 0, readbuf, DATA_LEN);
    if (r != want) {
        printf("smb_ReadAndX = %d, expected %d\n", r, want);
        return 1;
    }
    return 0;
}
'''

cases = [
    ('whole reply in one segment', 3000, [3000]),
    ('reply in three segments', 3000, [1000, 1000, 1000]),
    ('server closes after the first segment', -2, [1000, 0]),
    ('receive error after the first segment', -2, [1000, -1]),
    ('server closes after two segments', -2, [1000, 1500, 0]),
]
failures = []
with tempfile.TemporaryDirectory(prefix='smb-read-closed-') as folder:
    src = Path(folder) / 'test.c'
    src.write_text(source)
    binary = Path(folder) / 'test'
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wno-unused-function', '-Wno-unused-variable',
                    '-Wno-unused-but-set-variable', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(src), '-o', str(binary)], check=True)
    for name, want, script in cases:
        result = subprocess.run([str(binary), str(want)] + [str(s) for s in script],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            failures.append('%s: %s' % (name, (result.stdout + result.stderr).strip()))

if failures:
    print('FAIL:\n  ' + '\n  '.join(failures))
    sys.exit(1)
print('PASS: a cut-off SMB read reply fails with -2; whole and segmented replies still return their length')
