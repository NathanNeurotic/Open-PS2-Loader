#!/usr/bin/env python3
"""Shadow Hearts: Covenant (USA) defaults to Accurate Reads on both discs (PCSX2 #7139)."""
import re
from pathlib import Path

src = Path(__file__).resolve().parents[2].joinpath('src/supportbase.c').read_text()
table = src[src.index('sbTitleCompatDefaults[] = {'):]
table = table[:table.index('};')]
entries = dict(re.findall(r'\{"([A-Z]{4}_\d{3}\.\d{2})",\s*([^}]+)\}', table))
for disc in ('SLUS_210.41', 'SLUS_210.44'):
    assert entries.get(disc, '').strip() == 'COMPAT_MODE_1', f'{disc} must default to COMPAT_MODE_1, got {entries.get(disc)!r}'
assert len(entries) == table.count('{"'), 'duplicate startup ID in sbTitleCompatDefaults'
print('PASS: Shadow Hearts: Covenant (USA) discs default to Accurate Reads')
