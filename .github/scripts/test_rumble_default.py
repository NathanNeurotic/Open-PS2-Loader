#!/usr/bin/env python3
"""Menu rumble is off on a fresh configuration (#1070); a saved enable_rumble still overrides it."""
import re
from pathlib import Path

opl = (Path(__file__).resolve().parents[2] / 'src/opl.c').read_text()
defaults = re.findall(r'^\s*gEnableRumble = (\d+);', opl, re.M)
assert defaults == ['0'], f'fresh-config rumble default must be 0, got {defaults}'
assert 'configGetInt(configOPL, CONFIG_OPL_RUMBLE, &gEnableRumble);' in opl, 'saved setting must still load'
print('PASS: menu rumble defaults to off and still honours a saved setting')
