"""docs/VCD.md tells testers the exact size and SHA-256 of the equipped i.LINK usbhdfsd.irx (#1054).
The equip copies POPS/usbhdfsd.irx.ilink byte for byte, so the documented values must match it."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
doc = (ROOT / 'docs/VCD.md').read_text(encoding='utf-8')
data = (ROOT / 'POPS/usbhdfsd.irx.ilink').read_bytes()

match = re.search(r'\(([\d,]+) bytes; SHA-256 `([0-9A-Fa-f]{64})`\)', doc)
assert match, 'docs/VCD.md no longer documents the i.LINK usbhdfsd.irx size and hash'
assert int(match.group(1).replace(',', '')) == len(data), 'documented size differs from POPS/usbhdfsd.irx.ilink'
assert match.group(2).lower() == hashlib.sha256(data).hexdigest(), 'documented SHA-256 differs from POPS/usbhdfsd.irx.ilink'
print('docs/VCD.md i.LINK usbhdfsd.irx size and hash match the tracked file')
