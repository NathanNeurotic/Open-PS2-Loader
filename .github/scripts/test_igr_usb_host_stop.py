"""IGR and power-off stop the USB host controller after the device is shut down (YAOPL e72c9f48).

An IOP reset does not touch the USB host controller (OHCI). With a PADEMU USB pad, or a USB device, it kept
walking its lists and writing into memory the rebooted IOP then used, and IGR hung before the next program came
up. oplShutdown() now ends with cdvdman_usb_host_stop().

This compiles the real cdvdman_usb_host_stop() from modules/iopcore/cdvdman/cdvdman.c against simulated OHCI
registers and checks that it resets an operational controller, leaves a stopped or suspended one alone, and
waits a bounded time for a reset that never completes. It also checks that oplShutdown() calls it last, after
the VMC drain, the unmount and the power-off. This is a host check, not a console test.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
CDVDMAN = 'modules/iopcore/cdvdman/cdvdman.c'
source = (root / CDVDMAN).read_text(encoding='utf-8').replace('\r\n', '\n')


def body(signature):
    start = source.find(signature)
    if start < 0:
        sys.exit('%s: %s not found' % (CDVDMAN, signature))
    return source[start:source.index('\n}\n', start) + 3]


for name, offset in (('OHCI_HcControl', '04'), ('OHCI_HcCommandStatus', '08'), ('OHCI_HcInterruptDisable', '14')):
    if not re.search(r'^#define\s+%s\s+\(\*\(volatile u32 \*\)0xBF8016%s\)' % (name, offset), source, re.M):
        sys.exit('%s: %s is not the OHCI register at 0xBF8016%s' % (CDVDMAN, name, offset))

shutdown = body('static void oplShutdown(int poff)\n{')
steps = ['cdvdman_vmc_drain();', 'DeviceUnmount();', 'sceCdPowerOff(&stat);', 'cdvdman_usb_host_stop();']
positions = [shutdown.find(step) for step in steps]
if -1 in positions or positions != sorted(positions):
    sys.exit('oplShutdown() must drain the VMC, unmount, power off (poff), then stop the USB host: %s' % positions)
tail = shutdown[positions[-1]:]
if tail.count(';') != 1:
    sys.exit('cdvdman_usb_host_stop() must be the last thing oplShutdown() does')
if shutdown.rfind('}', 0, positions[-1]) < positions[2]:
    sys.exit('cdvdman_usb_host_stop() must run for IGR as well, not only inside the power-off branch')

harness = r'''
#include <assert.h>
#include <stdio.h>
typedef unsigned int u32;
static u32 control, status, intdis, status_reads, reset_after;
static u32 read_status(void) { status_reads++; if (reset_after && status_reads >= reset_after) status &= ~1u; return status; }
#define OHCI_HcControl control
#define OHCI_HcCommandStatus (*status_ref())
#define OHCI_HcInterruptDisable intdis
/* HcCommandStatus reads go through read_status() so the reset can finish after N polls. */
static u32 *status_ref(void) { read_status(); return &status; }
''' + body('void cdvdman_usb_host_stop(void)\n{') + r'''
static void run(u32 hcfs, u32 finish_after)
{
    control = hcfs | 0x3F; status = 0; intdis = 0; status_reads = 0; reset_after = finish_after;
    cdvdman_usb_host_stop();
}
int main(void)
{
    run(0x80, 3); /* UsbOperational: reset, interrupts off, finishes on the 3rd poll */
    assert(control == 0 && intdis == ~0u && (status & 1) == 0 && status_reads >= 3 && status_reads < 10);
    run(0x80, 0); /* the reset bit never clears: still returns, after a bounded wait */
    assert(control == 0 && intdis == ~0u && status_reads <= 1003);
    run(0x00, 1); /* UsbReset: already stopped, untouched */
    assert(control == 0x3F && intdis == 0 && status == 0);
    run(0x40, 1); /* UsbResume */
    assert(control == 0x7F && intdis == 0 && status == 0);
    run(0xC0, 1); /* UsbSuspend */
    assert(control == 0xFF && intdis == 0 && status == 0);
    puts("ok");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='igr-usb-stop-') as folder:
    src = Path(folder) / 'test.c'
    src.write_text(harness)
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(src),
                    '-o', str(Path(folder) / 'test')], check=True)
    subprocess.run([str(Path(folder) / 'test')], check=True, timeout=10)
print('PASS: IGR/power-off reset an operational USB host last, leave a stopped one alone, bounded wait')
