#!/usr/bin/env python3
"""The in-game IOP memory trims hold to what the code around them can do.

Two trims give a game over SMB its IOP RAM back (Kingdom Hearts II ran out; OPL-DualSense-BT
8bb581a). Each one is only safe because of facts elsewhere in the tree, and this test ties the
numbers to those facts so a later edit cannot quietly break the assumption:

1. The in-game lwIP build (INGAME_DRIVER) sends with IP_FRAG 0. That is safe only while nothing
   the stack sends can exceed the SMAP MTU: tcp_in.c must cap a connection's segment size at
   TCP_MSS, TCP_MSS + 40 must fit the MTU smap-ingame sets, and raudp's hand-built frames must
   fit it too. It receives with IP_REASSEMBLY 1 and a buffer that must still hold a full-MTU
   datagram, in units ip_frag.c's bitmap can address.

2. When USBD serves only the pads (PADEMU on, game not on USB), ee_core hands it pool sizes on
   its command line. usbd_mini must actually parse them: the test compiles usbd.c's own option
   parser and argument loop on the host, feeds them the exact string ee_core sends, and checks
   the pools that result fit four pads behind a hub or a Bluetooth dongle, beside the driver's
   own root entries, and stay within the defaults.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
failed = 0


def fail(msg):
    global failed
    failed = 1
    print('FAIL', msg)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8', errors='replace') as f:
        return f.read()


def one(pattern, text, what, flags=0):
    m = re.findall(pattern, text, flags)
    if len(m) != 1:
        sys.exit('expected one %s, found %d' % (what, len(m)))
    return m[0]


# --- lwIP ------------------------------------------------------------------------------------------------
OPTS = 'modules/network/SMSTCPIP/include/lwipopts.h'


def lwip_macros(defines):
    cmd = ['gcc', '-E', '-dM', '-P'] + ['-D' + d for d in defines] + ['-include', os.path.join(ROOT, OPTS), '-x', 'c', '-']
    out = subprocess.run(cmd, input='', capture_output=True, text=True, check=True).stdout
    macros = {}
    for name, val in re.findall(r'^#define (\w+) (.*)$', out, re.M):
        macros[name] = val.strip()
    return macros


def num(macros, name):
    v = macros.get(name)
    if v is None:
        sys.exit('%s not defined' % name)
    v = re.sub(r'/\*.*?\*/', '', v).strip()
    return int(eval(v, {}, {}))


ingame = lwip_macros(['INGAME_DRIVER'])
menu = lwip_macros([])

mtu = int(one(r'pNetIF->mtu\s*=\s*(\d+);', read('modules/network/smap-ingame/main.c'), 'smap-ingame MTU'))
tcp_mss = num(ingame, 'TCP_MSS')
link_hlen = num(ingame, 'PBUF_LINK_HLEN')
if tcp_mss + 20 + 20 > mtu:
    fail('TCP_MSS %d + 40 bytes of headers exceeds the in-game MTU %d: segments would need ip_frag()' % (tcp_mss, mtu))
if num(ingame, 'PBUF_POOL_BUFSIZE') < tcp_mss + 40 + link_hlen:
    fail('PBUF_POOL_BUFSIZE smaller than a full segment with its headers')

tcp_in = read('modules/network/SMSTCPIP/tcp_in.c')
if 'pcb->mss = mss > TCP_MSS ? TCP_MSS : mss;' not in tcp_in:
    fail('tcp_in.c no longer caps the peer MSS at TCP_MSS: outgoing segments could exceed the MTU')

raudp = os.path.join(ROOT, 'modules/network/raudp/raudp.c')
if os.path.exists(raudp):
    src = read('modules/network/raudp/raudp.c')
    payload = int(one(r'#define RA_PAYLOAD\s+(\d+)', src, 'RA_PAYLOAD'))
    if payload + 20 + 8 > mtu:
        fail('raudp RA_PAYLOAD %d + 28 bytes of headers exceeds the MTU %d' % (payload, mtu))
    if 'lwip_sendto' in src:
        req = int(one(r'char req\[(\d+)\]', src, 'raudp discovery request buffer'))
        if req + 28 > mtu:
            fail('raudp discovery datagram %d bytes could need fragmentation' % req)

if num(ingame, 'IP_FRAG') != 0:
    fail('in-game IP_FRAG is not 0: the 1500-byte fragmentation buffer is back in every game')
if num(ingame, 'IP_REASSEMBLY') != 1:
    fail('in-game IP_REASSEMBLY is off: a sub-1500 MTU hop to the SMB server would stall every read')
reass = num(ingame, 'IP_REASS_BUFSIZE')
if reass < mtu - 20:
    fail('in-game IP_REASS_BUFSIZE %d cannot hold a fragmented full-MTU datagram (%d bytes of payload)' % (reass, mtu - 20))
if reass % 64:
    fail('in-game IP_REASS_BUFSIZE %d is not a multiple of 64: ip_frag.c sizes its bitmap as BUFSIZE / 64 and would lose the tail' % reass)
if 'IP_REASS_BUFSIZE' in menu:
    fail('menu build defines IP_REASS_BUFSIZE: the full 5760-byte reassembly buffer must stay for the loader')
if num(menu, 'IP_FRAG') != 1 or num(menu, 'IP_REASSEMBLY') != 1:
    fail('menu build lost IP fragmentation or reassembly')

frag_c = read('modules/network/SMSTCPIP/ip_frag.c')
if '#ifndef IP_REASS_BUFSIZE' not in frag_c:
    fail('ip_frag.c hard-codes IP_REASS_BUFSIZE again; the in-game override is ignored')
for guard in ('#if IP_REASSEMBLY\n', '#endif /* IP_REASSEMBLY */', '#if IP_FRAG\n', '#endif /* IP_FRAG */'):
    if guard not in frag_c:
        fail('ip_frag.c lost the %s guard' % guard.strip())

# --- USBD pad pool -------------------------------------------------------------------------------------
IOPMGR = 'ee_core/src/iopmgr.c'
USBD = 'modules/usb/usbd-ra/src/usbd.c'
iopmgr = read(IOPMGR)
usbd = read(USBD)

lit = one(r'static (?:const )?char usbd_pad_args\[\] = "((?:[^"\\]|\\.)*)";', iopmgr, 'usbd_pad_args literal')
args = lit.encode('latin-1').decode('unicode_escape').encode('latin-1')
# One call: the default arguments for a game on USB, usbd_pad_args (full length) only when USBD serves just the pads.
block = one(r'(    if \(config->GameMode == BDM_USB_MODE PADEMU_ARG\) \{\n.*?\n    \}\n)', iopmgr, 'USBD load block', re.S)
steps = ['const char *usbd_args = "thpri=2,3";', 'int usbd_args_len = 11;', '#ifdef PADEMU',
         'if (config->GameMode != BDM_USB_MODE) {', 'usbd_args = usbd_pad_args;',
         'usbd_args_len = sizeof(usbd_pad_args);', '#endif',
         'LoadOPLModule(OPL_MODULE_ID_USBD, 0, usbd_args_len, usbd_args);']
at = [block.find(s) for s in steps]
if -1 in at or at != sorted(at) or block.count('LoadOPLModule(') != 1:
    fail('ee_core does not load USBD once, with usbd_pad_args (full length) only for a game that is not on USB')
if b'\0' in args[-1:]:
    fail('usbd_pad_args should not end in an explicit NUL: sizeof() already supplies the terminator')
argv = (args + b'\0').split(b'\0')[:-1]  # IOP modload splits the argument block at NULs

parser = one(r'(struct ArgOption\n\{.*?\n\};\n\nstatic inline void ParseOptionInput\(.*?\n\}\n)', usbd, 'ParseOptionInput', re.S)
table = one(r'(    static const struct ArgOption SupportedArgs\[\] = \{.*?NULL\}\};\n)', usbd, 'SupportedArgs table', re.S)
loop = one(r'(    for \(i = 1; i < argc; i\+\+\) \{\n        for \(option = 0; SupportedArgs\[option\]\.param != NULL; option\+\+\) \{.*?\n    \}\n)', usbd, 'argument loop', re.S)
cfg = one(r'#else\nUsbdConfig usbConfig = \{\n(.*?)\n\};', usbd, 'MINI_DRIVER usbConfig', re.S)
defaults = [int(x, 0) for x in re.findall(r'^\s*(0x[0-9A-Fa-f]+|\d+),?\s*//', cfg, re.M)]
if len(defaults) != 10:
    sys.exit('could not read the ten usbd_mini defaults')

FIELDS = ['maxDevices', 'maxEndpoints', 'maxTransfDesc', 'maxIsoTransfDesc', 'maxIoReqs', 'maxStaticDescSize',
          'maxHubDevices', 'maxPortsPerHub', 'hcdThreadPrio', 'cbThreadPrio']
harness = (
    '#include <stdio.h>\n'
    'typedef struct {\n' + ''.join('    int %s;\n' % f for f in FIELDS) + '} UsbdConfig;\n'
    'static UsbdConfig usbConfig = {' + ', '.join(str(d) for d in defaults) + '};\n'
    + parser +
    'int main(int argc, char *argv[])\n{\n' + table +
    '    const char *pArgs, *pParam;\n    int i, option;\n' + loop +
    '    printf("' + ' '.join('%d' for _ in FIELDS) + '\\n", ' + ', '.join('usbConfig.' + f for f in FIELDS) + ');\n'
    '    return 0;\n}\n')

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'usbd_args.c')
    exe = os.path.join(tmp, 'usbd_args')
    with open(src, 'w') as f:
        f.write(harness)
    cc = subprocess.run(['gcc', '-std=gnu99', '-w', '-o', exe, src], capture_output=True, text=True)
    if cc.returncode:
        sys.exit('harness failed to compile:\n' + cc.stderr)
    out = subprocess.run([exe] + [a.decode() for a in argv], capture_output=True, text=True, check=True).stdout
got = dict(zip(FIELDS, (int(x) for x in out.split())))
mini = dict(zip(FIELDS, defaults))
print('usbd_mini parsed', argv, '->', got)

want = {'maxDevices': 10, 'maxEndpoints': 20, 'maxTransfDesc': 16, 'maxIsoTransfDesc': 2, 'maxIoReqs': 24,
        'maxStaticDescSize': mini['maxStaticDescSize'], 'maxHubDevices': 2, 'maxPortsPerHub': mini['maxPortsPerHub'],
        'hcdThreadPrio': 2, 'cbThreadPrio': 3}
for k, v in want.items():
    if got[k] != v:
        fail('usbd_mini read %s = %d from ee_core\'s arguments, expected %d' % (k, got[k], v))
for k in FIELDS[:8]:
    if got[k] > mini[k]:
        fail('%s = %d is above the usbd_mini default %d: that is no trim' % (k, got[k], mini[k]))

# what the pads need, read from the drivers
hcd = read('modules/usb/usbd-ra/src/hcd.c')
root_devices = len(re.findall(r'^\s*(?:memPool\.deviceTreeRoot = )?attachChildDevice\(', hcd, re.M))
usb_pads = int(one(r'#define MAX_PADS\s+(\d+)', read('modules/pademu/ds34usb.c'), 'ds34usb MAX_PADS'))
usb_eps = len(re.findall(r'UsbOpenEndpoint(?:Aligned)?\(', read('modules/pademu/ds34usb.c')))
bt_eps = len(re.findall(r'UsbOpenEndpoint(?:Aligned)?\(', read('modules/pademu/ds34bt.c')))
need_dev = root_devices + 1 + usb_pads  # root entries, one hub, the pads
need_ep = max(usb_pads * usb_eps + 2, bt_eps + 2)  # pads (or dongle) plus the hub's control and status pipes
if got['maxDevices'] < need_dev:
    fail('maxDevices %d < %d: %d root entries + a hub + %d pads' % (got['maxDevices'], need_dev, root_devices, usb_pads))
if got['maxEndpoints'] < need_ep:
    fail('maxEndpoints %d < %d needed by %d pads x %d pipes (or a dongle with %d) plus a hub' % (got['maxEndpoints'], need_ep, usb_pads, usb_eps, bt_eps))
if got['maxIoReqs'] < need_ep:
    fail('maxIoReqs %d < one in flight per pipe (%d)' % (got['maxIoReqs'], need_ep))
if got['maxTransfDesc'] < need_ep:
    fail('maxTransfDesc %d < one per pipe (%d)' % (got['maxTransfDesc'], need_ep))
if got['maxIsoTransfDesc'] < 2:
    fail('maxIsoTransfDesc must be at least 2: hcd.c links maxIsoTransfDesc - 1 descriptors')
if got['maxHubDevices'] < 1:
    fail('no hub slot left')

# the saving, from usbd_mini's pool layout (hcd.c initHcdStructs, hub.c hubInit) with the IOP's struct sizes
SZ = {'HcCA': 256, 'HcIsoTD': 32, 'HcTD': 16, 'HcED': 16, 'Endpoint': 80, 'Device': 144, 'IoRequest': 56, 'UsbHub': 168}


def pool_bytes(c):
    main = (SZ['HcCA'] + c['maxIsoTransfDesc'] * SZ['HcIsoTD'] + c['maxTransfDesc'] * SZ['HcTD'] + 0x42 * SZ['HcED']
            + c['maxEndpoints'] * SZ['Endpoint'] + c['maxDevices'] * SZ['Device'] + c['maxIoReqs'] * SZ['IoRequest']
            + (c['maxIsoTransfDesc'] + c['maxTransfDesc']) * 4 + c['maxDevices'] * c['maxStaticDescSize'])
    hubs = c['maxHubDevices'] * SZ['UsbHub']
    rnd = lambda n: (n + 255) & ~255  # AllocSysMemory hands out 256-byte blocks
    return rnd(main) + rnd(hubs)


saved = pool_bytes(mini) - pool_bytes(got)
print('USBD pool: %d -> %d bytes, %d back to the game' % (pool_bytes(mini), pool_bytes(got), saved))
if saved < 20 * 1024:
    fail('USBD trim saves only %d bytes' % saved)

if failed:
    sys.exit(1)
print('OK: in-game lwIP fragment settings fit the MTU (%d); USBD pad pool parsed from ee_core\'s arguments' % mtu)
