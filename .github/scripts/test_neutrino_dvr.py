#!/usr/bin/env python3
"""Source integration guard for the experimental DESR DVR Neutrino branch."""
from pathlib import Path
root = Path(__file__).resolve().parents[2]
system = (root / "src/system.c").read_text()
hdd = (root / "src/hddsupport.c").read_text()
assert 'if (!strcmp(driver, "dvr"))' in system
assert 'return "dvr";' in system
assert '|| !strcmp(deviceName, "dvr")' in system
assert 'neutrinoArgHasActiveFlag(gNeutrinoArgs, "-qb")' in system
assert 'sysNeutrinoPreflight("dvr"' in hdd
assert 'sysLaunchNeutrino("dvr"' in hdd
assert 'hddDvrScan();' in hdd
assert 'dvrfile_fhi.irx' in system
assert 'SPD_CAPS_DVR' in hdd
assert 'sysLoadModuleBuffer(&dvrdrv_irx' in hdd
assert 'sysLoadModuleBuffer(&dvrfile_irx' in hdd
assert 'result == -2 || result == -3' in hdd
assert 'dir[strlen(dir) - 1]' in hdd
assert 'fileXioMount(roots[part], src, FIO_MT_RDONLY)' in hdd
assert 'hddPs2GameCount()' in hdd
assert 'hddDvrCleanUp();' in hdd
print("DESR DVR source integration checks passed (not a hardware/build test)")
