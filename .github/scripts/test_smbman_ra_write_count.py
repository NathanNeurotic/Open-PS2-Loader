"""The menu's smbman (modules/network/smbman-ra, embedded in every flavour) trusts only the server's WRITE_ANDX Count.

smb_WriteAndX() used to return the requested count for any success status, as ps2sdk master's still does.
MS-CIFS 2.2.4.43.2 lets a server answer a write to a full disk with a success status and a Count of zero,
and a server may store less than it was sent (ksmbd's SMB1 code returns what the kernel wrote), so against
such a server a write cut short reached the EE as complete. Samba, Windows (per MS-CIFS) and the
PS2-Servers servers answer a full disk with an error status instead, which was already a failed write.

This compiles the real smb_WriteAndX() and smb_WriteFile() from smb.c, and the real smb_write() from
smb_fio.c, against scripted server replies, and checks: smb_WriteAndX() builds the WRITE_ANDX request
it should and returns the server's Count; smb_WriteFile() sends the rest of the data from the right place
in the buffer and at the right 64-bit offset after a short Count, and on a zero Count or a failure returns
the bytes earlier chunks of the same call stored (0 or the error when there were none); a reply shorter
than the six-word response, a WordCount under 6 or a Count over the request fails, while a 45-byte reply
with six words is enough; and smb_write() hands the EE 0 or -EIO for a failed write with the file position
and size untouched, and otherwise advances them by the bytes written.
This is a host regression check, not a console test.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature, where):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        sys.exit('%s: %s...) not found' % (where, signature))
    return source[match.start():source.index('\n}', match.start()) + 2] + '\n'


def define(source, name, where):
    match = re.search(r'^#define\s+' + re.escape(name) + r'\b.*$', source, re.M)
    if match is None:
        sys.exit('%s: #define %s not found' % (where, name))
    return match.group(0) + '\n'


def struct(source, name, where, tail):
    end = source.find('} %s%s;' % (tail, name))
    if end < 0:
        sys.exit('%s: struct %s not found' % (where, name))
    return source[source.rfind('typedef struct', 0, end):end] + '} %s%s;\n' % (tail, name)


SMB = 'modules/network/smbman-ra/smb.c'
SMB_H = 'modules/network/smbman-ra/smb.h'
FIO = 'modules/network/smbman-ra/smb_fio.c'
smb = text(SMB)
smb_h = text(SMB_H)
fio = text(FIO)

wire = (''.join(define(smb_h, name, SMB_H) for name in
                ('SMB_MAGIC', 'SMB_FLAGS2_32BIT_STATUS', 'SMB_COM_WRITE_ANDX', 'SMB_COM_NONE', 'STATUS_SUCCESS'))
        + ''.join(define(smb, name, SMB) for name in ('ZERO_PKT_ALIGNED', 'CLIENT_MAX_XFER_SIZE',
                                                      'CLIENT_MAX_WRITE_SIZE'))
        + ''.join(struct(smb_h, name, SMB_H, '__attribute__((packed)) ') for name in
                  ('SMBHeader_t', 'WriteAndXRequest_t', 'WriteAndXResponse_t'))
        + define(fio, 'SMB_NAME_MAX', FIO) + struct(fio, 'FHANDLE', FIO, ''))
code = (function(smb, 'int smb_WriteAndX(', SMB) + function(smb, 'int smb_WriteFile(', SMB)
        + function(fio, 'int smb_write(', FIO))

HARNESS = r'''
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef long long s64;

/* ps2sdk iomanX values: O_RDWR is O_RDONLY | O_WRONLY. */
#define O_RDONLY 0x0001
#define O_WRONLY 0x0002
#define O_RDWR   0x0003

typedef struct
{
    void *privdata;
} iop_file_t;

@WIRE@

static int UID = 0x0801, TID = 0x0802;
static int locks, unlocks;
static void smb_io_lock(void)
{
    locks++;
}
static void smb_io_unlock(void)
{
    unlocks++;
}

static struct
{
    u32 sessionHeader;
    union
    {
        u8 u8buff[1024];
        WriteAndXRequest_t writeAndXRequest;
        WriteAndXResponse_t writeAndXResponse;
    } smb;
} __attribute__((packed)) SMB_buf;

static u32 session_length;
static void nb_SetSessionMessage(u32 size)
{
    session_length = size;
}

/* One scripted reply per request: the SMB message length GetSMBServerReply returns (or a transport
   error), the NT status, WordCount, Count (ASKED = the requested length) and CountHigh. Like RecvData,
   only the reply's own bytes overwrite SMB_buf.smb, so a reply too short to reach Count leaves the
   request's bytes there (its FID sits where the reply's Count goes). */
#define ASKED -1
#define REPLY_LEN 47 /* 32-byte header, WordCount, 6 words, ByteCount */
typedef struct
{
    int length;
    u32 status;
    u8 words;
    int count;
    u16 count_high;
} reply_t;
static reply_t replies[4];
static int nreplies, calls, bad_request, fid;
static s64 call_off[4];
static int call_len[4];
static long call_from[4]; /* where in buf each request's data starts */
static char buf[70000];

static int GetSMBServerReply(int shdrlen, void *spayload, int rhdrlen)
{
    WriteAndXRequest_t *WR = &SMB_buf.smb.writeAndXRequest;
    reply_t want = {REPLY_LEN, STATUS_SUCCESS, 6, ASKED, 0};
    u8 reply[REPLY_LEN];
    WriteAndXResponse_t *rsp = (WriteAndXResponse_t *)reply;
    int asked = WR->DataLengthLow | (WR->DataLengthHigh << 16);

    /* The request itself: one padding byte after the parameter block, data right behind it, write-through,
       and ByteCount covering padding and data, which needs at most 65534 bytes of data. */
    if (shdrlen != (int)sizeof(WriteAndXRequest_t) + 1 || rhdrlen != 0 || spayload == NULL ||
        session_length != (u32)(shdrlen + asked) || WR->smbH.Magic != SMB_MAGIC ||
        !(WR->smbH.Flags2 & SMB_FLAGS2_32BIT_STATUS) || WR->smbH.Cmd != SMB_COM_WRITE_ANDX ||
        WR->smbWordcount != 14 || WR->smbAndxCmd != SMB_COM_NONE || WR->smbH.UID != UID || WR->smbH.TID != TID ||
        WR->FID != fid || WR->WriteMode != 0x0001 || WR->DataOffset != sizeof(WriteAndXRequest_t) + 1 ||
        asked + 1 > 0xFFFF || WR->ByteCount != asked + 1)
        bad_request++;
    if (calls < 4) {
        call_off[calls] = (s64)WR->OffsetLow | ((s64)WR->OffsetHigh << 32);
        call_len[calls] = asked;
        call_from[calls] = (long)((char *)spayload - buf);
    }
    if (calls < nreplies)
        want = replies[calls];
    calls++;
    if (want.length <= 0)
        return want.length;

    memset(reply, 0, sizeof(reply));
    rsp->smbH.Magic = SMB_MAGIC;
    rsp->smbH.Cmd = SMB_COM_WRITE_ANDX;
    rsp->smbH.Eclass = (short)(want.status & 0xffff);
    rsp->smbH.Ecode = (short)(want.status >> 16);
    rsp->smbWordcount = want.words;
    rsp->smbAndxCmd = SMB_COM_NONE;
    rsp->Count = (u16)(want.count == ASKED ? asked : want.count);
    rsp->Remaining = 0xFFFF; /* Available: MUST be 0xFFFF for a disk file */
    rsp->CountHigh = want.count_high;
    memcpy(&SMB_buf.smb, reply, want.length < REPLY_LEN ? want.length : REPLY_LEN);
    return want.length;
}

@CODE@

static FHANDLE fh;
static iop_file_t file = {&fh};

static void reset(int n, const reply_t *r)
{
    int i;

    calls = locks = unlocks = 0;
    memset(call_off, 0, sizeof(call_off));
    memset(call_len, 0, sizeof(call_len));
    memset(call_from, 0, sizeof(call_from));
    nreplies = n;
    for (i = 0; i < n; i++)
        replies[i] = r[i];
    memset(&fh, 0, sizeof(fh));
    fid = 0x10;
    fh.smb_fid = 0x10;
    fh.mode = O_RDWR;
    fh.position = 1000;
    fh.filesize = 1000;
}

static void report(const char *name, int ret)
{
    printf("%s ret=%d calls=%d\n", name, ret, calls);
}

static void report_at(const char *name)
{
    printf("%s %d@%lld from %ld, %d@%lld from %ld\n", name, call_len[0], call_off[0], call_from[0], call_len[1],
           call_off[1], call_from[1]);
}

static void report_file(const char *name, int ret)
{
    printf("%s ret=%d calls=%d position=%lld filesize=%lld locks=%d/%d\n", name, ret, calls, fh.position, fh.filesize,
           locks, unlocks);
}

int main(void)
{
    static const reply_t zero[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t half_rest[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 256, 0}, {REPLY_LEN, STATUS_SUCCESS, 6, ASKED, 0}};
    static const reply_t half_zero[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 256, 0}, {REPLY_LEN, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t some_zero[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 100, 0}, {REPLY_LEN, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t half_full[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 256, 0}, {35, 0xC000007F, 0, 0, 0}};
    static const reply_t over[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 600, 0}};
    static const reply_t high[] = {{REPLY_LEN, STATUS_SUCCESS, 6, ASKED, 1}};
    static const reply_t disk_full[] = {{35, 0xC000007F, 0, 0, 0}};
    static const reply_t truncated[] = {{35, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t half_count[] = {{38, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t no_reserved[] = {{44, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t few_words[] = {{REPLY_LEN, STATUS_SUCCESS, 2, ASKED, 0}};
    static const reply_t five_words[] = {{REPLY_LEN, STATUS_SUCCESS, 5, ASKED, 0}};
    static const reply_t no_bytecount[] = {{45, STATUS_SUCCESS, 6, ASKED, 0}};
    static const reply_t lost[] = {{-2, STATUS_SUCCESS, 6, ASKED, 0}};

    reset(0, NULL);
    report("full", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, zero);
    report("count-zero", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(2, half_rest);
    report("count-half-then-rest", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    report_at("count-half-then-rest-at");
    /* The 64-bit position carries into OffsetHigh after a short Count. */
    reset(2, half_rest);
    report("count-half-past-4g", smb_WriteFile(UID, TID, 0x10, 0xFFFFFF00LL, buf, 512));
    report_at("count-half-past-4g-at");
    reset(2, half_zero);
    report("count-half-then-zero", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(2, some_zero); /* not half, so the bytes stored differ from the bytes left */
    report("count-100-then-zero", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(2, half_full);
    report("count-half-then-disk-full", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, over);
    report("count-over-asked", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, high);
    report("count-high-ignored", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, high);
    printf("count-high-ignored-andx ret=%d\n", smb_WriteAndX(UID, TID, 0x10, 1000, buf, 512));
    reset(2, half_rest);
    printf("count-half-andx ret=%d\n", smb_WriteAndX(UID, TID, 0x10, 1000, buf, 512));
    reset(1, disk_full);
    report("status-disk-full", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    /* FID 512 lands where the reply's Count goes: a truncated reply must not read it as Count. */
    reset(1, truncated);
    fid = 512;
    report("reply-truncated", smb_WriteFile(UID, TID, 512, 1000, buf, 512));
    reset(1, half_count); /* ends inside Count: its high byte is still the request FID's */
    fid = 512;
    report("reply-ends-in-count", smb_WriteFile(UID, TID, 512, 1000, buf, 512));
    reset(1, no_reserved); /* Count 0 arrived, the last parameter word did not */
    report("reply-44-bytes", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, few_words);
    report("reply-wordcount-2", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, five_words); /* a whole 47-byte reply, but MS-CIFS says six words */
    report("reply-wordcount-5", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, no_bytecount); /* all six words, no ByteCount: Count is all this needs */
    report("reply-45-bytes", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(1, lost);
    report("transport-error", smb_WriteFile(UID, TID, 0x10, 1000, buf, 512));
    reset(0, NULL);
    report("chunks", smb_WriteFile(UID, TID, 0x10, 0, buf, 70000));
    report_at("chunks-at");

    reset(0, NULL);
    report_file("write-saved", smb_write(&file, buf, 512));
    reset(1, zero);
    report_file("write-full-share", smb_write(&file, buf, 512));
    reset(2, half_zero);
    report_file("write-half-then-full-share", smb_write(&file, buf, 512));
    reset(2, half_full);
    report_file("write-half-then-disk-full", smb_write(&file, buf, 512));
    reset(2, half_rest);
    report_file("write-half-then-rest", smb_write(&file, buf, 512));
    report_at("write-half-then-rest-at");
    /* Inside the file: the position moves, the size does not. */
    reset(2, half_rest);
    fh.position = 0;
    report_file("write-inside-file", smb_write(&file, buf, 512));
    report_at("write-inside-file-at");
    reset(1, disk_full);
    report_file("write-status-disk-full", smb_write(&file, buf, 512));

    printf("bad-request %d\n", bad_request);
    return 0;
}
'''

WANT = [
    'full ret=512 calls=1',
    'count-zero ret=0 calls=1',
    'count-half-then-rest ret=512 calls=2',
    'count-half-then-rest-at 512@1000 from 0, 256@1256 from 256',
    'count-half-past-4g ret=512 calls=2',
    'count-half-past-4g-at 512@4294967040 from 0, 256@4294967296 from 256',
    'count-half-then-zero ret=256 calls=2',
    'count-100-then-zero ret=100 calls=2',
    'count-half-then-disk-full ret=256 calls=2',
    'count-over-asked ret=-5 calls=1',
    'count-high-ignored ret=512 calls=1',
    'count-high-ignored-andx ret=512',
    'count-half-andx ret=256',
    'status-disk-full ret=-5 calls=1',
    'reply-truncated ret=-5 calls=1',
    'reply-ends-in-count ret=-5 calls=1',
    'reply-44-bytes ret=-5 calls=1',
    'reply-wordcount-2 ret=-5 calls=1',
    'reply-wordcount-5 ret=-5 calls=1',
    'reply-45-bytes ret=512 calls=1',
    'transport-error ret=-5 calls=1',
    'chunks ret=70000 calls=2',
    'chunks-at 65534@0 from 0, 4466@65534 from 65534',
    'write-saved ret=512 calls=1 position=1512 filesize=1512 locks=1/1',
    'write-full-share ret=0 calls=1 position=1000 filesize=1000 locks=1/1',
    'write-half-then-full-share ret=256 calls=2 position=1256 filesize=1256 locks=1/1',
    'write-half-then-disk-full ret=256 calls=2 position=1256 filesize=1256 locks=1/1',
    'write-half-then-rest ret=512 calls=2 position=1512 filesize=1512 locks=1/1',
    'write-half-then-rest-at 512@1000 from 0, 256@1256 from 256',
    'write-inside-file ret=512 calls=2 position=512 filesize=1000 locks=1/1',
    'write-inside-file-at 512@0 from 0, 256@256 from 256',
    'write-status-disk-full ret=-5 calls=1 position=1000 filesize=1000 locks=1/1',
    'bad-request 0',
]


def run(name, source):
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / (name + '.c'), Path(tmp) / name
        src.write_text(source, encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            sys.exit('%s harness did not compile:\n%s' % (name, build.stderr))
        result = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            sys.exit('%s harness exited %d:\n%s' % (name, result.returncode, result.stderr))
        return result.stdout.splitlines()


got = run('write_count', HARNESS.replace('@WIRE@', wire).replace('@CODE@', code))
for index in range(max(len(got), len(WANT))):
    g = got[index] if index < len(got) else '<missing>'
    w = WANT[index] if index < len(WANT) else '<none>'
    if g != w:
        failures.append('smbman-ra WRITE_ANDX Count:\n  got  %s\n  want %s' % (g, w))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('smbman-ra: WRITE_ANDX trusts only the server Count; a short Count is resent, a zero one ends the write')
