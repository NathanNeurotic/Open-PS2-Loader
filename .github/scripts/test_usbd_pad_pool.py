#!/usr/bin/env python3
"""The in-game IOP memory trims hold to what the code around them can do.

Two trims give a game over SMB its IOP RAM back (Kingdom Hearts II ran out; OPL-DualSense-BT
8bb581a). Each one is only safe because of facts elsewhere in the tree, and this test ties the
numbers to those facts so a later edit cannot quietly break the assumption:

1. The in-game lwIP build (INGAME_DRIVER) sends with IP_FRAG 0. That is safe only while nothing
   the stack sends can exceed the SMAP MTU: tcp_in.c must cap a connection's segment size at
   TCP_MSS, TCP_MSS + 40 must fit the MTU smap-ingame sets, and raudp's hand-built frames must
   fit it too. It receives with IP_REASSEMBLY 1 and a buffer that must still hold a full-MTU
   datagram. The test also compiles ip_frag.c's own reassembly code on the host, under
   AddressSanitizer, and feeds it fragments: a datagram that ends exactly at the end of the
   buffer (the bitmap needs a byte for that end), a hole in the bitmap's second-to-last byte
   (the completeness check must see it), and an ordinary 1480-byte datagram in two pieces.

2. When USBD serves only the pads (PADEMU on, game not on USB), ee_core hands it pool sizes on
   its command line. usbd_mini must actually parse them: the test compiles usbd.c's own option
   parser and argument loop on the host, feeds them the exact string ee_core sends, and checks
   the pools that result fit four pads behind a hub or a Bluetooth dongle, beside the driver's
   own root entries, and stay within the defaults. The general transfer descriptors are not
   trimmed: a request that finds too few waits at the head of usbd's queue (usbio.c
   checkTdQueue retries only the head), so a shortfall stalls every pipe behind it.
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

# ip_reass() itself, on the host: the copy helper and the reassembly half of ip_frag.c, verbatim,
# around stand-ins for the pbuf, header and alarm calls it makes. AddressSanitizer catches a
# bitmap access past the end; the scenarios check what comes back.
REASS_HARNESS = r"""
#include <arpa/inet.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8_t;
typedef uint16_t u16_t;
typedef uint32_t u32_t;
typedef struct { u32_t lo, hi; } iop_sys_clock_t;
struct ip_addr { u32_t addr; };
struct ip_hdr {
    u16_t _v_hl_tos, _len, _id, _offset, _ttl_proto, _chksum;
    struct ip_addr src, dest;
};
#define IP_HLEN 20
#define IP_MF 0x2000
#define IP_OFFMASK 0x1fff
#define IPH_HL(hdr) ((ntohs((hdr)->_v_hl_tos) >> 8) & 0x0f)
#define IPH_LEN(hdr) ((hdr)->_len)
#define IPH_ID(hdr) ((hdr)->_id)
#define IPH_OFFSET(hdr) ((hdr)->_offset)
#define IPH_LEN_SET(hdr, len) (hdr)->_len = (len)
#define IPH_OFFSET_SET(hdr, off) (hdr)->_offset = (off)
#define IPH_CHKSUM_SET(hdr, chksum) (hdr)->_chksum = (chksum)
#define ip_addr_cmp(a, b) ((a)->addr == (b)->addr)
#define LWIP_DEBUGF(debug, x) do { } while (0)
#define mips_memcpy memcpy
#define mips_memset memset
#define PBUF_LINK 0
#define PBUF_POOL 0
struct pbuf { struct pbuf *next; void *payload; u16_t tot_len, len; };
static struct pbuf *pbuf_alloc(int layer, u16_t len, int type)
{
    struct pbuf *p = malloc(sizeof(*p) + len);
    p->next = NULL;
    p->payload = p + 1;
    p->tot_len = p->len = len;
    return p;
}
static void pbuf_free(struct pbuf *p) { free(p); }
static u16_t inet_chksum(void *data, u16_t len) { return 0; }
static int SetAlarm(iop_sys_clock_t *clock, unsigned (*handler)(void *), void *arg) { return 0; }
static int CancelAlarm(unsigned (*handler)(void *), void *arg) { return 0; }
#define IP_REASSEMBLY 1
#define IP_FRAG 0
#define IP_REASS_BUFSIZE @BUFSIZE@
@COPY@
@REASS@
static u8_t payload[IP_REASS_BUFSIZE + 64];

/* One fragment of datagram `id`: payload bytes [off, off + len), more fragments to come if mf. */
static struct pbuf *frag(u16_t id, u16_t off, u16_t len, int mf)
{
    struct pbuf *p = pbuf_alloc(0, IP_HLEN + len, 0);
    struct ip_hdr *h = p->payload;
    memset(h, 0, IP_HLEN);
    h->_v_hl_tos = htons(0x4500);
    h->_len = htons(IP_HLEN + len);
    h->_id = htons(id);
    h->_offset = htons((off / 8) | (mf ? IP_MF : 0));
    h->src.addr = 0x0a000001;
    h->dest.addr = 0x0a000002;
    memcpy((u8_t *)p->payload + IP_HLEN, payload + off, len);
    return p;
}

/* The datagram that came back must carry exactly bytes [0, total) of the payload. */
static int whole(struct pbuf *p, u16_t total)
{
    int ok = p && p->tot_len == IP_HLEN + total && !memcmp((u8_t *)p->payload + IP_HLEN, payload, total);
    if (p)
        pbuf_free(p);
    return ok;
}

int main(void)
{
    int i, bad = 0;
    struct pbuf *r;
    for (i = 0; i < (int)sizeof(payload); i++)
        payload[i] = (u8_t)(i * 7 + 3);

    /* A datagram whose last fragment ends exactly at the end of the buffer. */
    r = ip_reass(frag(1, 0, IP_REASS_BUFSIZE - 512, 1));
    if (r) { printf("exact: complete after the first fragment\n"); bad = 1; pbuf_free(r); }
    r = ip_reass(frag(1, IP_REASS_BUFSIZE - 512, 512, 0));
    if (!whole(r, IP_REASS_BUFSIZE)) { printf("exact: a datagram that fills the buffer did not reassemble\n"); bad = 1; }

    /* One byte of the bitmap covers 64 bytes of payload. Leave out bytes 1408-1471 of a 1480-byte
       datagram, the second-to-last bitmap byte: the datagram must not come back until they arrive. */
    r = ip_reass(frag(2, 0, 1408, 1));
    if (r) { printf("hole: complete after the first fragment\n"); bad = 1; pbuf_free(r); }
    r = ip_reass(frag(2, 1472, 8, 0));
    if (r) { printf("hole: returned with bytes 1408-1471 missing\n"); bad = 1; pbuf_free(r); }
    r = ip_reass(frag(2, 1408, 64, 1));
    if (!whole(r, 1480)) { printf("hole: did not reassemble once the gap was filled\n"); bad = 1; }

    /* An ordinary full-MTU datagram split across a smaller hop. */
    r = ip_reass(frag(3, 0, 1024, 1));
    if (r) { printf("plain: complete after the first fragment\n"); bad = 1; pbuf_free(r); }
    r = ip_reass(frag(3, 1024, 456, 0));
    if (!whole(r, 1480)) { printf("plain: a 1480-byte datagram did not reassemble\n"); bad = 1; }

    /* A fragment that would run past the buffer is dropped, and the next datagram starts clean. */
    r = ip_reass(frag(4, IP_REASS_BUFSIZE - 8, 16, 0));
    if (r) { printf("over: a fragment past the buffer was accepted\n"); bad = 1; pbuf_free(r); }
    r = ip_reass(frag(5, 0, 64, 0));
    if (!whole(r, 64)) { printf("over: the next datagram did not go through\n"); bad = 1; }

    if (!bad)
        printf("reass ok\n");
    return bad;
}
"""
copy_fn = one(r'(#if IP_REASSEMBLY \|\| IP_FRAG\n.*?#endif /\* IP_REASSEMBLY \|\| IP_FRAG \*/\n)', frag_c, 'copy_from_pbuf block', re.S)
reass_fn = one(r'(#if IP_REASSEMBLY\n#ifndef IP_REASS_BUFSIZE.*?#endif /\* IP_REASSEMBLY \*/\n)', frag_c, 'ip_reass block', re.S)
harness_c = REASS_HARNESS.replace('@BUFSIZE@', str(reass)).replace('@COPY@', copy_fn).replace('@REASS@', reass_fn)
with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'reass.c')
    exe = os.path.join(tmp, 'reass')
    with open(src, 'w') as f:
        f.write(harness_c)
    cc = subprocess.run(['gcc', '-std=gnu99', '-g', '-O1', '-w', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                         '-fno-omit-frame-pointer', '-o', exe, src], capture_output=True, text=True)
    if cc.returncode:
        sys.exit('ip_reass harness failed to compile (it needs gcc with AddressSanitizer):\n' + cc.stderr)
    run = subprocess.run([exe], capture_output=True, text=True)
    print(run.stdout.strip() or '(no output)')
    if run.returncode:
        fail('ip_reass on the host, IP_REASS_BUFSIZE %d:\n%s%s' % (reass, run.stdout, run.stderr[-3000:]))

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

want = {'maxDevices': 10, 'maxEndpoints': 20, 'maxTransfDesc': mini['maxTransfDesc'], 'maxIsoTransfDesc': 2, 'maxIoReqs': 24,
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
# Transfer descriptors: every open pipe keeps one as its tail (hcd.c openDeviceEndpoint), every
# bulk or interrupt transfer in flight takes one more (usbio.c setupBulkTransfer), and a control
# request with data three more (setupControlTransfer). When the free list runs short the request
# waits in a queue of which checkTdQueue retries only the head, so a control request that cannot
# get its three holds up every pipe queued behind it. Worst case with four USB pads behind a hub:
# every pipe's tail, the hub's status read, a report read and a SET_REPORT write on every pad, and
# two more control requests (a DS3 sends two back to back when it connects, and a new device on
# the hub is enumerated with them).
if b'gtd=' in args:
    fail('ee_core trims usbd_mini\'s general transfer descriptors again; a shortfall there stalls the pads')
need_td = need_ep + 1 + usb_pads * (1 + 3) + 2 * 3
if got['maxTransfDesc'] < need_td:
    fail('maxTransfDesc %d < %d: %d pipe tails, the hub status read, a read and a control write per pad, two more control requests' % (got['maxTransfDesc'], need_td, need_ep))
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
