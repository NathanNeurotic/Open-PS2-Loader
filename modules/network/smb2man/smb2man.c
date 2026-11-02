/*
  smb2man -- the SMB2 browse driver for the menu (game lists, art, configs, VMC files, the
  file manager). Chosen instead of smbman when Settings > Network > SMB Version is SMB2.

  It registers the same iomanX device as smbman ("smb", so every "smb0:" path is unchanged) and
  answers the same devctl interface from ps2smb.h (LOGON, OPENSHARE, GETSHARELIST, ...), so the EE
  side only chooses which of the two modules to load. Only one of them is ever resident.

  The protocol work is Ronnie Sahlberg's libsmb2, vendored unmodified under libsmb2/ (see
  libsmb2/VENDORED.txt for the commit). libsmb2 can negotiate up to SMB 3.1.1, but this driver offers
  only 2.0.2 and 2.1, the dialects the in-game reader speaks (smb2man_new_context). It does NTLMv2
  and signs when the server asks for it. This file is only the iomanX/devctl front end, and the
  allocator libsmb2 needs on the IOP.

  It follows the earlier Open-PS2-Loader master implementation (modules/network/smb2man/smb2man.c,
  OPL PRs #278/#286/#291) with these changes: libsmb2 is current upstream built with its own IOP
  support instead of local shims; reads and writes loop until the request is done, because libsmb2
  caps one call at the server's maximum transfer size; open() reports EACCES/EBUSY/ENOENT from the
  server status; GETSHARELIST enumerates the server's disk shares.

  The menu's SMB1 driver (smbman) is unchanged.

  Licence: this front end is distributed under the GNU LGPL 2.1 or later, like the libsmb2 it links
  (libsmb2/COPYING). Parts of the allocator follow libsmb2's lib/ps2/smb2man.c.
*/

#include <stdint.h>

#include <errno.h>
#include <fcntl.h>
#include <intrman.h>
#include <iomanX.h>
#include <loadcore.h>
#include <sifman.h>
#include <stdio.h>
#include <sysclib.h>
#include <sysmem.h>
#include <thbase.h>
#include <thsemap.h>

#include <ps2smb.h>

#include <smb2/smb2.h>
#include <smb2/libsmb2.h>
#include <smb2/libsmb2-share-enum.h>
#include <smb2/libsmb2-raw.h>

#define MODNAME "smb2man"
IRX_ID(MODNAME, 1, 2);

#define MAX_OPEN_FILES          8
#define MAX_PATH_LEN            512
// libsmb2's synchronous calls wait this long for a reply. Without a timeout a dead server would
// hold the driver lock, and with it the menu's IO thread, forever.
#define SMB2MAN_TIMEOUT_SECONDS 15

static struct smb2_context *smb2 = NULL;
static int smb2_sema = -1;

// LOGON only records the server and credentials: libsmb2 logs on as part of connecting a share.
static char conn_server[64];
static char conn_user[256];
static char conn_password[256];
static char conn_share[256]; // the share OPENSHARE connected, for the keepalive's reconnect
static int conn_valid = 0;
static int share_open = 0;
// Set when a share that was open is gone (a read or write whose reply never came, a failed
// keepalive) and nothing has connected it again. ECHO reports it, so the menu's Refresh
// reconnects at once, as it does with smbman; LOGON, OPENSHARE and LOGOFF clear it.
static int session_lost = 0;

/*
  Keepalive, as smbman's: every KEEPALIVE_SECONDS an alarm wakes a thread that sends an SMB2 ECHO
  on the open session. It keeps a Windows server's idle autodisconnect (15 minutes by default) from
  dropping the session while the menu sits still, and when the server did drop it, the thread tears
  the session down and connects the share again. A failed reconnect is retried only every
  KEEPALIVE_RETRY_SECONDS: each attempt can wait the full SMB2MAN_TIMEOUT_SECONDS with the driver
  locked, and a server that is off should not keep the menu's IO thread waiting on it.
*/
#define KEEPALIVE_SECONDS       3
#define KEEPALIVE_RETRY_SECONDS 30
static int keepalive_sema = -1;
static int keepalive_tid = -1;
static iop_sys_clock_t keepalive_clock;
static u32 keepalive_ticks = 0;    // alarm ticks since start, for the retry backoff
static u32 keepalive_retry_at = 0; // tick at which the next reconnect may be tried

struct smb2man_file
{
    struct smb2fh *fh;
    int used;
    unsigned gen; // bumped on every open of this slot; privdata carries it (see smb2man_slot)
};

// privdata = slot | gen << SMB2MAN_SLOT_BITS. MAX_OPEN_FILES must fit in the slot bits.
#define SMB2MAN_SLOT_BITS 4
#define SMB2MAN_GEN_MASK  (0x7FFFFFFFu >> SMB2MAN_SLOT_BITS)

static struct smb2man_file file_table[MAX_OPEN_FILES];

#define LOCK()   WaitSema(smb2_sema)
#define UNLOCK() SignalSema(smb2_sema)

//-------------------------------------------------------------------------
// Allocator for libsmb2 (the IOP has no libc heap). As in libsmb2's lib/ps2/smb2man.c.
void *malloc(int size)
{
    void *result;
    int OldState;

    CpuSuspendIntr(&OldState);
    result = AllocSysMemory(ALLOC_FIRST, size, NULL);
    CpuResumeIntr(OldState);

    return result;
}

void free(void *ptr)
{
    int OldState;

    if (ptr == NULL)
        return;

    CpuSuspendIntr(&OldState);
    FreeSysMemory(ptr);
    CpuResumeIntr(OldState);
}

void *calloc(size_t nmemb, size_t size)
{
    size_t s = nmemb * size;
    void *ptr;

    if (size != 0 && s / size != nmemb)
        return NULL;

    ptr = malloc((int)s);
    if (ptr != NULL)
        memset(ptr, 0, s);

    return ptr;
}

void *realloc(void *ptr, size_t size)
{
    void *n;
    size_t old, ncopy;

    if (ptr == NULL)
        return malloc((int)size);
    if (size == 0) {
        free(ptr);
        return NULL;
    }

    old = QueryBlockSize(ptr);
    n = malloc((int)size);
    if (n == NULL)
        return NULL;
    ncopy = (old < size) ? old : size;
    memcpy(n, ptr, ncopy);
    free(ptr);

    return n;
}

//-------------------------------------------------------------------------
/*
  OPL builds share paths with backslashes and a leading separator ("\CD\FOO.ISO"). libsmb2 wants
  forward slashes, relative to the share root. Returns -ENAMETOOLONG rather than truncating, so an
  over-long name can never open a different, shorter file.
*/
static int smb2man_fixpath(char *out, const char *in, int outmax)
{
    int i = 0;

    while (*in == '\\' || *in == '/')
        in++;

    while (*in != '\0') {
        if (i >= outmax - 1)
            return -ENAMETOOLONG;
        out[i++] = (*in == '\\') ? '/' : *in;
        in++;
    }

    out[i] = '\0';
    return 0;
}

// A negative errno for the last failed libsmb2 call: the server's status where there is one.
static int smb2man_errno(int fallback)
{
    int err;

    if (smb2 == NULL)
        return fallback;

    err = nterror_to_errno((uint32_t)smb2_get_nterror(smb2));
    return (err > 0) ? -err : fallback;
}

//-------------------------------------------------------------------------
static void smb2man_keepalive_thread(void *arg);
static unsigned int smb2man_keepalive_alarm(void *arg);

static int smb2man_init(iop_device_t *dev)
{
    iop_sema_t smp;
    iop_thread_t thread;

    (void)dev;

    smp.initial = 1;
    smp.max = 1;
    smp.option = 0;
    smp.attr = 1;
    smb2_sema = CreateSema(&smp);

    memset(file_table, 0, sizeof(file_table));

    if (smb2_sema < 0)
        return -1;

    // The keepalive: the alarm signals this semaphore, the thread does the network work.
    smp.initial = 0;
    smp.max = 1;
    keepalive_sema = CreateSema(&smp);

    thread.attr = TH_C;
    thread.option = 0;
    thread.thread = smb2man_keepalive_thread;
    thread.stacksize = 0x2000; // libsmb2 sync calls run on it: socket.c keeps SMB2_MAX_VECTORS iovecs on the stack
    thread.priority = 0x64;
    keepalive_tid = CreateThread(&thread);
    if (keepalive_sema >= 0 && keepalive_tid >= 0 && StartThread(keepalive_tid, NULL) == 0) {
        USec2SysClock(KEEPALIVE_SECONDS * 1000 * 1000, &keepalive_clock);
        SetAlarm(&keepalive_clock, smb2man_keepalive_alarm, NULL);
    } else {
        printf("smb2man: no keepalive (sema %d, thread %d)\n", keepalive_sema, keepalive_tid);
    }

    return 0;
}

static int smb2man_deinit(iop_device_t *dev)
{
    int oldstate;

    (void)dev;

    CpuSuspendIntr(&oldstate);
    CancelAlarm(smb2man_keepalive_alarm, NULL);
    CpuResumeIntr(oldstate);

    if (smb2_sema >= 0) {
        DeleteSema(smb2_sema);
        smb2_sema = -1;
    }

    return 0;
}

//-------------------------------------------------------------------------
static int smb2man_alloc_fd(void)
{
    int i;

    for (i = 0; i < MAX_OPEN_FILES; i++) {
        if (!file_table[i].used)
            return i;
    }

    return -1;
}

/*
  libsmb2's sync read/write return exactly -1 when waiting for the reply failed (poll or
  smb2_service error). The request is then still queued, and it still points at the caller's
  buffer, so a late reply could land in memory the caller has reused. Destroy the context (that
  frees every queued request without more network I/O) and forget the open handles; the menu's
  next OPENSHARE builds a fresh session. (A status-mapped -EPERM also ends here: those statuses
  mean the handle is gone anyway.) Called with the lock held.
*/
static void smb2man_drop_session(void)
{
    int i;

    for (i = 0; i < MAX_OPEN_FILES; i++) {
        file_table[i].fh = NULL;
        file_table[i].used = 0;
    }
    if (smb2 != NULL) {
        smb2_destroy_context(smb2);
        smb2 = NULL;
    }
    if (share_open) {
        share_open = 0;
        session_lost = 1;
        keepalive_retry_at = keepalive_ticks; // the first reconnect goes out on the next tick
    }
}

static void smb2man_drop_broken_session(int rv)
{
    if (rv != -1 || smb2 == NULL)
        return;

    smb2man_drop_session();
}

/*
  A handle whose slot was cleared (share change, logoff, a dropped session) and then reused by a
  later open must not reach the new file: the slot's generation no longer matches the one stored
  in the stale handle's privdata, so it gets -EBADF instead.
*/
static int smb2man_slot(iop_file_t *f)
{
    unsigned v = (unsigned)(uintptr_t)f->privdata;
    unsigned slot = v & ((1u << SMB2MAN_SLOT_BITS) - 1);

    if (slot >= MAX_OPEN_FILES || !file_table[slot].used || file_table[slot].gen != (v >> SMB2MAN_SLOT_BITS))
        return -1;

    return (int)slot;
}

/*
  Open flags for libsmb2. libsmb2.c takes O_RDONLY/O_WRONLY/O_RDWR/O_CREAT/O_TRUNC/O_EXCL from the
  <fcntl.h> it is built with, so this file uses the same header rather than hard-coded numbers. On
  the IOP that header gives the iomanX values (O_RDONLY 1, O_WRONLY 2, O_RDWR 3, as FIO_O_*); a
  table of POSIX numbers (0/1/2) here would open every read-only file with no read access and turn
  read-write opens into write-only ones.
*/
static int smb2man_open(iop_file_t *f, const char *filename, int flags, int mode)
{
    char path[MAX_PATH_LEN];
    struct smb2fh *fh;
    int slot, oflags, rv;

    (void)mode;

    if (filename == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    slot = smb2man_alloc_fd();
    if (slot < 0) {
        UNLOCK();
        return -EMFILE;
    }

    rv = smb2man_fixpath(path, filename, sizeof(path));
    if (rv < 0) {
        UNLOCK();
        return rv;
    }

    // FIO_O_RDWR is a bit-superset of FIO_O_RDONLY and FIO_O_WRONLY, so test it first.
    if ((flags & FIO_O_RDWR) == FIO_O_RDWR)
        oflags = O_RDWR;
    else if (flags & FIO_O_WRONLY)
        oflags = O_WRONLY;
    else
        oflags = O_RDONLY;

    // libsmb2 picks the CREATE disposition from these: without O_CREAT no new file (a per-game
    // config, a VMC) could be made, and without O_TRUNC a shorter rewrite would keep the old tail.
    if (flags & FIO_O_CREAT)
        oflags |= O_CREAT;
    if (flags & FIO_O_TRUNC)
        oflags |= O_TRUNC;
    if (flags & FIO_O_EXCL)
        oflags |= O_EXCL;

    fh = smb2_open(smb2, path, oflags);
    if (fh == NULL) {
        rv = smb2man_errno(-ENOENT);
        UNLOCK();
        return rv;
    }

    file_table[slot].fh = fh;
    file_table[slot].used = 1;
    file_table[slot].gen = (file_table[slot].gen + 1) & SMB2MAN_GEN_MASK;
    f->privdata = (void *)(uintptr_t)((unsigned)slot | (file_table[slot].gen << SMB2MAN_SLOT_BITS));

    UNLOCK();

    return slot;
}

static int smb2man_close(iop_file_t *f)
{
    int slot;

    LOCK();

    slot = smb2man_slot(f);
    if (slot < 0) {
        UNLOCK();
        return -EBADF;
    }

    if (smb2 != NULL)
        smb2_close(smb2, file_table[slot].fh);
    file_table[slot].fh = NULL;
    file_table[slot].used = 0;

    UNLOCK();

    return 0;
}

/*
  One libsmb2 read or write moves at most the server's maximum transfer size (as little as 64 KB),
  so loop until the whole request is done. A read stops early only at the end of the file. The
  callers (art, configs, VMC pages) expect smbman's behaviour, where a short count means EOF.
*/
static int smb2man_read(iop_file_t *f, void *buffer, int size)
{
    uint8_t *p = (uint8_t *)buffer;
    int slot, rv, done = 0;

    if (size < 0)
        return -EINVAL;

    LOCK();

    slot = smb2man_slot(f);
    if (slot < 0 || smb2 == NULL) {
        UNLOCK();
        return -EBADF;
    }

    while (done < size) {
        rv = smb2_read(smb2, file_table[slot].fh, p + done, (uint32_t)(size - done));
        if (rv < 0) {
            smb2man_drop_broken_session(rv);
            UNLOCK();
            return (done > 0) ? done : -EIO;
        }
        if (rv == 0)
            break; // end of file
        done += rv;
    }

    UNLOCK();

    return done;
}

static int smb2man_write(iop_file_t *f, void *buffer, int size)
{
    const uint8_t *p = (const uint8_t *)buffer;
    int slot, rv, done = 0;

    if (size < 0)
        return -EINVAL;

    LOCK();

    slot = smb2man_slot(f);
    if (slot < 0 || smb2 == NULL) {
        UNLOCK();
        return -EBADF;
    }

    while (done < size) {
        rv = smb2_write(smb2, file_table[slot].fh, p + done, (uint32_t)(size - done));
        if (rv <= 0) {
            // A server that stores nothing (a full disk) must not spin this loop forever.
            smb2man_drop_broken_session(rv);
            UNLOCK();
            return (done > 0) ? done : -EIO;
        }
        done += rv;
    }

    UNLOCK();

    return done;
}

static int smb2man_lseek(iop_file_t *f, int offset, int whence)
{
    uint64_t pos = 0;
    int slot, rv;

    LOCK();

    slot = smb2man_slot(f);
    if (slot < 0 || smb2 == NULL) {
        UNLOCK();
        return -EBADF;
    }

    rv = smb2_lseek(smb2, file_table[slot].fh, (int64_t)offset, whence, &pos);

    UNLOCK();

    if (rv < 0)
        return -EIO;
    // The 32-bit call cannot report a position past 2 GB; lseek64 serves those.
    if (pos > 0x7fffffffULL)
        return -EOVERFLOW;

    return (int)pos;
}

static s64 smb2man_lseek64(iop_file_t *f, s64 offset, int whence)
{
    uint64_t pos = 0;
    int slot, rv;

    LOCK();

    slot = smb2man_slot(f);
    if (slot < 0 || smb2 == NULL) {
        UNLOCK();
        return -EBADF;
    }

    rv = smb2_lseek(smb2, file_table[slot].fh, (int64_t)offset, whence, &pos);

    UNLOCK();

    return (rv < 0) ? -EIO : (s64)pos;
}

//-------------------------------------------------------------------------
/*
  Unix seconds to the packed time in iox_stat_t: [1] second, [2] minute, [3] hour, [4] day,
  [5] month, [6..7] year (little-endian). ethsupport's change detector compares the CD folder's
  mtime between scans, so leaving these at zero would hide games added to the share.
*/
static void smb2man_pack_time(uint64_t unixsec, unsigned char *out)
{
    u32 t = (u32)unixsec;
    u32 days = t / 86400u;
    u32 rem = t % 86400u;
    u32 y, m, d;

    out[0] = 0;
    out[1] = (unsigned char)(rem % 60u);
    out[2] = (unsigned char)((rem / 60u) % 60u);
    out[3] = (unsigned char)(rem / 3600u);

    // Civil date from days since 1970-01-01 (Howard Hinnant's civil_from_days).
    {
        u32 z = days + 719468u;
        u32 era = z / 146097u;
        u32 doe = z - era * 146097u;
        u32 yoe = (doe - doe / 1460u + doe / 36524u - doe / 146096u) / 365u;
        u32 doy = doe - (365u * yoe + yoe / 4u - yoe / 100u);
        u32 mp = (5u * doy + 2u) / 153u;

        d = doy - (153u * mp + 2u) / 5u + 1u;
        m = mp + (mp < 10u ? 3u : (u32)-9);
        y = yoe + era * 400u + (m <= 2u ? 1u : 0u);
    }

    out[4] = (unsigned char)d;
    out[5] = (unsigned char)m;
    out[6] = (unsigned char)(y & 0xff);
    out[7] = (unsigned char)((y >> 8) & 0xff);
}

// The PS2's ctime is the creation time; SMB2's smb2_ctime is the change time. Use the birth time,
// or the change time when the server does not report one.
static uint64_t smb2man_btime(const struct smb2_stat_64 *st)
{
    return st->smb2_btime ? st->smb2_btime : st->smb2_ctime;
}

static void smb2man_fill_stat(iox_stat_t *stat, const struct smb2_stat_64 *st)
{
    memset(stat, 0, sizeof(iox_stat_t));
    stat->mode = (st->smb2_type == SMB2_TYPE_DIRECTORY) ? (FIO_S_IFDIR | FIO_S_IRUSR | FIO_S_IWUSR | FIO_S_IXUSR) :
                                                          (FIO_S_IFREG | FIO_S_IRUSR | FIO_S_IWUSR);
    stat->size = (unsigned int)st->smb2_size;
    stat->hisize = (unsigned int)(st->smb2_size >> 32);
    smb2man_pack_time(smb2man_btime(st), stat->ctime);
    smb2man_pack_time(st->smb2_atime, stat->atime);
    smb2man_pack_time(st->smb2_mtime, stat->mtime);
}

//-------------------------------------------------------------------------
static int smb2man_dopen(iop_file_t *f, const char *dirname)
{
    char path[MAX_PATH_LEN];
    struct smb2dir *dir;
    int rv;

    if (dirname == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    rv = smb2man_fixpath(path, dirname, sizeof(path));
    if (rv < 0) {
        UNLOCK();
        return rv;
    }

    dir = smb2_opendir(smb2, path);
    if (dir == NULL) {
        rv = smb2man_errno(-ENOENT);
        UNLOCK();
        return rv;
    }

    f->privdata = (void *)dir;

    UNLOCK();

    return 0;
}

static int smb2man_dclose(iop_file_t *f)
{
    struct smb2dir *dir;

    LOCK();

    dir = (struct smb2dir *)f->privdata;
    if (dir == NULL) {
        UNLOCK();
        return -EBADF;
    }

    if (smb2 != NULL)
        smb2_closedir(smb2, dir);
    f->privdata = NULL;

    UNLOCK();

    return 0;
}

static int smb2man_dread(iop_file_t *f, iox_dirent_t *dirent)
{
    struct smb2dir *dir;
    struct smb2dirent *ent;

    LOCK();

    dir = (struct smb2dir *)f->privdata;
    if (dir == NULL || smb2 == NULL) {
        UNLOCK();
        return -EBADF;
    }

    ent = smb2_readdir(smb2, dir);
    if (ent == NULL) {
        UNLOCK();
        return 0; // end of the directory
    }

    smb2man_fill_stat(&dirent->stat, &ent->st);
    strncpy(dirent->name, ent->name, sizeof(dirent->name) - 1);
    dirent->name[sizeof(dirent->name) - 1] = '\0';
    dirent->privdata = NULL;

    UNLOCK();

    return 1;
}

static int smb2man_getstat(iop_file_t *f, const char *filename, iox_stat_t *stat)
{
    char path[MAX_PATH_LEN];
    struct smb2_stat_64 st;
    int rv;

    (void)f;

    if (filename == NULL || stat == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    rv = smb2man_fixpath(path, filename, sizeof(path));
    if (rv == 0)
        rv = smb2_stat(smb2, path, &st);
    if (rv < 0) {
        UNLOCK();
        return (rv == -ENAMETOOLONG) ? rv : -ENOENT;
    }

    smb2man_fill_stat(stat, &st);

    UNLOCK();

    return 0;
}

//-------------------------------------------------------------------------
// Directory and file management (the file manager, sbCreateFolders' CFG/ART/VMC/... folders).
static int smb2man_mkdir(iop_file_t *f, const char *dirname, int mode)
{
    char path[MAX_PATH_LEN];
    struct smb2_stat_64 st;
    int rv;

    (void)f;
    (void)mode;

    if (dirname == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    rv = smb2man_fixpath(path, dirname, sizeof(path));
    if (rv == 0) {
        rv = smb2_mkdir(smb2, path);
        // sbCreateFolders runs on every refresh; an existing folder is not a failure.
        if (rv < 0 && smb2_stat(smb2, path, &st) == 0 && st.smb2_type == SMB2_TYPE_DIRECTORY)
            rv = 0;
        else if (rv < 0)
            rv = -EIO;
    }

    UNLOCK();

    return rv;
}

static int smb2man_rmdir(iop_file_t *f, const char *dirname)
{
    char path[MAX_PATH_LEN];
    int rv;

    (void)f;

    if (dirname == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    rv = smb2man_fixpath(path, dirname, sizeof(path));
    if (rv == 0 && smb2_rmdir(smb2, path) < 0)
        rv = smb2man_errno(-EIO);

    UNLOCK();

    return rv;
}

static int smb2man_remove(iop_file_t *f, const char *filename)
{
    char path[MAX_PATH_LEN];
    int rv;

    (void)f;

    if (filename == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    rv = smb2man_fixpath(path, filename, sizeof(path));
    if (rv == 0 && smb2_unlink(smb2, path) < 0)
        rv = smb2man_errno(-EIO);

    UNLOCK();

    return rv;
}

static int smb2man_rename(iop_file_t *f, const char *oldname, const char *newname)
{
    char oldpath[MAX_PATH_LEN];
    char newpath[MAX_PATH_LEN];
    int rv;

    (void)f;

    if (oldname == NULL || newname == NULL)
        return -EINVAL;

    LOCK();

    if (smb2 == NULL || !share_open) {
        UNLOCK();
        return -ENODEV;
    }

    rv = smb2man_fixpath(oldpath, oldname, sizeof(oldpath));
    if (rv == 0)
        rv = smb2man_fixpath(newpath, newname, sizeof(newpath));
    if (rv == 0 && smb2_rename(smb2, oldpath, newpath) < 0)
        rv = smb2man_errno(-EIO);

    UNLOCK();

    return rv;
}

//-------------------------------------------------------------------------
// Close every open handle and the session. Called with the lock held.
static void smb2man_teardown(void)
{
    int i;

    for (i = 0; i < MAX_OPEN_FILES; i++) {
        if (file_table[i].used && smb2 != NULL && share_open)
            smb2_close(smb2, file_table[i].fh);
        file_table[i].fh = NULL;
        file_table[i].used = 0;
    }

    if (smb2 != NULL) {
        if (share_open)
            smb2_disconnect_share(smb2);
        smb2_destroy_context(smb2);
        smb2 = NULL;
    }

    share_open = 0;
}

static struct smb2_context *smb2man_new_context(void)
{
    struct smb2_context *ctx = smb2_init_context();

    if (ctx == NULL)
        return NULL;

    // Sign when the server asks for it. Offer SMB 2.0.2 and 2.1 only: those are the dialects the
    // in-game reader (smb2_cdvdman) speaks, so a server the menu can list is one a game can load
    // from. An SMB 3-only server fails here, at browse, instead of hanging at game start.
    smb2_set_security_mode(ctx, SMB2_NEGOTIATE_SIGNING_ENABLED);
    smb2_set_version(ctx, SMB2_VERSION_ANY2);
    smb2_set_timeout(ctx, SMB2MAN_TIMEOUT_SECONDS);
    smb2_set_password(ctx, conn_password);

    return ctx;
}

// Connect conn_share again after the session was lost. Called with the lock held.
static void smb2man_reconnect(void)
{
    struct smb2_context *ctx = smb2man_new_context();

    if (ctx != NULL && smb2_connect_share(ctx, conn_server, conn_share, conn_user[0] ? conn_user : NULL) == 0) {
        if (smb2 != NULL)
            smb2_destroy_context(smb2);
        smb2 = ctx;
        share_open = 1;
        session_lost = 0;
        printf("smb2man: reconnected %s\n", conn_share);
        return;
    }

    if (ctx != NULL)
        smb2_destroy_context(ctx);
    keepalive_retry_at = keepalive_ticks + KEEPALIVE_RETRY_SECONDS / KEEPALIVE_SECONDS;
}

static unsigned int smb2man_keepalive_alarm(void *arg)
{
    (void)arg;

    keepalive_ticks++;
    iSignalSema(keepalive_sema);
    iSetAlarm(&keepalive_clock, smb2man_keepalive_alarm, NULL);

    return 0;
}

static void smb2man_keepalive_thread(void *arg)
{
    (void)arg;

    for (;;) {
        WaitSema(keepalive_sema);

        LOCK();
        if (smb2 != NULL && share_open) {
            if (smb2_echo(smb2) < 0) {
                printf("smb2man: keepalive echo failed, session dropped\n");
                smb2man_drop_session();
            }
        } else if (session_lost && conn_valid && (int)(keepalive_ticks - keepalive_retry_at) >= 0) {
            smb2man_reconnect();
        }
        UNLOCK();
    }
}

// Copy to EE memory, as smbman does for GETSHARELIST.
static void smb2man_copy_to_ee(void *ee_addr, void *src, int size)
{
    SifDmaTransfer_t dmat;
    int oldstate, id;

    dmat.src = src;
    dmat.dest = ee_addr;
    dmat.size = (size + 15) & ~15;
    dmat.attr = 0;

    do {
        CpuSuspendIntr(&oldstate);
        id = sceSifSetDma(&dmat, 1);
        CpuResumeIntr(oldstate);
    } while (id == 0);

    while (sceSifDmaStat(id) >= 0)
        DelayThread(100);
}

/*
  The server's disk shares, for the share picker the menu shows when no share name is set. Lists
  them over a second connection to IPC$, so an open share is not disturbed. Hidden ($) shares are
  left out, as Windows Explorer does.
*/
static int smb2man_getsharelist(smbGetShareList_in_t *in)
{
    struct smb2_context *ctx;
    struct smb2_share_enum_reply *rep;
    ShareEntry_t *entry;
    u32 i;
    int count = 0;

    if (in->maxent <= 0 || in->EE_addr == NULL)
        return -EINVAL;

    ctx = smb2man_new_context();
    if (ctx == NULL)
        return -ENOMEM;

    if (smb2_connect_share(ctx, conn_server, "IPC$", conn_user[0] ? conn_user : NULL) < 0) {
        smb2_destroy_context(ctx);
        return -EIO;
    }

    rep = smb2_share_enum_sync(ctx, SMB2_SHARE_INFO_1);
    if (rep == NULL) {
        smb2_disconnect_share(ctx);
        smb2_destroy_context(ctx);
        return -EIO;
    }

    entry = (ShareEntry_t *)malloc(sizeof(ShareEntry_t));
    if (entry == NULL) {
        smb2_free_data(ctx, rep);
        smb2_disconnect_share(ctx);
        smb2_destroy_context(ctx);
        return -ENOMEM;
    }

    for (i = 0; i < rep->entries_read && count < in->maxent; i++) {
        const struct smb2_share_info_1 *info = &rep->share_info.info_1[i];

        if ((info->type & 3) != SMB2_SHARE_TYPE_DISKTREE || (info->type & SMB2_SHARE_TYPE_HIDDEN) || info->netname == NULL)
            continue;

        memset(entry, 0, sizeof(ShareEntry_t));
        strncpy(entry->ShareName, info->netname, sizeof(entry->ShareName) - 1);
        if (info->remark != NULL)
            strncpy(entry->ShareComment, info->remark, sizeof(entry->ShareComment) - 1);

        smb2man_copy_to_ee((u8 *)in->EE_addr + count * sizeof(ShareEntry_t), entry, sizeof(ShareEntry_t));
        count++;
    }

    free(entry);
    smb2_free_data(ctx, rep);
    smb2_disconnect_share(ctx);
    smb2_destroy_context(ctx);

    return count;
}

static int smb2man_devctl(iop_file_t *f, const char *name, int cmd, void *arg, unsigned int arglen, void *buf, unsigned int buflen)
{
    int rv;

    (void)f;
    (void)name;
    (void)buf;
    (void)buflen;

    switch (cmd) {
        case SMB_DEVCTL_GETPASSWORDHASHES:
            // libsmb2 runs NTLMSSP itself and needs the password as typed. Failing here makes the
            // menu send it as PLAINTEXT_PASSWORD; it still goes to the server only as an NTLM
            // response, never in the clear.
            return -1;

        case SMB_DEVCTL_LOGON: {
            smbLogOn_in_t *logon = (smbLogOn_in_t *)arg;

            if (arg == NULL || arglen < sizeof(smbLogOn_in_t))
                return -EINVAL;

            LOCK();
            smb2man_teardown();
            conn_valid = 0;
            session_lost = 0;

            // libsmb2 takes the port as "<host>:<port>" (a bare host means 445).
            if (logon->serverPort > 0 && logon->serverPort != 445)
                sprintf(conn_server, "%.15s:%d", logon->serverIP, logon->serverPort);
            else
                sprintf(conn_server, "%.15s", logon->serverIP);

            strncpy(conn_user, logon->User, sizeof(conn_user) - 1);
            conn_user[sizeof(conn_user) - 1] = '\0';

            // On the no-password path the menu leaves logon->Password uninitialised.
            if (logon->PasswordType == PLAINTEXT_PASSWORD) {
                strncpy(conn_password, logon->Password, sizeof(conn_password) - 1);
                conn_password[sizeof(conn_password) - 1] = '\0';
            } else {
                conn_password[0] = '\0';
            }

            smb2 = smb2man_new_context();
            if (smb2 == NULL) {
                UNLOCK();
                return -SMB_DEVCTL_LOGON_ERR_CONN;
            }

            conn_valid = 1;
            UNLOCK();
            return 0;
        }

        case SMB_DEVCTL_LOGOFF:
            LOCK();
            smb2man_teardown();
            conn_valid = 0;
            session_lost = 0;
            UNLOCK();
            return 0;

        case SMB_DEVCTL_OPENSHARE: {
            smbOpenShare_in_t *openshare = (smbOpenShare_in_t *)arg;

            if (arg == NULL || arglen < sizeof(smbOpenShare_in_t))
                return -EINVAL;

            LOCK();

            if (!conn_valid) {
                UNLOCK();
                return -ENODEV;
            }

            // A fresh context per share: libsmb2 cannot reconnect a context it disconnected.
            smb2man_teardown();
            session_lost = 0;
            smb2 = smb2man_new_context();
            if (smb2 == NULL) {
                UNLOCK();
                return -SMB_DEVCTL_LOGON_ERR_CONN;
            }

            openshare->ShareName[sizeof(openshare->ShareName) - 1] = '\0';
            strncpy(conn_share, openshare->ShareName, sizeof(conn_share) - 1);
            conn_share[sizeof(conn_share) - 1] = '\0';
            rv = smb2_connect_share(smb2, conn_server, conn_share, conn_user[0] ? conn_user : NULL);
            if (rv < 0) {
                UNLOCK();
                return -SMB_DEVCTL_LOGON_ERR_LOGON;
            }

            share_open = 1;
            UNLOCK();
            return 0;
        }

        case SMB_DEVCTL_CLOSESHARE:
            LOCK();
            if (share_open) {
                smb2man_teardown();
                // Keep the logon: a later OPENSHARE builds a new context from it.
                smb2 = smb2man_new_context();
            }
            session_lost = 0;
            UNLOCK();
            return 0;

        case SMB_DEVCTL_ECHO:
            /*
              The menu's Refresh probes the session with this before deciding between "keep the
              open handles" and "log on again" (ethsupport's refresh path), so it has to tell the
              truth. With a share open it is a real SMB2 ECHO round trip; a share that was open and
              is gone reports -EIO until something connects it again. Between LOGON and OPENSHARE
              there is no session yet (libsmb2 logs on when it connects a share): 0, as before, and
              OPENSHARE is the call whose failure the menu reports.
            */
            if (!conn_valid)
                return -ENODEV;
            LOCK();
            if (smb2 != NULL && share_open) {
                rv = 0;
                if (smb2_echo(smb2) < 0) {
                    smb2man_drop_session();
                    rv = -EIO;
                }
            } else {
                rv = session_lost ? -EIO : 0;
            }
            UNLOCK();
            return rv;

        case SMB_DEVCTL_GETSHARELIST:
            if (arg == NULL || arglen < sizeof(smbGetShareList_in_t))
                return -EINVAL;
            LOCK();
            rv = conn_valid ? smb2man_getsharelist((smbGetShareList_in_t *)arg) : -ENODEV;
            UNLOCK();
            return rv;

        case SMB_DEVCTL_QUERYDISKINFO:
            // Only used to show free space, which the menu does not do for SMB.
            return -1;
    }

    return -EINVAL;
}

static int smb2man_nulldev(void)
{
    return -EIO;
}

static s64 smb2man_nulldev64(void)
{
    return -EIO;
}

static iop_device_ops_t smb2man_ops = {
    &smb2man_init,
    &smb2man_deinit,
    (void *)&smb2man_nulldev, // format
    &smb2man_open,
    &smb2man_close,
    &smb2man_read,
    &smb2man_write,
    &smb2man_lseek,
    (void *)&smb2man_nulldev, // ioctl
    &smb2man_remove,
    &smb2man_mkdir,
    &smb2man_rmdir,
    &smb2man_dopen,
    &smb2man_dclose,
    &smb2man_dread,
    &smb2man_getstat,
    (void *)&smb2man_nulldev, // chstat
    &smb2man_rename,
    (void *)&smb2man_nulldev, // chdir
    (void *)&smb2man_nulldev, // sync
    (void *)&smb2man_nulldev, // mount
    (void *)&smb2man_nulldev, // umount
    &smb2man_lseek64,
    &smb2man_devctl,
    (void *)&smb2man_nulldev,   // symlink
    (void *)&smb2man_nulldev,   // readlink
    (void *)&smb2man_nulldev64, // ioctl2
};

static iop_device_t smb2man_dev = {
    "smb",
    IOP_DT_FS | IOP_DT_FSEXT,
    1,
    "SMB2",
    &smb2man_ops,
};

int _start(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    printf("smb2man: SMB2 browse driver, libsmb2 (c) Ronnie Sahlberg\n");

    DelDrv(smb2man_dev.name);
    if (AddDrv(&smb2man_dev) != 0)
        return MODULE_NO_RESIDENT_END;

    return MODULE_RESIDENT_END;
}
