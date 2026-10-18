#!/usr/bin/env python3
"""In-game freeze report (INGAMEDIAG / FREEZEDIAG flavour) structural checks.

The report must not exist in any other build, must not be able to hang IGR on a stuck IOP, and
must capture the game's threads before IGR changes them. The text formatter itself is covered by
ee_core/tests/test_freeze_diag_format.c.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAILURES = []


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def check(cond, what):
    if not cond:
        FAILURES.append(what)


TOKEN = re.compile(r"freeze_diag|FreezeDiag|FREEZE_DIAG|CDSC_GET_FREEZE_DIAG")


def positive_diag_guard(line):
    return re.fullmatch(r"#ifdef\s+INGAMEDIAG|#(?:if|elif)\s+defined\s*(?:\(\s*INGAMEDIAG\s*\)|INGAMEDIAG)", line) is not None


assert positive_diag_guard("#ifdef INGAMEDIAG")
assert positive_diag_guard("#elif defined(INGAMEDIAG)")
assert not positive_diag_guard("#ifndef INGAMEDIAG")
assert not positive_diag_guard("#if !defined(INGAMEDIAG)")
assert not positive_diag_guard("#if defined(INGAMEDIAG) || OTHER")


def unguarded_lines(rel):
    """Lines that mention the report outside any #if/#ifdef naming INGAMEDIAG."""
    stack = []
    bad = []
    for number, line in enumerate(read(rel).split("\n"), 1):
        s = line.strip()
        if s.startswith("#if"):
            stack.append(positive_diag_guard(s))
            continue
        if s.startswith("#elif"):
            if stack:
                stack[-1] = positive_diag_guard(s)
            continue
        if s.startswith("#else"):
            if stack:
                stack[-1] = False
            continue
        if s.startswith("#endif"):
            if stack:
                stack.pop()
            continue
        if TOKEN.search(line) and not any(stack):
            bad.append(f"{rel}:{number}: {s}")
    return bad


# 1. Nothing of the report outside INGAMEDIAG in the shared sources.
for rel in [
    "ee_core/src/padhook.c",
    "ee_core/src/iopmgr.c",
    "modules/iopcore/cdvdman/cdvdman.c",
    "modules/iopcore/cdvdman/internal.h",
    "modules/iopcore/cdvdman/device-bdm.c",
    "modules/iopcore/cdvdman/device-mmce.c",
    "modules/iopcore/cdvdfsv/cdvdfsv.c",
]:
    for line in unguarded_lines(rel):
        FAILURES.append("report code outside #ifdef INGAMEDIAG: " + line)

ee_make = read("ee_core/Makefile")
check(re.search(r"ifeq \(\$\(INGAMEDIAG\),1\)\nEE_OBJS \+= freeze_diag\.o\n", ee_make) is not None,
      "ee_core builds freeze_diag.o only under INGAMEDIAG (formatting and file I/O live in freezediag.irx)")
for rel in ["modules/iopcore/cdvdman/Makefile", "modules/iopcore/cdvdfsv/Makefile"]:
    check(re.search(r"ifeq \(\$\(INGAMEDIAG\),1\)\nIOP_CFLAGS \+= -DINGAMEDIAG\n", read(rel)) is not None,
          f"{rel} defines INGAMEDIAG only when asked")

top = read("Makefile")
check("INGAMEDIAG ?= 0" in top, "INGAMEDIAG defaults off")
check(re.search(r"ifeq \(\$\(INGAMEDIAG\),1\)\n  ifeq \(\$\(RETROACHIEVEMENTS\),1\)\n    \$\(error", top) is not None,
      "INGAMEDIAG refuses to combine with RETROACHIEVEMENTS (RA runs IGR from VBLANK)")
cdvdman_rules = re.findall(r"\t\$\(MAKE\) \$\(CDVDMAN_PS2LOGO_FLAGS\)[^\n]*USE_[A-Z_]+=1 -C \$< all", top)
check(len(cdvdman_rules) == 8, f"eight CDVDMAN variant rules found (got {len(cdvdman_rules)})")
check(all("$(CDVDMAN_DIAG_FLAGS)" in r for r in cdvdman_rules), "every CDVDMAN variant receives the diag flag")
check("\t$(MAKE) $(CDVDMAN_DIAG_FLAGS) -C $<" in top, "CDVDFSV receives the diag flag")
check("EECORE_EXTRA_FLAGS += INGAMEDIAG=1" in top, "ee_core gets the flag")
check("IOP_OBJS += freezediag.o" in top, "the menu embeds freezediag.irx only in the flavour")
check("\t$(MAKE) FREEZEDIAG_BUILD=$(OPL_VERSION) -C $<" in top, "the report names the build it came from")

# 2. IGR ordering in padhook.c.
pad = read("ee_core/src/padhook.c")
poll = pad[pad.index("static void IGR_PollUntilRequested(void)"):]
poll = poll[:poll.index("\n}\n")]
i_prio = poll.index("ChangeThreadPriority(TH_SELF, 0);")
i_begin = poll.index("FreezeDiag_Begin(")
i_stop = poll.index("IGR_StopDmaAndGs();")
i_suspend = poll.index("SuspendThread(i);")
check(i_prio < i_begin < i_stop < i_suspend,
      "threads are captured at priority 0 and before DMA/GS stop and thread suspension")
check("if (Pad_Data.combo_type == IGR_COMBO_START_SELECT) {" in poll[i_prio:i_begin],
      "only the reset combo arms a report (not IGS or power-off)")
alarm = pad[pad.index("static void IGR_Poll_Alarm("):pad.index("static void IGR_PollUntilRequested(void)")]
check("g_freeze_diag_polls++;" in alarm[:alarm.index("IGR_CheckInputs();")], "each alarm input sample is counted")

thread = pad[pad.index("static void IGR_Thread(void *arg)"):]
gate = re.search(r"#ifdef INGAMEDIAG\n(?:\s*//[^\n]*\n)*\s*FreezeDiag_FetchAndShutdown\(\);\n#else\n#ifdef RETROACHIEVEMENTS\n(?:\s*//[^\n]*\n)*\s*if \(config->GameMode != DISC_MODE\)\n#endif\n\s*oplIGRShutdown\(0\);\n#endif\n", thread)
check(gate is not None, "the flavour replaces the blocking shutdown RPC; other builds keep theirs unchanged")
i_lmb = thread.index("sbv_patch_enable_lmb();")
i_write = thread.index("FreezeDiag_Write();")
i_spu = thread.index("LoadOPLModule(OPL_MODULE_ID_RESETSPU")
check(i_lmb < i_write < i_spu, "the report is written after the IGR IOP reboot, before RESETSPU")

# 3. freeze_diag.c: bounded waits, non-blocking bind, the reboot after writing.
core = read("ee_core/src/freeze_diag.c")
check("SifBindRpc(&igr_cd, IGR_RPC_SERVER, SIF_RPC_M_NOWAIT)" in core, "the bind does not block on a stuck IOP")
check(re.search(r"SifCallRpc\([^;]*SIF_RPC_M_NOWAIT", core) is not None, "the call does not block on a stuck IOP")
for match in re.finditer(r"while \(SifCheckStatRpc\(&(?:igr_cd|shutdown_cd)\)\) \{(.*?)\n    \}", core, re.S):
    check("budget_spent(start)" in match.group(1), "every RPC wait has a deadline")
check(len(re.findall(r"while \(SifCheckStatRpc", core)) == 3, "three RPC waits (bind, record, shutdown), all bounded")
fas = core[core.index("void FreezeDiag_FetchAndShutdown(void)"):]
fas = fas[:fas.index("\n}\n")]
check(re.search(r"if \(!report_armed\) \{\n\s*oplIGRShutdown\(0\);\n\s*return;", fas) is not None,
      "without a report to take (IGS, power-off) the shutdown is exactly oplIGRShutdown(0)")
check(fas.index("fetch_iop()") < fas.index("shutdown_with_deadline()"), "the record is fetched before the shutdown changes the IOP")
check("FREEZE_DIAG_SHUTDOWN_SKIPPED" in fas, "bind failure skips shutdown")
sd = core[core.index("static void shutdown_with_deadline(void)"):]
sd = sd[:sd.index("\n}\n")]
check(re.search(r"SifCallRpc\(&shutdown_cd, 1, SIF_RPC_M_NOWAIT", sd) is not None, "the shutdown is RPC function 1, sent without blocking")
check("= 0; // 0 = shut down, do not power off" in sd, "the shutdown asks for the same thing as oplIGRShutdown(0)")
check(core.count("budget_spent(start)") >= 3, "the bind retry loop also has a deadline")
w = core[core.index("void FreezeDiag_Write(void)"):]
check(w.index("LoadModule(\"rom0:MCMAN\"") < w.index("FlushCache(0)") < w.index("CopyToIop(") < w.index("LoadOPLModule(OPL_MODULE_ID_FREEZEDIAG") < w.index("Reset_Iop(\"\", 0)"),
      "ROM MCMAN, cache flushed before the DMA, record handed to freezediag.irx, then a clean IOP reboot")
check("fio" not in core and "freeze_diag_format(" not in core, "ee_core carries no file client or formatter (stack budget)")
irx = read("modules/iopcore/freezediag/freezediag.c")
for path in re.findall(r'"(mc[01]:/[^"]+)"', irx):
    name = path.split(":/", 1)[1]
    check("/" not in name and len(name) <= 31, f"report path {path} fits a memory card name")
check("O_WRONLY | O_CREAT | O_TRUNC" in irx, "IOP ioman flags")
check("freeze_diag_format(" in irx, "the IRX uses the host-tested formatter")
fmt = read("ee_core/src/freeze_diag_format.c")
check("long long" not in fmt, "the formatter needs no 64-bit division (IOP has none)")
mods = read("ee_core/include/modules.h")
check(re.search(r"#ifdef INGAMEDIAG\n(?:\s*//[^\n]*\n)*\s*OPL_MODULE_ID_FREEZEDIAG,\n#endif\n\n\s*OPL_MODULE_ID_PCCF = 60,\n\s*OPL_MODULE_ID_COUNT", mods) is not None,
      "the diagnostic ID remains guarded and existing IDs are preserved before CF")
sysc = read("src/system.c")
check(re.search(r"#ifdef INGAMEDIAG\n(?:\s*//[^\n]*\n)*\s*irxptr_tab\[modcount\]\.info = size_freezediag_irx", sysc) is not None,
      "the menu registers freezediag.irx only in the flavour")

# 4. Shared constants.
opl_h = read("modules/iopcore/common/cdvdman_opl.h")
codes = re.findall(r"#define (CDSC_\w+)\s+(0x[0-9A-Fa-f]+)", opl_h)
values = [int(v, 16) for _, v in codes]
check(len(values) == len(set(values)), "CDSC codes are unique")
check(("CDSC_GET_FREEZE_DIAG", "0xFFFFFFEF") in codes, "freeze report CDSC code defined")
shared = read("modules/iopcore/common/freeze_diag.h")
check(re.search(r"#define FREEZE_DIAG_RPC_FNO\s+2\b", shared) is not None, "RPC function 2 (1 is shutdown)")

# 5. The flavour exists and is built with the flag.
flav = read(".github/workflows/flavours.yml")
check(re.search(r"- flavour: OFFICIALROLLING-FREEZEDIAG\n\s+image: ghcr\.io/ps2homebrew/ps2homebrew:main\n(?:\s+\w+: [^\n]*\n)*?\s+ingamediag: \"1\"", flav) is not None,
      "OFFICIALROLLING-FREEZEDIAG flavour on the toolchain testers run")
check("INGAMEDIAG=${{ matrix.ingamediag || '0' }}" in flav, "the build step passes INGAMEDIAG")

if FAILURES:
    for f in FAILURES:
        print("FAIL:", f)
    sys.exit(1)
print("test_ingame_freeze_diag: all checks passed")
