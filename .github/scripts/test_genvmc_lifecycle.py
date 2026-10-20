"""Drive genvmc's real request / worker / abort bodies under controlled scheduling (#934).

StartThread never runs the worker: the test decides when it runs, so every interleaving the IOP
can produce -- a STATUS read before the worker is scheduled, an abort before it runs, an abort
racing completion -- is replayed deterministically. A WaitSema that could never be satisfied is
reported as a hang instead of blocking the test.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "modules/vmc/genvmc/genvmc.c").read_text(encoding="utf-8")
state_start = source.index("static int genvmc_io_sema")
state = source[state_start:source.index("\n//----", state_start)]
body = source[source.index("static int genvmc_init(iop_device_t *dev)\n{"):source.index("int _start(")]
writer_start = source.index("static int mc_writecluster(")
writer = source[writer_start:source.index("\n}\n", writer_start) + 3]

program = r'''
#include <errno.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "genvmc.h"

#define remove fs_remove
#define DPRINTF(...) do { } while (0)
#define MODNAME "genvmc"
#define TH_C 0x02000000
#define IOP_MUTEX_LOCKED 0
#define IOP_MUTEX_UNLOCKED 1

typedef struct iop_device { int unused; } iop_device_t;
typedef struct iop_file { int unused; } iop_file_t;
typedef struct { unsigned int attr, option; void *thread; unsigned int stacksize, priority; } iop_thread_t;

/* ---- semaphores: a wait that no other party can ever signal is a hang ---- */
static int semTokens[16], semAlive[16], semCount;
static jmp_buf hang;
int CreateSema_(int tokens) { semTokens[semCount] = tokens; semAlive[semCount] = 1; return semCount++; }
#define CreateMutex(t) CreateSema_(t)
int DeleteSema(int id) { semAlive[id] = 0; return 0; }
int WaitSema(int id)
{
    if (id < 0 || id >= semCount || !semAlive[id] || semTokens[id] == 0)
        longjmp(hang, 1);
    semTokens[id]--;
    return 0;
}
int SignalSema(int id)
{
    if (id >= 0 && id < semCount && semAlive[id])
        semTokens[id]++;
    return 0;
}

/* ---- threads: started, never run until the test says so ---- */
static void (*pendingEntry)(void *);
static void *pendingArg;
static int created, deleted, exited, createResult, startResult, lastThid;
int CreateThread(iop_thread_t *t)
{
    if (createResult < 0)
        return createResult;
    created++;
    pendingEntry = (void (*)(void *))t->thread;
    return lastThid = 40 + created;
}
int StartThread(int thid, void *arg)
{
    (void)thid;
    if (startResult < 0)
        return startResult;
    pendingArg = arg;
    return 0;
}
int DeleteThread(int thid) { if (thid == lastThid) deleted++; pendingEntry = NULL; return 0; }
void ExitDeleteThread(void) { exited++; }

@STATE@

/* ---- the real cluster writer, over a device whose write can stall ---- */
#define SEEK_SET 0
typedef struct { int cluster_size; } MCDevInfo;
static MCDevInfo devinfo = {512};
static int abortInsideWrite;
static int genvmc_devctl(iop_file_t *f, const char *name, int cmd, void *args, unsigned int arglen, void *buf, unsigned int buflen);
int lseek(int fd, int offset, int whence) { (void)fd; (void)whence; return offset; }
int write(int fd, void *buf, int count)
{
    (void)fd; (void)buf;
    if (abortInsideWrite) /* the device stalls in write(); the user presses Abort meanwhile */
        genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_ABORT, NULL, 0, NULL, 0);
    return count;
}
@WRITER@

/* ---- the job itself ---- */
static int formatResult, formats, removes, removeSawBusy, abortDuringFormat, formatterOwns;
static char formatName[1024], removedName[1024];
static int vmc_mcformat(char *filename, int size_kb, int blocksize, int *progress, char *msg)
{
    static char cluster[1024];
    (void)size_kb; (void)blocksize; (void)msg;
    genvmc_owns_file = formatterOwns;
    formats++;
    strcpy(formatName, filename);
    *progress = 50;
    if (abortDuringFormat) /* another thread cancels while the card is being written */
        genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_ABORT, NULL, 0, NULL, 0);
    if (abortInsideWrite && mc_writecluster(3, 0, cluster, 1) == 0 && mc_writecluster(3, 1, cluster, 1) == -2)
        return -1000; /* the next cluster sees the abort, as the real formatter does */
    return genvmc_abort ? -1000 : formatResult;
}
static int vmc_mccopy(char *filename, int slot, int *progress, char *msg)
{
    (void)slot;
    return vmc_mcformat(filename, 0, 0, progress, msg);
}
static int vmc_rebuild(char *filename, int size_kb, int *progress, char *msg)
{
    return vmc_mcformat(filename, size_kb, 16, progress, msg); /* copy mode: test_vmc_rebuild.py */
}
int fs_remove(const char *path)
{
    removes++;
    strcpy(removedName, path);
    removeSawBusy = genvmc_stats.VMC_status == GENVMC_STAT_BUSY;
    return 0;
}

@BODY@

static int failures;
#define CHECK(cond, what) do { if (!(cond)) { printf("FAIL: %s\n", what); failures++; } } while (0)

static void reset(void)
{
    semCount = 0;
    memset(&genvmc_stats, 0, sizeof(genvmc_stats));
    genvmc_abort = 0;
    pendingEntry = NULL;
    pendingArg = NULL;
    created = deleted = exited = createResult = startResult = lastThid = 0;
    formatResult = formats = removes = removeSawBusy = abortDuringFormat = abortInsideWrite = 0;
    formatName[0] = removedName[0] = '\0';
    genvmc_init(NULL);
}

static void runWorker(void)
{
    void (*entry)(void *) = pendingEntry;
    pendingEntry = NULL;
    if (entry)
        entry(pendingArg);
}

static int create(createVMCparam_t *p, const char *path)
{
    memset(p, 0, sizeof(*p));
    strcpy(p->VMC_filename, path);
    p->VMC_size_mb = 8;
    p->VMC_blocksize = 16;
    p->VMC_thread_priority = 0x0f;
    p->VMC_card_slot = -1;
    return genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_CREATE_VMC, p, sizeof(*p), NULL, 0);
}

static statusVMCparam_t status(void)
{
    statusVMCparam_t s;
    memset(&s, 0xff, sizeof(s));
    genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_STATUS, NULL, 0, &s, sizeof(s));
    return s;
}

static int abortJob(void)
{
    return genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_ABORT, NULL, 0, NULL, 0);
}

#define SCENARIO(name) \
    reset();           \
    if (setjmp(hang)) { printf("FAIL: %s: a semaphore wait can never be satisfied (hang)\n", name); failures++; } else

int main(void)
{
    createVMCparam_t a, b;

    SCENARIO("accepted_job_reads_busy") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "a create on an idle driver is accepted");
        CHECK(status().VMC_status == GENVMC_STAT_BUSY, "STATUS reads busy right after an accepted create, before the worker runs");
        runWorker();
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL && status().VMC_error == 0 && status().VMC_progress == 100,
              "a finished job reads available, no error, 100%");
    }

    SCENARIO("job_owns_its_parameters") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "create accepted");
        strcpy(a.VMC_filename, "mass:VMC/SOMEONE_ELSE.bin"); /* the RPC buffer is reused */
        a.VMC_card_slot = 0;
        runWorker();
        CHECK(strcmp(formatName, "mass:VMC/A.bin") == 0, "the worker builds the file named in the request, not what the buffer holds now");
    }

    SCENARIO("failure_cleanup_uses_owned_name") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "create accepted");
        strcpy(a.VMC_filename, "mass:VMC/SAVES.bin");
        formatResult = -5;
        runWorker();
        CHECK(removes == 1 && strcmp(removedName, "mass:VMC/A.bin") == 0, "a failed job removes ITS partial file, never another name");
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL && status().VMC_error == -5, "the failure is reported");
    }

    SCENARIO("overlapping_create_rejected") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "first create accepted");
        CHECK(create(&b, "mass:VMC/B.bin") == -EBUSY, "a second create while the first is pending is refused as busy");
        CHECK(created == 1, "no second worker thread is made");
        runWorker();
        CHECK(strcmp(formatName, "mass:VMC/A.bin") == 0 && formats == 1, "only the first job runs");
        CHECK(create(&b, "mass:VMC/B.bin") == 0, "once idle, the next create is accepted");
    }

    SCENARIO("abort_before_worker_runs") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "create accepted");
        CHECK(abortJob() == 0, "abort returns without waiting for the worker");
        CHECK(status().VMC_status == GENVMC_STAT_BUSY, "still busy until the worker has wound down");
        runWorker();
        CHECK(formats == 0 && removes == 0, "a job cancelled before it ran never touches the file");
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL && status().VMC_error == -1000, "it reports aborted, then available");
    }

    SCENARIO("abort_during_format") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "create accepted");
        abortDuringFormat = 1;
        runWorker();
        CHECK(removes == 1 && strcmp(removedName, "mass:VMC/A.bin") == 0, "the aborted partial file is removed");
        CHECK(removeSawBusy, "status stays busy until the partial file is removed");
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL && status().VMC_error == -1000, "then reads aborted and available");
    }

    SCENARIO("abort_while_write_stalls") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "create accepted");
        abortInsideWrite = 1;
        runWorker();
        CHECK(removes == 1 && removeSawBusy, "the abort lands, the partial file is removed while still busy");
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL && status().VMC_error == -1000, "then reads aborted and available");
    }

    SCENARIO("abort_after_completion") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "create accepted");
        runWorker();
        CHECK(abortJob() == 0, "an abort after the job finished returns at once");
        CHECK(abortJob() == 0, "and again (idempotent)");
        CHECK(status().VMC_error == 0 && removes == 0, "a finished card is left alone");
        CHECK(create(&b, "mass:VMC/B.bin") == 0, "next create accepted");
        runWorker();
        CHECK(formats == 2 && status().VMC_error == 0, "a late abort does not cancel the next job");
    }

    SCENARIO("create_thread_fails") {
        createResult = -400;
        CHECK(create(&a, "mass:VMC/A.bin") < 0, "a create whose thread cannot be made fails");
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL, "and leaves the driver idle");
        createResult = 0;
        CHECK(create(&b, "mass:VMC/B.bin") == 0, "so a retry is accepted");
    }

    SCENARIO("start_thread_fails") {
        startResult = -401;
        CHECK(create(&a, "mass:VMC/A.bin") < 0, "a create whose thread cannot start fails");
        CHECK(deleted == 1, "the unstarted thread is deleted");
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL, "and the driver is idle");
        startResult = 0;
        CHECK(create(&b, "mass:VMC/B.bin") == 0, "so a retry is accepted");
    }

    SCENARIO("short_request_refused") {
        memset(&a, 0, sizeof(a));
        CHECK(genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_CREATE_VMC, &a, 8, NULL, 0) < 0, "a create shorter than the request struct is refused");
        CHECK(created == 0, "and starts nothing");
    }

    SCENARIO("invalid_native_allocation_request_refused") {
        memset(&a, 0, sizeof(a));
        strcpy(a.VMC_filename, "mass:VMC/A.bin");
        a.VMC_flags = VMC_CREATE_CONTIGUOUS;
        a.VMC_card_slot = -1;
        CHECK(genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_CREATE_VMC, &a, sizeof(a), NULL, 0) < 0, "invalid size/block geometry refused");
        a.VMC_size_mb = 8; a.VMC_blocksize = 16; a.VMC_card_slot = 0;
        CHECK(genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_CREATE_VMC, &a, sizeof(a), NULL, 0) < 0, "copy requests cannot reserve new files");
        CHECK(created == 0, "invalid requests start nothing");
    }
    SCENARIO("pfs_reservation_flag_accepted_unknown_flags_refused") {
        memset(&a, 0, sizeof(a));
        strcpy(a.VMC_filename, "pfs0:VMC/A.bin");
        a.VMC_size_mb = 8; a.VMC_blocksize = 16; a.VMC_thread_priority = 0x0f; a.VMC_card_slot = -1;
        a.VMC_flags = 8; /* 4 is VMC_CREATE_REBUILD */
        CHECK(genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_CREATE_VMC, &a, sizeof(a), NULL, 0) < 0 && created == 0, "an unknown flag is still refused");
        a.VMC_flags = VMC_CREATE_PFS_RESERVE;
        CHECK(genvmc_devctl(NULL, "genvmc:", GENVMC_DEVCTL_CREATE_VMC, &a, sizeof(a), NULL, 0) == 0 && created == 1, "an HDD card's PFS reservation flag is accepted");
        CHECK(genvmc_job.VMC_flags == VMC_CREATE_PFS_RESERVE, "and reaches the job");
        runWorker();
        CHECK(status().VMC_status == GENVMC_STAT_AVAIL && genvmc_stats.VMC_error == 0, "and the job completes normally");
    }
    SCENARIO("contiguous_preopen_failure_preserves_file") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "accepted");
        genvmc_job.VMC_flags = VMC_CREATE_CONTIGUOUS;
        formatterOwns = 0; formatResult = -111;
        runWorker();
        CHECK(removes == 0, "unsupported capability must not remove any file");
    }
    SCENARIO("contiguous_allocation_failure_removes_only_owned_file") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "accepted");
        genvmc_job.VMC_flags = VMC_CREATE_CONTIGUOUS;
        formatterOwns = 1; formatResult = -112;
        runWorker();
        CHECK(removes == 1 && removeSawBusy, "only this job's exclusive new file is removed before status");
        formatterOwns = 0;
    }
    SCENARIO("close_failure_has_its_own_message") {
        CHECK(create(&a, "mass:VMC/A.bin") == 0, "accepted");
        formatResult = -114;
        runWorker();
        CHECK(genvmc_stats.VMC_error == -114, "close failure retained");
        CHECK(strcmp(genvmc_stats.VMC_msg, "Cannot close the VMC file") == 0, "close is not mislabeled as layout failure");
    }
    genvmc_deinit(NULL);
    if (failures)
        return 1;
    printf("genvmc lifecycle: owned job, busy on accept, no overlap, non-blocking abort, idle after cleanup\n");
    return 0;
}
'''.replace("@STATE@", state).replace("@WRITER@", writer).replace("@BODY@", body)

with tempfile.TemporaryDirectory() as directory:
    cfile, exe = Path(directory) / "test.c", Path(directory) / "test"
    cfile.write_text(program, encoding="utf-8")
    subprocess.run(["gcc", "-std=gnu99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                    "-I", str(root / "modules/vmc/genvmc"), str(cfile), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
