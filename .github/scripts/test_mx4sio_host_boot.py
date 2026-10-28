"""MX4SIO enabled hung the boot screen under PCSX2 (ported from RiptOPL #95).

mx4sio_bd's start-up probe spins on an SIO2 status bit PCSX2 never sets for a receive-only
transfer, so the module load never returned (emulog ends at "[MX4SIO_BD]:"). A host: boot is
PCSX2 (or ps2client), so the menu does not load MX4SIO there. Every load site carries the gate;
the queue gate's behaviour is tested in test_io_queue_trims.py.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
support = (ROOT / 'src/bdmsupport.c').read_text()

assert support.count('&mx4sio_bd_irx') == 2, 'a new MX4SIO load site needs the host: gate'
assert (
    'if (gEnableMX4SIO && !mx4sioModLoaded && !oplBootDirIsHostFs()) {\n'
    '        // Load MX4SIO Block Device drivers\n'
    '        if (bdmDiagLoadOptionalModule("MX4SIO", "MX4SIO_BD", &mx4sio_bd_irx, size_mx4sio_bd_irx) >= 0)' in support
), 'the MX4SIO load must stay inside the host: gate'
assert 'if (gEnableMX4SIO && !mx4sioModLoaded && !oplBootDirIsHostFs())\n        return 1;' in support
assert 'if (!mx4sioModLoaded && !oplBootDirIsHostFs() && bdmLoadOptionalModule("MX4SIO_BD"' in support
print('PASS: no MX4SIO load on a host: boot')
