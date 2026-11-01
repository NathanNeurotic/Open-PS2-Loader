"""Menu crash catcher (diagnostic builds only; from YAOPL, Roman Kelesidis: yaopl/yaopl ebffcf6, c1fdeb0).

An EE exception in the menu used to park the CPU with no word on screen. In __OPLDIAG builds the
menu watchdog now installs libeedebug level 1 handlers that send the crashed thread into a report
written to RIPTOPL-CRASH.TXT, plus a VBlank PC sampler both reports list. Structural checks: the
handler stays free of kernel calls, the report runs on its own stack, the watchdog stands down after
a crash, it is all compiled only into diagnostic builds, and those builds link libeedebug.
"""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
CPP = (root / "src/ui/menuwatch.cpp").exists()
src = (root / ("src/ui/menuwatch.cpp" if CPP else "src/menuwatch.c")).read_text(encoding="utf-8")


def function(source, signature):
    start = source.index(signature)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(signature)


# Diagnostic builds only: everything sits inside the file's __OPLDIAG block.
guard = src.index("#ifdef __OPLDIAG")
assert guard < src.index("static int crashException(") < src.rindex("#endif"), "crash catcher outside __OPLDIAG"
assert "#include <ee_debug.h>" in src[guard:], "ee_debug.h included only in the __OPLDIAG part"

# Started with the watchdog, from the GUI thread.
start = function(src, "void menuWatchStart(")
assert start.index("guiThreadId = GetThreadId();") < start.index("crashCatcherStart();")

catcher = function(src, "static void crashCatcherStart(")
assert "ee_dbg_install(1)" in catcher and "ee_dbg_set_level1_handler(codes[i], &crashException)" in catcher
codes = re.search(r"codes\[\] = \{([^}]*)\}", catcher).group(1)
assert [int(c) for c in codes.split(",")] == [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13], codes
assert "AddIntcHandler(INTC_VBLANK_S, &epcSampler, 0)" in catcher

# The exception handler runs in exception context: copy and redirect, nothing else.
handler = function(src, "static int crashException(")
for call in ("SleepThread", "diagLog", "printf", "screen(", "writeReport", "ReferThreadStatus", "DelayThread"):
    assert call not in handler, call + " called in exception context"
assert "crashReport" in handler and "crashPark" in handler, "first exception reports, a second one parks"
assert "crashStack + CRASH_STACK_SIZE" in handler, "the report runs on a stack of its own"
assert "crashCount++ == 0" in handler
assert "parkStack + sizeof(parkStack)" in handler, "a second exception parks on its own stack, not on the report's"

sampler = function(src, "static int epcSampler(")
assert "mfc0 %0, $14" in sampler and "ExitHandler();" in sampler

report = function(src, "static void crashReport(")
assert 'writeReport("mc0:/RIPTOPL-CRASH.TXT", len) || writeReport("mc1:/RIPTOPL-CRASH.TXT", len)' in report
assert "exceptionName(code)" in report and "addEpcSamples(len)" in report and "crashPark();" in report
assert "crashRegs.sp >= 0x00100000" in report, "only a sane stack pointer is walked"

# Torn down before the handoff: the next program inherits no VBlank handler and no exception hooks.
stop = function(src, "void menuWatchStop(")
assert "RemoveIntcHandler(INTC_VBLANK_S, epcHandlerId)" in stop and "ee_dbg_remove(1)" in stop
opl = (root / ("src/app/opl.cpp" if CPP else "src/opl.c")).read_text(encoding="utf-8")
for sig in ("void deinitEx(", "void deinit("):
    assert "menuWatchStop();" in function(opl, sig), sig + " tears the crash catcher down"
header = (root / "include/menuwatch.h").read_text(encoding="utf-8")
assert header.count("menuWatchStop(void)") == 2, "declared, and a no-op outside diagnostic builds"

# The freeze report lists the sampled PCs too, and the watchdog stands down after a crash.
assert "addEpcSamples(len)" in function(src, "static int buildReport(")
assert "if (crashCount)" in function(src, "static void watchThread(")

if CPP:
    import sys
    sys.path.insert(0, str(root / "tools"))
    import build_edition as editions

    def main_target(configuration):
        targets = {t["name"]: t for t in editions.definition("korium", configuration)["targets"]}
        return targets["riptopl"]

    # Every configuration: libeedebug is linked exactly when __OPLDIAG compiles the catcher in.
    for configuration in editions.CONFIGURATIONS:
        main = main_target(configuration)
        diag = "__OPLDIAG" in main.get("defines", [])
        assert ("eedebug" in main["libs"]) == diag, configuration + ": libeedebug iff __OPLDIAG"
    assert "eedebug" not in main_target("standard")["libs"], "release builds stay without it"
else:
    make = (root / "Makefile").read_text(encoding="utf-8")
    block = make[make.index("ifeq ($(OPLDIAG),1)"):]
    block = block[:block.index("endif")]
    assert "-leedebug" in block, "OPLDIAG builds link libeedebug"

print("PASS: the menu crash catcher is diagnostic-only, handler-safe, and linked with libeedebug")
