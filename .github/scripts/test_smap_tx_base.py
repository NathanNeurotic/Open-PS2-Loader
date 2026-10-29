#!/usr/bin/env python3
"""Every SMAP driver gives a TX descriptor the buffer address, not the FIFO offset (zokzot, xeRAbora OPL 205223e2).

SMAP_R_TXFIFO_WR_PTR is an offset into the 4 KiB TX buffer; a descriptor's pointer is the buffer's
address, SMAP_TX_BASE (0x1000) plus that offset. The in-game driver handed the chip the bare offset,
unlike the UDPBD and UDPFS drivers here and Neutrino's. Checks each driver that fills a TX descriptor.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = ['modules/network/smap-ingame/xfer.c', 'modules/network/smap_udpbd/src/xfer.c',
           'modules/network/udpfs_smap/src/xfer.c']


def main():
    failures = []
    checked = 0
    for rel in DRIVERS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        reads = re.findall(r'(\w+)\s*=\s*SMAP_REG16\(SMAP_R_TXFIFO_WR_PTR\)([^;]*);', text)
        if not reads:
            failures.append('%s reads no TX FIFO write pointer' % rel)
        for var, rest in reads:
            if 'SMAP_TX_BASE' not in rest:
                failures.append('%s: %s is the FIFO offset without SMAP_TX_BASE' % (rel, var))
            if not re.search(r'->pointer\s*=\s*%s\s*;' % re.escape(var), text):
                failures.append('%s: no descriptor takes %s' % (rel, var))
        checked += 1

    for line in failures:
        print('FAIL: ' + line)
    if failures:
        return 1
    print('SMAP TX descriptors: buffer address in %d drivers' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
