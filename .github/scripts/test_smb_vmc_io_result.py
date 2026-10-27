"""SMB VMC page I/O releases smb_io_sema on failure and reports the failure to mcemu.

smb_WriteFile() and smb_ReadFile() (modules/iopcore/cdvdman/smb.c) take smb_io_sema and used to return
straight out of their chunk loop when smb_WriteAndX()/smb_ReadAndX() failed, without signalling it. The
SMB VMC device (modules/mcemu/device-smb.c) then mapped the result with "!= 0 ? 1 : 0", so -EIO reached
mcemu as a successful page access. The next SMB disc read, VMC access, or the IGR shutdown's DeviceLock()
(WaitSema(smb_io_sema)) then blocked forever. DeviceReadPage() also tested smb_OpenAndX() with "!", but
smb_OpenAndX() returns 1 or a negative code, never 0, so a failed open was ignored.

This compiles the real smb_ReadFile/smb_WriteFile with a scripted transport and a counting binary
semaphore (a WaitSema that would block is recorded instead), the real cdvdman DeviceLock(), and the real
mcemu DeviceWritePage/DeviceReadPage, and checks: the semaphore is released after success and after
every failure path (first chunk, later chunk, zero result), the next access and DeviceLock() do not
block after a failure, and device-smb.c turns an error, a short result or a failed open into 0.
It also pins that every function in smb.c that waits on smb_io_sema signals it before each return, and
that smb_Close() never waits on it (oplShutdown() calls it with the semaphore already held).

smb_WriteAndX() used to return the requested count for any success status. MS-CIFS 2.2.4.43.2 lets a
server answer a write to a full disk with a success status and a Count of zero (Samba sends an error
status instead, which already failed), and a server may store less than it was sent, so against such a
server an unwritten VMC page was reported as saved. A third harness runs the real smb_WriteAndX() against scripted server replies and
checks that it returns the server's Count, that smb_WriteFile() sends the rest of the data from the right
place in the buffer after a short Count and fails on a zero one, and that a truncated reply, a short
WordCount or a Count over the request fails.
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


def packed_struct(source, name, where):
    end = source.find('} __attribute__((packed)) %s;' % name)
    if end < 0:
        sys.exit('%s: struct %s not found' % (where, name))
    return source[source.rfind('typedef struct', 0, end):end] + '} __attribute__((packed)) %s;\n' % name


SMB = 'modules/iopcore/cdvdman/smb.c'
SMB_H = 'modules/iopcore/cdvdman/smb.h'
CDVD_DEVICE = 'modules/iopcore/cdvdman/device-smb.c'
VMC_DEVICE = 'modules/mcemu/device-smb.c'
smb = text(SMB)
smb_h = text(SMB_H)
cdvd_device = text(CDVD_DEVICE)
vmc_device = text(VMC_DEVICE)

defines = ''.join(define(smb, name, SMB) for name in
                  ('CLIENT_MAX_XMIT_SIZE', 'CLIENT_MAX_RECV_SIZE', 'WAITIOSEMA', 'SIGNALIOSEMA'))
smb_io = function(smb, 'int smb_ReadFile(', SMB) + function(smb, 'int smb_WriteFile(', SMB)
write_andx = function(smb, 'static int smb_WriteAndX(', SMB)
write_file = function(smb, 'int smb_WriteFile(', SMB)
wire = (''.join(define(smb_h, name, SMB_H) for name in
                ('SMB_MAGIC', 'SMB_FLAGS2_32BIT_STATUS', 'SMB_COM_WRITE_ANDX', 'SMB_COM_NONE', 'STATUS_SUCCESS'))
        + define(smb, 'ZERO_PKT_ALIGNED', SMB)
        + ''.join(packed_struct(smb_h, name, SMB_H) for name in
                  ('SMBHeader_t', 'WriteAndXRequest_t', 'WriteAndXResponse_t')))
device_lock = function(cdvd_device, 'void DeviceLock(', CDVD_DEVICE)
vmc_pages = function(vmc_device, 'int DeviceWritePage(', VMC_DEVICE) + function(vmc_device, 'int DeviceReadPage(', VMC_DEVICE)

COMMON = r'''
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
#define DPRINTF(...) do { } while (0)

typedef struct
{
    u16 PageSize;
    u16 BlockSize;
    u32 CardSize;
} McSpec;
typedef struct
{
    int active;
    char fname[80];
    u16 fid;
    int flags;
    McSpec cspec;
} McImageSpec;
McImageSpec vmcSpec[2];
'''

# The real smb.c read/write loops, the real cdvdman DeviceLock() and the real mcemu page functions,
# linked the way the oplsmb export table links them on the IOP.
END_TO_END = COMMON + r'''
#define SEMA_ID 7
int smb_io_sema = SEMA_ID;
static int sema_count, blocked, extra, bad_id;

/* A binary semaphore (initial 1, max 1, as smb_NegotiateProtocol creates it). A wait on a taken
   semaphore blocks forever on the IOP; here it is counted and returns. */
static int WaitSema(int id)
{
    if (id != SEMA_ID)
        bad_id++;
    if (sema_count == 0) {
        blocked++;
        return -1;
    }
    sema_count--;
    return 0;
}

static int SignalSema(int id)
{
    if (id != SEMA_ID)
        bad_id++;
    if (sema_count == 1)
        extra++;
    else
        sema_count++;
    return 0;
}

@DEFINES@

/* Scripted transport: each AndX call returns the next scripted result; FULL (or an exhausted script)
   transfers the whole chunk. */
#define FULL 0x7fffffff
static int script[8], script_len, script_pos, calls;
static u32 call_off[8];
static int call_len[8];

static int scripted(u32 offsetlow, int nbytes)
{
    int r = FULL;

    if (calls < 8) {
        call_off[calls] = offsetlow;
        call_len[calls] = nbytes;
    }
    calls++;
    if (script_pos < script_len)
        r = script[script_pos++];
    return r == FULL ? nbytes : r;
}

static int smb_ReadAndX(u16 FID, u32 offsetlow, u32 offsethigh, void *readbuf, int nbytes)
{
    (void)FID;
    (void)offsethigh;
    (void)readbuf;
    return scripted(offsetlow, nbytes);
}

static int smb_WriteAndX(u16 FID, u32 offsetlow, u32 offsethigh, void *writebuf, int nbytes)
{
    (void)FID;
    (void)offsethigh;
    (void)writebuf;
    return scripted(offsetlow, nbytes);
}

@SMB_IO@

@DEVICE_LOCK@

static int open_result, opens;
int smb_OpenAndX(char *filename, u16 *FID, int Write)
{
    (void)filename;
    (void)Write;
    opens++;
    if (open_result == 1)
        *FID = 0x42;
    return open_result;
}

@VMC_PAGES@

static char buf[70000];

static void reset(int n, const int *results)
{
    int i;

    sema_count = 1;
    blocked = extra = calls = script_pos = opens = 0;
    script_len = n;
    for (i = 0; i < n; i++)
        script[i] = results[i];
    open_result = 1;
    memset(vmcSpec, 0, sizeof(vmcSpec));
    vmcSpec[0].active = 1;
    vmcSpec[0].fid = 0x10;
    vmcSpec[0].cspec.PageSize = 512;
    vmcSpec[0].cspec.BlockSize = 16;
    vmcSpec[0].cspec.CardSize = 16384;
    strcpy(vmcSpec[0].fname, "VMC\\card.bin");
}

static void report(const char *name, int ret)
{
    printf("%s ret=%d calls=%d held=%d blocked=%d extra=%d\n", name, ret, calls, 1 - sema_count, blocked, extra);
}

int main(void)
{
    static const int full_eio[] = {FULL, -EIO}, full_recv[] = {FULL, -2};
    static const int eio[] = {-EIO}, zero[] = {0};
    int r;

    reset(0, NULL);
    report("write-one", smb_WriteFile(1, 0, 0, buf, 512));
    reset(0, NULL);
    report("write-chunks", smb_WriteFile(1, 0, 0, buf, 70000));
    printf("write-chunks-split %d@%u %d@%u\n", call_len[0], call_off[0], call_len[1], call_off[1]);
    reset(1, eio);
    report("write-eio", smb_WriteFile(1, 0, 0, buf, 512));
    reset(2, full_eio);
    report("write-eio-second-chunk", smb_WriteFile(1, 0, 0, buf, 70000));
    reset(1, zero);
    report("write-zero", smb_WriteFile(1, 0, 0, buf, 512));
    reset(1, eio);
    smb_WriteFile(1, 0, 0, buf, 512);
    report("write-after-failed-write", smb_WriteFile(1, 0, 0, buf, 512));

    reset(0, NULL);
    report("read-one", smb_ReadFile(1, 0, 0, buf, 512));
    reset(0, NULL);
    report("read-chunks", smb_ReadFile(1, 0, 0, buf, 20000));
    printf("read-chunks-split %d@%u %d@%u %d@%u\n", call_len[0], call_off[0], call_len[1], call_off[1], call_len[2], call_off[2]);
    reset(1, eio);
    report("read-eio", smb_ReadFile(1, 0, 0, buf, 512));
    reset(2, full_recv);
    report("read-recv-error-second-chunk", smb_ReadFile(1, 0, 0, buf, 20000));
    reset(1, zero);
    report("read-zero", smb_ReadFile(1, 0, 0, buf, 512));
    reset(1, eio);
    smb_ReadFile(1, 0, 0, buf, 512);
    report("read-after-failed-read", smb_ReadFile(1, 0, 0, buf, 512));

    reset(0, NULL);
    report("vmc-write-ok", DeviceWritePage(0, buf, 3));
    printf("vmc-write-ok-at %d@%u\n", call_len[0], call_off[0]);
    reset(1, eio);
    report("vmc-write-eio", DeviceWritePage(0, buf, 3));
    reset(0, NULL);
    report("vmc-read-ok", DeviceReadPage(0, buf, 3));
    reset(1, eio);
    report("vmc-read-eio", DeviceReadPage(0, buf, 3));

    reset(0, NULL);
    vmcSpec[0].fid = 0xFFFF;
    open_result = -1;
    r = DeviceReadPage(0, buf, 0);
    printf("vmc-open-fails-1 ret=%d opens=%d reads=%d fid=0x%x\n", r, opens, calls, vmcSpec[0].fid);
    reset(0, NULL);
    vmcSpec[0].fid = 0xFFFF;
    open_result = -1000;
    r = DeviceReadPage(0, buf, 0);
    printf("vmc-open-fails-1000 ret=%d opens=%d reads=%d fid=0x%x\n", r, opens, calls, vmcSpec[0].fid);
    reset(0, NULL);
    vmcSpec[0].fid = 0xFFFF;
    r = DeviceReadPage(0, buf, 0);
    printf("vmc-open-ok ret=%d opens=%d reads=%d fid=0x%x\n", r, opens, calls, vmcSpec[0].fid);

    /* IGR: oplShutdown() takes the device lock after a failed VMC save. */
    reset(1, eio);
    DeviceWritePage(0, buf, 3);
    DeviceLock();
    printf("igr-lock-after-failed-vmc-write held=%d blocked=%d\n", 1 - sema_count, blocked);
    reset(1, eio);
    DeviceReadPage(0, buf, 3);
    DeviceLock();
    printf("igr-lock-after-failed-vmc-read held=%d blocked=%d\n", 1 - sema_count, blocked);

    printf("bad-sema-id %d\n", bad_id);
    return 0;
}
'''

END_TO_END_WANT = [
    'write-one ret=512 calls=1 held=0 blocked=0 extra=0',
    'write-chunks ret=70000 calls=2 held=0 blocked=0 extra=0',
    'write-chunks-split 65535@0 4465@65535',
    'write-eio ret=-5 calls=1 held=0 blocked=0 extra=0',
    'write-eio-second-chunk ret=-5 calls=2 held=0 blocked=0 extra=0',
    'write-zero ret=0 calls=1 held=0 blocked=0 extra=0',
    'write-after-failed-write ret=512 calls=2 held=0 blocked=0 extra=0',
    'read-one ret=512 calls=1 held=0 blocked=0 extra=0',
    'read-chunks ret=20000 calls=3 held=0 blocked=0 extra=0',
    'read-chunks-split 8192@0 8192@8192 3616@16384',
    'read-eio ret=-5 calls=1 held=0 blocked=0 extra=0',
    'read-recv-error-second-chunk ret=-2 calls=2 held=0 blocked=0 extra=0',
    'read-zero ret=0 calls=1 held=0 blocked=0 extra=0',
    'read-after-failed-read ret=512 calls=2 held=0 blocked=0 extra=0',
    'vmc-write-ok ret=1 calls=1 held=0 blocked=0 extra=0',
    'vmc-write-ok-at 512@1536',
    'vmc-write-eio ret=0 calls=1 held=0 blocked=0 extra=0',
    'vmc-read-ok ret=1 calls=1 held=0 blocked=0 extra=0',
    'vmc-read-eio ret=0 calls=1 held=0 blocked=0 extra=0',
    'vmc-open-fails-1 ret=0 opens=1 reads=0 fid=0xffff',
    'vmc-open-fails-1000 ret=0 opens=1 reads=0 fid=0xffff',
    'vmc-open-ok ret=1 opens=1 reads=1 fid=0x42',
    'igr-lock-after-failed-vmc-write held=1 blocked=0',
    'igr-lock-after-failed-vmc-read held=1 blocked=0',
    'bad-sema-id 0',
]

# device-smb.c alone, against an smb API that returns any count: only the full page is a success.
MAPPING = COMMON + r'''
static int write_result, read_result, writes, reads;
int smb_WriteFile(u16 FID, u32 offsetlow, u32 offsethigh, void *writebuf, int nbytes)
{
    (void)FID;
    (void)offsetlow;
    (void)offsethigh;
    (void)writebuf;
    (void)nbytes;
    writes++;
    return write_result;
}

int smb_ReadFile(u16 FID, u32 offsetlow, u32 offsethigh, void *readbuf, int nbytes)
{
    (void)FID;
    (void)offsetlow;
    (void)offsethigh;
    (void)readbuf;
    (void)nbytes;
    reads++;
    return read_result;
}

int smb_OpenAndX(char *filename, u16 *FID, int Write)
{
    (void)filename;
    (void)FID;
    (void)Write;
    return 1;
}

@VMC_PAGES@

int main(void)
{
    static const int results[] = {512, 511, 256, 1, 0, -EIO, -2, -1000};
    static char page[512];
    unsigned int i;

    vmcSpec[1].active = 1;
    vmcSpec[1].fid = 0x20;
    vmcSpec[1].cspec.PageSize = 512;
    for (i = 0; i < sizeof(results) / sizeof(results[0]); i++) {
        write_result = read_result = results[i];
        printf("%d write=%d read=%d\n", results[i], DeviceWritePage(1, page, 7), DeviceReadPage(1, page, 7));
    }
    printf("calls %d %d\n", writes, reads);
    return 0;
}
'''

MAPPING_WANT = [
    '512 write=1 read=1',
    '511 write=0 read=0',
    '256 write=0 read=0',
    '1 write=0 read=0',
    '0 write=0 read=0',
    '-5 write=0 read=0',
    '-2 write=0 read=0',
    '-1000 write=0 read=0',
    'calls 8 8',
]


# The real smb_WriteAndX() parsing a scripted server's WRITE_ANDX reply, under the real smb_WriteFile()
# and the real mcemu DeviceWritePage(). A success status with a smaller Count is one way a server may
# answer a full disk (MS-CIFS 2.2.4.43.2): the page was not stored, so it must not be reported as saved.
WRITE_REPLY = COMMON + r'''
@WIRE@

#define SEMA_ID 7
int smb_io_sema = SEMA_ID;
static int sema_count, blocked, extra;

static int WaitSema(int id)
{
    (void)id;
    if (sema_count == 0) {
        blocked++;
        return -1;
    }
    sema_count--;
    return 0;
}

static int SignalSema(int id)
{
    (void)id;
    if (sema_count == 1)
        extra++;
    else
        sema_count++;
    return 0;
}

@DEFINES@

static u16 UID = 0x0801, TID = 0x0802;
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
static int nreplies, calls, bad_request;
static u32 call_off[4];
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

    if (shdrlen != (int)sizeof(WriteAndXRequest_t) + 1 || rhdrlen != 0 || spayload == NULL ||
        session_length != (u32)(shdrlen + asked) || WR->smbH.Cmd != SMB_COM_WRITE_ANDX || WR->smbWordcount != 14)
        bad_request++;
    if (calls < 4) {
        call_off[calls] = WR->OffsetLow;
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

@WRITE_ANDX@

@SMB_IO@

/* DeviceReadPage() is linked in with DeviceWritePage(); this harness only writes. */
int smb_ReadFile(u16 FID, u32 offsetlow, u32 offsethigh, void *readbuf, int nbytes)
{
    (void)FID;
    (void)offsetlow;
    (void)offsethigh;
    (void)readbuf;
    return nbytes;
}

int smb_OpenAndX(char *filename, u16 *FID, int Write)
{
    (void)filename;
    (void)FID;
    (void)Write;
    return 1;
}

@VMC_PAGES@

static void reset(int n, const reply_t *r)
{
    int i;

    sema_count = 1;
    blocked = extra = calls = 0;
    nreplies = n;
    for (i = 0; i < n; i++)
        replies[i] = r[i];
    memset(vmcSpec, 0, sizeof(vmcSpec));
    vmcSpec[0].active = 1;
    vmcSpec[0].fid = 0x10;
    vmcSpec[0].cspec.PageSize = 512;
}

static void report(const char *name, int ret)
{
    printf("%s ret=%d calls=%d held=%d blocked=%d extra=%d\n", name, ret, calls, 1 - sema_count, blocked, extra);
}

int main(void)
{
    static const reply_t zero[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t half_rest[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 256, 0}, {REPLY_LEN, STATUS_SUCCESS, 6, ASKED, 0}};
    static const reply_t half_zero[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 256, 0}, {REPLY_LEN, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t over[] = {{REPLY_LEN, STATUS_SUCCESS, 6, 600, 0}};
    static const reply_t high[] = {{REPLY_LEN, STATUS_SUCCESS, 6, ASKED, 1}};
    static const reply_t disk_full[] = {{35, 0xC000007F, 0, 0, 0}};
    static const reply_t truncated[] = {{35, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t half_count[] = {{38, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t no_reserved[] = {{44, STATUS_SUCCESS, 6, 0, 0}};
    static const reply_t few_words[] = {{REPLY_LEN, STATUS_SUCCESS, 2, ASKED, 0}};
    static const reply_t lost[] = {{-2, STATUS_SUCCESS, 6, ASKED, 0}};

    reset(0, NULL);
    report("full", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(1, zero);
    report("count-zero", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(2, half_rest);
    report("count-half-then-rest", smb_WriteFile(0x10, 1000, 0, buf, 512));
    printf("count-half-then-rest-at %d@%u from %ld, %d@%u from %ld\n", call_len[0], call_off[0], call_from[0],
           call_len[1], call_off[1], call_from[1]);
    reset(2, half_zero);
    report("count-half-then-zero", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(1, over);
    report("count-over-asked", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(1, high);
    report("count-high-ignored", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(1, high);
    printf("count-high-ignored-andx ret=%d\n", smb_WriteAndX(0x10, 1000, 0, buf, 512));
    reset(2, half_rest);
    printf("count-half-andx ret=%d\n", smb_WriteAndX(0x10, 1000, 0, buf, 512));
    reset(1, disk_full);
    report("status-disk-full", smb_WriteFile(0x10, 1000, 0, buf, 512));
    /* FID 512 lands where the reply's Count goes: a truncated reply must not read it as Count. */
    reset(1, truncated);
    report("reply-truncated", smb_WriteFile(512, 1000, 0, buf, 512));
    reset(1, half_count); /* ends inside Count: its high byte is still the request FID's */
    report("reply-ends-in-count", smb_WriteFile(512, 1000, 0, buf, 512));
    reset(1, no_reserved); /* Count 0 arrived, the last parameter word did not */
    report("reply-44-bytes", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(1, few_words);
    report("reply-wordcount-2", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(1, lost);
    report("transport-error", smb_WriteFile(0x10, 1000, 0, buf, 512));
    reset(0, NULL);
    report("chunks", smb_WriteFile(0x10, 0, 0, buf, 70000));
    printf("chunks-at %d@%u from %ld, %d@%u from %ld\n", call_len[0], call_off[0], call_from[0], call_len[1],
           call_off[1], call_from[1]);

    reset(0, NULL);
    report("vmc-page-saved", DeviceWritePage(0, buf, 3));
    reset(1, zero);
    report("vmc-page-full-share", DeviceWritePage(0, buf, 3));
    reset(2, half_zero);
    report("vmc-page-half-then-full-share", DeviceWritePage(0, buf, 3));
    reset(2, half_rest);
    report("vmc-page-half-then-rest", DeviceWritePage(0, buf, 3));
    printf("vmc-page-half-then-rest-at %d@%u from %ld, %d@%u from %ld\n", call_len[0], call_off[0], call_from[0],
           call_len[1], call_off[1], call_from[1]);

    printf("bad-request %d\n", bad_request);
    return 0;
}
'''

WRITE_REPLY_WANT = [
    'full ret=512 calls=1 held=0 blocked=0 extra=0',
    'count-zero ret=0 calls=1 held=0 blocked=0 extra=0',
    'count-half-then-rest ret=512 calls=2 held=0 blocked=0 extra=0',
    'count-half-then-rest-at 512@1000 from 0, 256@1256 from 256',
    'count-half-then-zero ret=0 calls=2 held=0 blocked=0 extra=0',
    'count-over-asked ret=-5 calls=1 held=0 blocked=0 extra=0',
    'count-high-ignored ret=512 calls=1 held=0 blocked=0 extra=0',
    'count-high-ignored-andx ret=512',
    'count-half-andx ret=256',
    'status-disk-full ret=-5 calls=1 held=0 blocked=0 extra=0',
    'reply-truncated ret=-5 calls=1 held=0 blocked=0 extra=0',
    'reply-ends-in-count ret=-5 calls=1 held=0 blocked=0 extra=0',
    'reply-44-bytes ret=-5 calls=1 held=0 blocked=0 extra=0',
    'reply-wordcount-2 ret=-5 calls=1 held=0 blocked=0 extra=0',
    'transport-error ret=-5 calls=1 held=0 blocked=0 extra=0',
    'chunks ret=70000 calls=2 held=0 blocked=0 extra=0',
    'chunks-at 65535@0 from 0, 4465@65535 from 65535',
    'vmc-page-saved ret=1 calls=1 held=0 blocked=0 extra=0',
    'vmc-page-full-share ret=0 calls=1 held=0 blocked=0 extra=0',
    'vmc-page-half-then-full-share ret=0 calls=2 held=0 blocked=0 extra=0',
    'vmc-page-half-then-rest ret=1 calls=2 held=0 blocked=0 extra=0',
    'vmc-page-half-then-rest-at 512@1536 from 0, 256@1792 from 256',
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


def compare(name, got, want):
    for index in range(max(len(got), len(want))):
        g = got[index] if index < len(got) else '<missing>'
        w = want[index] if index < len(want) else '<none>'
        if g != w:
            failures.append('%s:\n  got  %s\n  want %s' % (name, g, w))


compare('smb.c + device-smb.c', run('end_to_end', END_TO_END.replace('@DEFINES@', defines)
                                    .replace('@SMB_IO@', smb_io).replace('@DEVICE_LOCK@', device_lock)
                                    .replace('@VMC_PAGES@', vmc_pages)), END_TO_END_WANT)
compare('device-smb.c result mapping', run('mapping', MAPPING.replace('@VMC_PAGES@', vmc_pages)), MAPPING_WANT)
compare('smb_WriteAndX reply Count', run('write_reply', WRITE_REPLY.replace('@WIRE@', wire).replace('@DEFINES@', defines)
                                         .replace('@WRITE_ANDX@', write_andx).replace('@SMB_IO@', write_file)
                                         .replace('@VMC_PAGES@', vmc_pages)), WRITE_REPLY_WANT)

# Source shape: every smb.c function that waits on smb_io_sema signals it before each later return.
code = re.sub(r'//[^\n]*', '', smb)
waiters = []
for match in re.finditer(r'^(?:static\s+)?int\s+(\w+)\([^;{]*\)\s*\{', code, re.M):
    body = code[match.start():code.index('\n}', match.start()) + 2]
    if 'WAITIOSEMA(smb_io_sema);' not in body:
        continue
    waiters.append(match.group(1))
    lines = [line.strip() for line in body[body.index('WAITIOSEMA(smb_io_sema);'):].split('\n')]
    statements = [line for line in lines if line and line not in ('{', '}')]
    for index, line in enumerate(statements):
        if line.startswith('return') and statements[index - 1] != 'SIGNALIOSEMA(smb_io_sema);':
            failures.append('%s: %s() returns "%s" without SIGNALIOSEMA(smb_io_sema)' % (SMB, match.group(1), line))
if sorted(waiters) != ['smb_OpenAndX', 'smb_ReadFile', 'smb_WriteFile']:
    failures.append('%s: expected smb_OpenAndX, smb_ReadFile and smb_WriteFile to take smb_io_sema, found %s' % (SMB, waiters))

# smb_Close() runs from oplShutdown() after DeviceLock() took smb_io_sema (through the mcemu shutdown
# callback and DeviceUnmount()), and from _shutdown() with interrupts disabled: it must not wait on it.
close = re.sub(r'//[^\n]*', '', function(smb, 'int smb_Close(', SMB))
if 'WAITIOSEMA' in close or 'WaitSema' in close:
    failures.append('%s: smb_Close() must not wait on smb_io_sema; its callers already hold it' % SMB)

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('SMB VMC I/O: smb_io_sema released on every failure path, failures and short pages reported to mcemu')
