#!/usr/bin/env python3
"""Host-side invariants for the opt-in DESR DVR source.

Does not claim PSX DESR hardware validation, driver binary buildability, or
successful boot from any specific DVRP firmware.
"""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
read = lambda name: (root / name).read_text(encoding="utf-8")

make = read("Makefile")
modes = read("include/iosupport.h")
opl = read("src/opl.c")
dvr = read("src/dvrsupport.c")
gui = read("src/gui.c")
game = read("src/guigame.c")
system = read("src/system.c")
docs = read("docs/NEUTRINO.md")

assert "DVRP ?= 0" in make
assert "ifeq ($(DVRP),1)" in make
assert "FRONTEND_OBJS += dvrsupport.o" in make
assert "dvrdrv.irx" in make and "dvrfile.irx" in make
assert re.search(r"HTTP_MODE,[^\n]*\n#ifdef DVRP[\s\S]{0,150}DVR_MODE,", modes)

assert 'open("rom0:PSXVER", O_RDONLY)' in dvr
assert 'fileXioDopen("dvr_hdd0:")' in dvr
assert 'FIO_MT_RDONLY' in dvr
assert 'snprintf(partition, sizeof(partition), "dvr_hdd0:%s", gDVRPartition)' in dvr
assert 'dvrScanDirectory("dvr_pfs0:/"' in dvr
assert 'dvrScanDirectory("dvr_pfs0:/DVD/"' in dvr
assert 'dvrScanDirectory("dvr_pfs0:/CD/"' in dvr
assert 'dvrValidPartition(gDVRPartition)' in dvr
assert '"config/bsd-dvr.toml"' in dvr
assert '"modules/dvrfile_fhi.irx"' in dvr
assert 'sysNeutrinoArgsPreflight("dvr", image' in dvr
assert 'sysLaunchNeutrino("dvr", image' in dvr
assert "hddInspectSupportHome();" not in dvr
assert "hddLoadModulesReady()" not in dvr
assert "sysInitDev9()" in dvr and "sysShutdownDev9()" in dvr
assert "dvrKeepMountOnHandoff = 1" in dvr
assert "dvrPfsOwned && !dvrKeepMountOnHandoff" in dvr
assert "dvrMountedPartition, gDVRPartition" in dvr
assert "if (id >= dvrGameCount || !dvrGames)" in dvr
assert 'if (!strncasecmp(dvrConfigPrefix, "dvr_pfs", 7)' in dvr
assert "fileXioFormat(" not in dvr
assert "O_CREAT" not in dvr
assert "fileXioWrite(" not in dvr
assert "flash" not in dvr.lower().replace("firmware", "")
assert 'gDVRStartMode = START_MODE_DISABLED' in opl
assert 'strcpy(gDVRPartition, "__xcontents")' in opl
assert 'dvrIsAvailable() ? gDVRStartMode : START_MODE_DISABLED' in opl
assert 'CFG_DVRMODE' in gui
assert 'CFG_DVRPARTITION' in gui
assert 'coreForcedDvr' in game
assert 'sourceMode == DVR_MODE' in game
assert 'if (!strcmp(driver, "dvr"))' in system
assert 'neutrinoArgHasActiveFlag(gNeutrinoArgs, "-qb")' in system
assert 'neutrinoArgHasActiveFlag(extraArgs, "-bsd=")' in system
assert 'neutrinoArgHasActiveFlag(extraArgs, "-dvd=")' in system
assert 'neutrinoArgHasActiveFlag(extraArgs, "-logo")' in system
assert "not hardware-validated" in docs
print("PASS: experimental DESR DVR source contract (source inspection only)")
