#!/usr/bin/env python3
"""The ART directory index never answers for network shares (SMB, UDPFS): it must always go and look (#1070)."""
import re
from pathlib import Path

src = (Path(__file__).resolve().parents[2] / 'src/artindex.c').read_text()
body = src[src.index('int artIndexMayExist(const char *fullPath)'):]
body = body[:body.index('\n}\n')]
guard = re.search(r'if \(([^\n]*!strncmp\(fullPath, "smb", 3\)[^\n]*)\)\n\s*return 1;', body)
assert guard, 'network-share guard missing'
assert '!strncmp(fullPath, "udpfs", 5)' in guard.group(1), 'UDPFS art must bypass the directory index'
# The guard must run before any slot is built (opendir/readdir on the share).
assert body.index(guard.group(0)) < body.index('artIndexSlotFor('), 'guard must precede the directory sweep'
print('PASS: SMB and UDPFS art bypass the directory index')
