"""Only actual VMC, PADEMU or MX4SIO consumers need the SDK SIO2MAN.

The VMC flag used to be set even for a zero-sized MCEMU image (both slots disabled).
After #962 made it select SIO2MAN too, default HDD/USB/SMB launches preloaded an
unneeded SDK driver instead of leaving the game to load its own, as in OPL 2049.
MMCE always retains its game-owned SIO2MAN, including with active VMC/PADEMU.

Compile the production launch selection and packing conditions, with and without
PADEMU. An optional git ref supplies the source for before/after reproduction.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
system = (subprocess.check_output(['git', 'show', sys.argv[1] + ':src/system.c'], cwd=root, text=True)
          if len(sys.argv) > 1 else (root / 'src/system.c').read_text(encoding='utf-8')).replace('\r\n', '\n')
failures = []

body_at = system.find('static unsigned int sendIrxKernelRAM(')
pack_at = system.find('SET_OPL_MOD_ID(OPL_MODULE_ID_SIO2MAN)', body_at)
cond_at = system.rfind('\n    if (', body_at, pack_at)
if body_at < 0 or pack_at < 0 or cond_at < 0:
    print('src/system.c: SIO2MAN packing in sendIrxKernelRAM not found')
    sys.exit(1)
line = system[cond_at:system.index('\n', cond_at + 1)].strip()
match = re.fullmatch(r'if \((.*)\) \{', line)
if match is None:
    print('src/system.c: unexpected SIO2MAN packing condition: %s' % line)
    sys.exit(1)
condition = match.group(1)
launch_at = system.index('void sysLaunchLoaderElf(')
disc_selection = re.search(r'#ifdef RETROACHIEVEMENTS\n    const int discMode = .*?\n#endif', system[launch_at:], re.S)
if disc_selection is None:
    sys.exit('src/system.c: DISC launch selection not found')
launch_flag = re.search(r'    if \([^\n]+\)\n        modules \|= CORE_IRX_VMC;', system[launch_at:])
if launch_flag is None:
    sys.exit('src/system.c: native VMC selection not found')

defines = ''.join('#define %s %s\n' % m for m in re.findall(r'#define (CORE_IRX_\w+)\s+(0x[0-9A-Fa-f]+)', system))
for name in ('CORE_IRX_MMCE', 'CORE_IRX_VMC', 'CORE_IRX_MX4SIO', 'CORE_IRX_USB', 'CORE_IRX_HDD'):
    if name not in defines:
        failures.append('src/system.c: %s is not defined' % name)

PROGRAM = r'''
#include <stdio.h>
#include <string.h>
@DEFINES@
static int gEnablePadEmu;
#ifdef PADEMU
#define PADEMU_ARG || gEnablePadEmu
#else
#define PADEMU_ARG
#endif
static int packs(unsigned int modules, int padEmu)
{
    gEnablePadEmu = padEmu;
    return (@COND@) ? 1 : 0;
}
static unsigned int launch_modules(const char *mode_str, unsigned int transport, int size_mcemu_irx)
{
    unsigned int modules = transport;
@DISC_SELECTION@
    (void)size_mcemu_irx;
@LAUNCH_FLAG@
    return modules;
}
static int fails;
#define CHECK(c, m) do { if (!(c)) { printf("FAIL %s\n", m); fails++; } } while (0)
int main(void)
{
    struct {const char *mode; unsigned int transport;} modes[] = {
        {"HDD_MODE", CORE_IRX_HDD}, {"BDM_USB_MODE", CORE_IRX_USB},
        {"ETH_MODE", CORE_IRX_ETH | CORE_IRX_SMB}, {"HTTP_MODE", CORE_IRX_ETH},
        {"BDM_ILK_MODE", CORE_IRX_ILINK}, {"BDM_M4S_MODE", CORE_IRX_MX4SIO},
        {"MMCE_MODE", CORE_IRX_MMCE}, {"BDM_CF_MODE", CORE_IRX_PCCF},
        {"BDM_ATA_MODE", CORE_IRX_HDD},
#ifdef RETROACHIEVEMENTS
        {"DISC_MODE", 0}
#endif
    };
    for (unsigned int i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
        unsigned int idle = launch_modules(modes[i].mode, modes[i].transport, 0);
        unsigned int active = launch_modules(modes[i].mode, modes[i].transport, 4096);
        int supportsVmc = strcmp(modes[i].mode, "DISC_MODE") && strcmp(modes[i].mode, "BDM_CF_MODE");
        int isMx4sio = modes[i].transport == CORE_IRX_MX4SIO;
        int isMmce = modes[i].transport == CORE_IRX_MMCE;
        CHECK(!(idle & CORE_IRX_VMC), modes[i].mode);
        CHECK(!!(active & CORE_IRX_VMC) == !!supportsVmc, "only an active supported VMC selects MCEMU");
        CHECK(packs(idle, 0) == isMx4sio, "idle launch leaves SIO2MAN to the game except on MX4SIO");
        CHECK(packs(active, 0) == (!isMmce && (supportsVmc || isMx4sio)), "active VMC retains its SIO2MAN dependency");
        CHECK(!(launch_modules(modes[i].mode, modes[i].transport, -1) & CORE_IRX_VMC), "invalid MCEMU size selects no VMC");
#ifdef PADEMU
        CHECK(packs(idle, 1) == !isMmce, "PADEMU still selects SIO2MAN independently of VMC");
#endif
    }
    CHECK(!packs(CORE_IRX_MMCE | CORE_IRX_VMC, 0), "MMCE game with VMC gets no SDK SIO2MAN");
    CHECK(!packs(CORE_IRX_MMCE | CORE_IRX_VMC, 1), "MMCE game with PADEMU gets no SDK SIO2MAN");
    CHECK(packs(CORE_IRX_USB | CORE_IRX_VMC, 0), "USB game keeps the SDK SIO2MAN (#962)");
    CHECK(packs(CORE_IRX_HDD | CORE_IRX_VMC, 0), "HDD game keeps the SDK SIO2MAN (#962)");
    CHECK(packs(CORE_IRX_MX4SIO | CORE_IRX_VMC, 0), "MX4SIO game keeps the SIO2MAN it requires");
    CHECK(packs(CORE_IRX_MX4SIO, 0), "MX4SIO without VMC still gets SIO2MAN");
    CHECK(!packs(0, 0), "a disc launch without VMC, MX4SIO or PADEMU gets none");
#ifdef PADEMU
    CHECK(packs(CORE_IRX_HDD, 1), "PADEMU alone still packs SIO2MAN off MMCE");
#endif
    return fails ? 1 : 0;
}
'''

if not failures:
    for flavour, extra in (('standard', ''), ('pademu', '#define PADEMU\n'),
                           ('ra-pademu', '#define RETROACHIEVEMENTS\n#define PADEMU\n')):
        program = extra + PROGRAM.replace('@DEFINES@', defines).replace('@COND@', condition).replace('@LAUNCH_FLAG@', launch_flag.group(0)).replace('@DISC_SELECTION@', disc_selection.group(0))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'pack.c'
            exe = Path(tmp) / ('pack.exe' if sys.platform == 'win32' else 'pack')
            src.write_text(program, encoding='utf-8')
            try:
                build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                                       capture_output=True, text=True, check=False, timeout=120)
            except subprocess.TimeoutExpired:
                failures.append('%s harness: gcc did not finish within 120 s' % flavour)
                continue
            if build.returncode != 0:
                failures.append('%s harness did not compile:\n%s' % (flavour, build.stderr))
                continue
            try:
                run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=10)
            except subprocess.TimeoutExpired:
                failures.append('%s harness: did not finish within 10 s' % flavour)
                continue
            if run.returncode != 0:
                failures.extend('%s: %s' % (flavour, l) for l in (run.stdout.strip().splitlines() or ['exited %d' % run.returncode]))

iopmgr = (root / 'ee_core/src/iopmgr.c').read_text(encoding='utf-8').replace('\r\n', '\n')
mmce_case = iopmgr[iopmgr.find('case MMCE_MODE:'):]
mmce_case = mmce_case[:mmce_case.find('break;')]
if 'OPL_MODULE_ID_SIO2MAN' in mmce_case:
    failures.append('ee_core/src/iopmgr.c: the MMCE case must not load SIO2MAN')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('Native SIO2MAN packing: idle, active VMC and PADEMU launches pass across 10 launch paths in standard, PADEMU and RA builds')
