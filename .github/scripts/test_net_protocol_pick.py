"""Turning Network Connectivity off and back on must keep the protocol the user chose (Nathan, 09-28).

gNetworkProtocol is OFF while Connectivity is Off -- every consumer reads that as "no network", and
that stays. Before gNetProtocolPick, OFF was all that was stored, so both Protocol rows (Game Sources
and Network) showed SMB afterwards and a UDPFS / UDPBD / HTTP user had to pick it again.

This compiles the real protocol helpers from src/gui.c on the host and checks:

- a live protocol is shown as itself; while Off the rows show the remembered pick;
- storing with Connectivity Off keeps the pick and leaves the live protocol OFF;
- turning Connectivity back on restores the pick (UDPFS Files and IMG, UDPBD, HTTP, SMB);
- picking a different protocol on the Network page while Off is remembered too;
- UDPBD -> UDPFS keeps IMG (the Access both pages derive from the shown protocol);

and pins the load / save / default halves in src/opl.c.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
gui = (root / 'src/gui.c').read_text(encoding='utf-8').replace('\r\n', '\n')
opl = (root / 'src/opl.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def function_text(source, signature, where):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        failures.append('%s: %s...) not found' % (where, signature))
        return ''
    end = source.index('\n}', match.start())
    return source[match.start():end] + '\n}\n'


helpers = ''.join(function_text(gui, sig, 'src/gui.c') for sig in (
    'static int guiNetProtocolShown(',
    'static int guiNetProtocolToPicker(',
    'static int guiNetProtocolAccess(',
    'static int guiNetProtocolFromPicker(',
    'static void guiNetProtocolStore(',
))

HARNESS = r'''
#include <stdio.h>

enum { NET_PROTO_OFF = 0, NET_PROTO_SMB = 1, NET_PROTO_UDPFS = 2, NET_PROTO_UDPFSBD = 3, NET_PROTO_UDPBD = 4, NET_PROTO_HTTP = 5 };
enum { START_MODE_DISABLED = 0, START_MODE_MANUAL = 1, START_MODE_AUTO = 2 };
static int gNetworkProtocol, gNetProtocolPick, gNetStartMode;

@HELPERS@

static int fails;
static void expect(const char *what, int got, int want)
{
    if (got != want) {
        printf("FAIL %s: got %d, want %d\n", what, got, want);
        fails++;
    }
}

/* One visit to a page: show the rows, the user leaves the protocol alone, sets Connectivity. */
static void visitSetConnectivity(int startMode)
{
    int shown = guiNetProtocolShown();
    int picker = guiNetProtocolToPicker(shown);
    int access = guiNetProtocolAccess(shown);
    gNetStartMode = startMode;
    guiNetProtocolStore(picker, access);
}

static void roundTrip(const char *name, int protocol)
{
    char what[96];
    gNetworkProtocol = protocol;
    gNetProtocolPick = protocol;
    gNetStartMode = START_MODE_MANUAL;

    visitSetConnectivity(START_MODE_DISABLED);
    snprintf(what, sizeof(what), "%s: Off stores OFF live", name);
    expect(what, gNetworkProtocol, NET_PROTO_OFF);
    snprintf(what, sizeof(what), "%s: Off remembers the pick", name);
    expect(what, gNetProtocolPick, protocol);
    snprintf(what, sizeof(what), "%s: rows show the pick while Off", name);
    expect(what, guiNetProtocolShown(), protocol);

    visitSetConnectivity(START_MODE_AUTO);
    snprintf(what, sizeof(what), "%s: back on restores it", name);
    expect(what, gNetworkProtocol, protocol);
}

int main(void)
{
    roundTrip("SMB", NET_PROTO_SMB);
    roundTrip("UDPFS Files", NET_PROTO_UDPFS);
    roundTrip("UDPFS IMG", NET_PROTO_UDPFSBD);
    roundTrip("UDPBD", NET_PROTO_UDPBD);
    roundTrip("HTTP", NET_PROTO_HTTP);

    /* Network page while Off: the user picks HTTP there; it is remembered, still not live. */
    gNetworkProtocol = NET_PROTO_OFF;
    gNetProtocolPick = NET_PROTO_UDPFS;
    gNetStartMode = START_MODE_DISABLED;
    guiNetProtocolStore(3, 0);
    expect("pick while Off: live stays OFF", gNetworkProtocol, NET_PROTO_OFF);
    expect("pick while Off: remembered", gNetProtocolPick, NET_PROTO_HTTP);

    /* UDPBD -> UDPFS keeps IMG: Access comes from the shown protocol. */
    gNetworkProtocol = NET_PROTO_UDPBD;
    gNetProtocolPick = NET_PROTO_UDPBD;
    gNetStartMode = START_MODE_AUTO;
    guiNetProtocolStore(1, guiNetProtocolAccess(guiNetProtocolShown()));
    expect("UDPBD -> UDPFS keeps IMG", gNetworkProtocol, NET_PROTO_UDPFSBD);

    if (!fails)
        printf("net protocol pick: Connectivity off/on keeps the chosen protocol\n");
    return fails ? 1 : 0;
}
'''

if helpers and not failures:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'pick.c'
        exe = Path(tmp) / ('pick.exe' if sys.platform == 'win32' else 'pick')
        src.write_text(HARNESS.replace('@HELPERS@', helpers), encoding='utf-8')
        build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                               capture_output=True, text=True, check=False)
        if build.returncode != 0:
            failures.append('harness did not compile:\n' + build.stderr)
        else:
            run = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
            sys.stdout.write(run.stdout)
            if run.returncode != 0:
                failures.append('protocol helpers failed the off/on round trip')

# The persisted halves (src/opl.c).
if 'configSetInt(configOPL, CONFIG_OPL_NET_PROTOCOL_PICK, gNetProtocolPick);' not in opl:
    failures.append('src/opl.c: the settings save does not write net_protocol_pick')
if not re.search(r'if \(gNetworkProtocol != NET_PROTO_OFF\)\s*gNetProtocolPick = gNetworkProtocol;\s*else if \(!configGetInt\(configOPL, CONFIG_OPL_NET_PROTOCOL_PICK', opl):
    failures.append('src/opl.c: the load does not take the pick from a live protocol, else net_protocol_pick')
load_pick = opl.find('CONFIG_OPL_NET_PROTOCOL_PICK, &gNetProtocolPick')
reconcile = opl.find('if (gNetStartMode == START_MODE_DISABLED || gNetworkProtocol == NET_PROTO_OFF)')
if load_pick < 0 or reconcile < 0 or load_pick > reconcile:
    failures.append('src/opl.c: the pick must be taken BEFORE the start-row reconcile forces OFF')
if 'gNetProtocolPick = NET_PROTO_SMB;' not in function_text(opl, 'static void setDefaults(', 'src/opl.c'):
    failures.append('src/opl.c: setDefaults does not default the pick to SMB')
if 'gNetworkProtocol = guiNetProtocolFromPicker' in gui or 'guiNetProtocolToPicker(gNetworkProtocol)' in gui:
    failures.append('src/gui.c: a Protocol row still bypasses the remembered pick')

if failures:
    for failure in failures:
        print(failure)
    sys.exit(1)
