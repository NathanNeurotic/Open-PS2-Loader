/*
  No-IOP-reset ELF handoff (NHDDL parity) for the Neutrino launch path.

  ps2sdk's LoadELFFromFileWithPartition SifLoadElf()s the target through the live IOP but then
  SifIopReset()s and reloads ONLY rom0:SIO2MAN/MCMAN/MCSERV before jumping in
  (ee/elf-loader/src/loader/src/loader.c). Neutrino must read its config/modules (-cwd) and open
  the game ISO through the LAUNCHER's mounts before doing its own IOP reset, so that handoff
  black-screens every setup whose neutrino/ folder or game lives on a BDM device.

  ps2sdk gained a NoReset entry point in 8890d8b5 (2026-06-30), but neither build container ships
  it yet (ps2dev:latest probed 2026-07-04 carries a 2026-06-21 SDK; the PS2MAXSDK pin is 2025-07-25),
  so we vendor the child loader instead (elfldr/loader.c, the NHDDL approach): copy it into
  BIOS-unused memory at 0x84000, ExecPS2 into it with argv[0] = target path, and it SifLoadElf()s
  the target through OPL's still-live mounts -- no IOP reset. Works identically on both SDKs.
*/

#include <kernel.h>
#include "include/ioman.h"      // LOG (kernel argv-budget refusal trace)
#include "include/launchdiag.h" // UDPBD hang-triage stage markers (keep-IOP handoffs only)
#include <sifrpc.h>
#define NEWLIB_PORT_AWARE
#include <fileXio_rpc.h> // fileXioOpen/fileXioDopen: the probe's second opinion (the child's own route)
#include <delaythread.h> // DelayThread: the probe's bounded settle retry
#include <string.h>
#include <fcntl.h>
#include <unistd.h>

extern unsigned char elfldr_elf[];
extern unsigned int size_elfldr_elf;

#define ELFLDR_ELF_MAGIC 0x464c457f
#define ELFLDR_PT_LOAD   1

typedef struct
{
    u8 ident[16];
    u16 type;
    u16 machine;
    u32 version;
    u32 entry;
    u32 phoff;
    u32 shoff;
    u32 flags;
    u16 ehsize;
    u16 phentsize;
    u16 phnum;
    u16 shentsize;
    u16 shnum;
    u16 shstrndx;
} elfldr_header_t;

typedef struct
{
    u32 type;
    u32 offset;
    void *vaddr;
    u32 paddr;
    u32 filesz;
    u32 memsz;
    u32 flags;
    u32 align;
} elfldr_pheader_t;

// Wipe the BIOS-unused region the child loader is linked into (0x84000 - 0x100000,
// below OPL itself -- see elfldr/linkfile).
static void wipeBramMem(void)
{
    int i;
    for (i = 0x00084000; i < 0x100000; i += 64) {
        __asm__ __volatile__(
            "\tsq $0, 0(%0) \n"
            "\tsq $0, 16(%0) \n"
            "\tsq $0, 32(%0) \n"
            "\tsq $0, 48(%0) \n" ::"r"(i));
    }
}

// The probe below asks one question -- can the child load this file through our live mounts? -- and
// the child reads it through fileXio (elfldr/loader.c loadElfViaFileXio). A failed open() used to end
// the handoff on the spot. UDPBD triage (FatBaldDad, #755): neutrino.elf on mmce0: opened fine before
// the teardown and failed this probe after it. So before refusing, try the child's own fileXio route,
// then give a device that is still settling a bounded ~3 s. A first open() that works costs nothing.
#define PROBE_RETRIES  12
#define PROBE_RETRY_US (250 * 1000)

// 1 = open() works, 2 = only fileXio opens it, 0 = neither.
static int probeTargetOnce(const char *filename)
{
    int fd = open(filename, O_RDONLY);
    if (fd >= 0) {
        close(fd);
        return 1;
    }
    fd = fileXioOpen(filename, 0x1, 0666); // 0x1 = FIO_O_RDONLY
    if (fd >= 0) {
        fileXioClose(fd);
        return 2;
    }
    return 0;
}

// For a refusal: does the device itself still answer? "mmce0:/NEUTRINO/neutrino.elf" -> "mmce0:/".
static int probeDeviceRootOpens(const char *filename)
{
    char root[32];
    const char *colon = strchr(filename, ':');
    int n, dfd;

    if (colon == NULL)
        return 0;
    n = (int)(colon - filename) + 1;
    if (n + 2 > (int)sizeof(root))
        return 0;
    memcpy(root, filename, n);
    root[n] = '/';
    root[n + 1] = '\0';
    dfd = fileXioDopen(root);
    if (dfd < 0)
        return 0;
    fileXioDclose(dfd);
    return 1;
}

// 0 = the child can load it, -1 = refuse. diag = paint the UDPBD triage markers.
static int probeTarget(const char *filename, int diag)
{
    int how, i, rootOk;

    how = probeTargetOnce(filename);
    if (how == 1)
        return 0;
    for (i = 0; how == 0 && i < PROBE_RETRIES; i++) {
        DelayThread(PROBE_RETRY_US);
        how = probeTargetOnce(filename);
    }
    if (how != 0) {
        LOG("[ELFLDR] %s opened only %s\n", filename, how == 2 ? "through fileXio" : "on a retry");
        if (diag)
            launchDiagHold(how == 2 ? 15 : 16, 2000);
        return 0;
    }
    rootOk = probeDeviceRootOpens(filename);
    LOG("[ELFLDR] %s will not open; its device root %s -- refusing handoff\n", filename, rootOk ? "opens" : "does not open");
    if (diag)
        launchDiagRefuse(rootOk ? LAUNCHDIAG_REFUSE_OPEN_ROOT_OK : LAUNCHDIAG_REFUSE_OPEN_ROOT_GONE);
    return -1;
}

static int sysLoadELFCommon(const char *filename, const char *partition, int argc, char *argv[], int resetIop, int cleanupHdd)
{
    elfldr_header_t *eh;
    elfldr_pheader_t *eph;
    void *pdata;
    int i;
    int diag = !resetIop && gLaunchDiag;
    const char *loaderArg = cleanupHdd ? (resetIop ? "-la=RH" : "-la=H") : (resetIop ? "-reset-iop" : NULL);
    int extra_args = loaderArg != NULL ? 1 : 0;

    // The child loads through filename's live mount. Any portable APA path is already present in
    // the caller-controlled target argv[0]; partition is retained for API compatibility.
    (void)partition;

    // argv here is the target's FULL argv -- argv[0] INCLUDED and caller-controlled (Neutrino:
    // its own path; POPSTARTER: the XX./SB. selector it string-parses; Apps: bootpath). At least argv[0] must
    // be supplied: the child forwards &argv[1] verbatim, never synthesizing a replacement.
    if (argc < 1 || argv == NULL || argv[0] == NULL)
        return -1;

    // Probe the target through our still-live mounts so a bad path fails fast in OPL
    // instead of inside the child loader (which can only fall through to OSDSYS).
    if (filename == NULL) {
        if (diag)
            launchDiagRefuse(LAUNCHDIAG_REFUSE_ARGS);
        return -1;
    }
    if (probeTarget(filename, diag) < 0)
        return -1;
    if (diag)
        launchDiagMark(10); // ELF probe open OK -- the elfldr child handoff runs next

    // Kernel args-area budget, the last line of defense for EVERY handoff (Neutrino,
    // POPSTARTER, Apps): SetArg copies at most 15 strings into ONE 256-byte pool (NULs included) and
    // ExecPS2 forwards the UNCLAMPED count -- exceeding either limit corrupts rather than
    // truncates. Callers are expected to fit (sysLaunchNeutrino budgets itself); refuse loudly
    // here rather than hand the kernel a mangled argv.
    {
        int pool = (int)strlen(filename) + 1;
        int j;
        if (loaderArg != NULL)
            pool += (int)strlen(loaderArg) + 1;
        for (j = 0; j < argc; j++) {
            if (argv[j] == NULL)
                return -1; // a NULL mid-argv would crash SetArg's copy inside ExecPS2 -- refuse here
            pool += (int)strlen(argv[j]) + 1;
        }
        if (argc + 1 + extra_args > 15 || pool > 256) {
            LOG("[ELFLDR] argv over the kernel budget (args=%d/15, pool=%d/256) -- refusing handoff\n", argc + 1 + extra_args, pool);
            if (diag)
                launchDiagRefuse(LAUNCHDIAG_REFUSE_CHILD_BUDGET);
            return -1;
        }
    }

    // Child contract: argv[0] = load path (SifLoadElf'd), argv[1..argc] = the target's full argv;
    // if resetIop is non-zero, trailing argv[argc+1] = "-reset-iop".
    // The ExecPS2 syscall marshals the strings across the jump.
    char *new_argv[argc + 1 + extra_args];
    new_argv[0] = (char *)filename;
    for (i = 0; i < argc; i++)
        new_argv[i + 1] = argv[i];
    if (loaderArg != NULL)
        new_argv[argc + 1] = (char *)loaderArg;

    wipeBramMem();

    eh = (elfldr_header_t *)elfldr_elf;
    if (_lw((u32)&eh->ident) != ELFLDR_ELF_MAGIC) {
        if (diag)
            launchDiagRefuse(LAUNCHDIAG_REFUSE_CHILD_MAGIC);
        return -1;
    }

    eph = (elfldr_pheader_t *)(elfldr_elf + eh->phoff);
    for (i = 0; i < eh->phnum; i++) {
        if (eph[i].type != ELFLDR_PT_LOAD)
            continue;

        pdata = (void *)(elfldr_elf + eph[i].offset);
        memcpy(eph[i].vaddr, pdata, eph[i].filesz);

        if (eph[i].memsz > eph[i].filesz)
            memset((void *)((u8 *)(eph[i].vaddr) + eph[i].filesz), 0, eph[i].memsz - eph[i].filesz);
    }

    sceSifExitRpc();
    FlushCache(0);
    FlushCache(2);

    if (diag)
        launchDiagMark(11); // ExecPS2 into the elfldr child is the next (and last) step on this side

    return ExecPS2((void *)eh->entry, NULL, argc + 1 + extra_args, new_argv);
}

int sysLoadELF(const char *filename, const char *partition, int argc, char *argv[], int resetIop)
{
    return sysLoadELFCommon(filename, partition, argc, argv, resetIop, 0);
}

int sysLoadELFApp(const char *filename, const char *partition, int argc, char *argv[], int resetIop, int cleanupHdd)
{
    return sysLoadELFCommon(filename, partition, argc, argv, resetIop, cleanupHdd);
}

int sysLoadELFKeepIOP(const char *filename, const char *partition, int argc, char *argv[])
{
    return sysLoadELF(filename, partition, argc, argv, 0);
}
