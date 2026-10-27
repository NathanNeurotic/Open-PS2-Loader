#!/usr/bin/env python3
"""Per-title compat defaults: evidence-backed entries, and per-core routing at every launch path."""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
src = {p: (root / p).read_text() for p in (
    'src/supportbase.c', 'src/bdmsupport.c', 'src/hddsupport.c', 'src/mmcesupport.c',
    'src/udpfssupport.c', 'src/guigame.c')}

table = src['src/supportbase.c']
table = table[table.index('sbTitleCompatDefaults[] = {'):]
table = table[:table.index('};')]
entries = {}
for sid, modes, cores in re.findall(r'\{"([A-Z]{4}_\d{3}\.\d{2})",\s*([^,]+),\s*(TITLE_CORE_\w+)\}', table):
    assert sid not in entries, f'duplicate startup ID {sid}'
    entries[sid] = (modes.strip(), cores)
assert len(entries) == table.count('{"'), 'every sbTitleCompatDefaults entry must name its cores'

# Shadow Hearts: Covenant (USA), both discs: Accurate Reads on both cores (PCSX2 #7139).
for disc in ('SLUS_210.41', 'SLUS_210.44'):
    assert entries.get(disc) == ('COMPAT_MODE_1', 'TITLE_CORE_ALL'), disc
# Klonoa 2 (USA): Synchronous reads on the OPL core only; it already runs smoothly on Neutrino.
assert entries.get('SLUS_201.51') == ('COMPAT_MODE_2', 'TITLE_CORE_OPL')

# A core-limited default must not apply on the other core.
assert '(sbTitleCompatDefaults[i].cores & core) ? sbTitleCompatDefaults[i].compatModes : 0' in src['src/supportbase.c']

# Every launch path asks for its own core's modes.
assert 'sbGetCompatModes(configSet, 0); // OPL core' in src['src/supportbase.c']
assert 'compatmask = sbGetCompatModes(configSet, 1);' in src['src/bdmsupport.c']
assert src['src/hddsupport.c'].count('sbGetCompatModes(configSet, 1)') == 2       # APA + DVR Neutrino legs
assert src['src/hddsupport.c'].count('sbGetCompatModes(configSet, 0)') == 1       # native HDD leg
assert 'compatmask = sbGetCompatModes(configSet, 1);' in src['src/mmcesupport.c']
assert 'compatmask = sbGetCompatModes(configSet, 1);' in src['src/udpfssupport.c']
for p, s in src.items():
    assert not re.search(r'sbGetCompatModes\(configSet\)|sbTitleCompatDefault\(configSet\)', s), p

# The MMCE switch to Neutrino happens after the OPL-core fallback, so that fallback keeps the OPL mask.
mmce = src['src/mmcesupport.c']
assert mmce.index('sbEnsureIgrUsbDrivers(compatmask);\n\n        // VMC -> neutrino') < mmce.index('compatmask = sbGetCompatModes(configSet, 1);')

# The settings screen saves only a change from the default it showed, so a core-limited default
# never turns into a saved value for both cores.
# Compared with the core whose defaults filled the checkboxes: the Loader row can change after loading (#1072).
assert 'if (compatMode == sbTitleCompatDefault(configSet, compatShownNeutrino))' in src['src/guigame.c']
assert 'compatShownNeutrino = guiGameDialogCoreIsNeutrino(support, neverNeutrino);' in src['src/guigame.c']

# The screen resolves a source that boots one core only before the Loader row: UDPFS and UDPBD are always
# Neutrino, so a core-limited default shown there matches the launch.
gui = src['src/guigame.c']
helper = gui[gui.index('static int guiGameDialogCoreIsNeutrino('):]
helper = helper[:helper.index('\n}\n')]
assert 'support->mode == UDPFS_MODE || bdmSupportIsUDPBD(support)' in helper

print('PASS: title compat defaults are evidence-backed and routed per core')
