"""Exercise the production EE/IOP launch binding across local transports.

The shared BDM matcher must accept iLink's sd/ilink aliases without widening
USB, MX4SIO, CF or ATA matches. ATA's synthetic in-game device has its own rule.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ee = (ROOT / 'src/bdmsupport.c').read_text()
iop = (ROOT / 'modules/iopcore/cdvdman/device-bdm.c').read_text()


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2]


production = function(ee, 'static void bdmSetLaunchDeviceBinding(')
production += '\n#ifdef USE_BDM_ATA\n' + function(iop, 'static int bdm_is_ata_driver_name(') + '\n#endif\n'
production += function(iop, 'static int bdm_is_ilink_driver_name(')
production += function(iop, 'static int bdm_matches_launch_device(')
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct block_device { const char *name; unsigned int devNr; };
struct cdvdman_settings_bdm { unsigned int bdDeviceId; char bdDeviceDriver[16]; };
static struct cdvdman_settings_bdm cdvdman_settings;
@PRODUCTION@
int main(void) {
    const char *names[] = {"usb", "sd", "ilink", "sdc", "mx4sio", "ata", "cf"};
    for (unsigned int i = 0; i < sizeof(names)/sizeof(names[0]); i++) {
        bdmSetLaunchDeviceBinding(&cdvdman_settings, names[i], 2);
        for (unsigned int j = 0; j < sizeof(names)/sizeof(names[0]); j++) {
            struct block_device device = {names[j], 2};
            int aliases = (!strcmp(names[i], "sd") && !strcmp(names[j], "ilink")) ||
                          (!strcmp(names[i], "ilink") && !strcmp(names[j], "sd"));
            assert(bdm_matches_launch_device(&device) == (i == j || aliases));
            device.devNr = 3;
#ifdef USE_BDM_ATA
            int synthetic = !strcmp(names[i], "ata") && !strcmp(names[j], "ata");
#else
            int synthetic = 0;
#endif
            assert(bdm_matches_launch_device(&device) == synthetic);
        }
    }
    struct block_device ata = {"ata", 0}, usb = {"usb", 0};
    bdmSetLaunchDeviceBinding(&cdvdman_settings, "ata", -1);
#ifdef USE_BDM_ATA
    assert(bdm_matches_launch_device(&ata)); // ATA ignores the menu's missing index
#else
    assert(!bdm_matches_launch_device(&ata));
#endif
    assert(!bdm_matches_launch_device(&usb));
    assert(!bdm_matches_launch_device(NULL));
    ata.name = NULL;
    assert(!bdm_matches_launch_device(&ata));
    bdmSetLaunchDeviceBinding(&cdvdman_settings, NULL, 0);
    assert(bdm_matches_launch_device(&usb)); // legacy index-only binding
    usb.devNr = 1;
    assert(!bdm_matches_launch_device(&usb));
    puts("PASS: local transport isolation, iLink aliases, device indices and legacy binding");
    return 0;
}
'''.replace('@PRODUCTION@', production)
with tempfile.TemporaryDirectory() as directory:
    source, binary = Path(directory) / 'binding.c', Path(directory) / 'binding'
    source.write_text(program)
    for flags in ([], ['-DUSE_BDM_ATA']):
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', *flags,
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=5)
