"""The UDPFS/UDPBD toml ip sync must leave a parseable file on a memory card (#1010).

sysSyncNeutrinoUdpfsToml rewrites the "ip=" token in Neutrino's config/bsd-<device>.toml. It opened
the file with O_WRONLY | O_TRUNC, and mcman (mc0:/mc1:) ignores O_TRUNC unless O_CREAT is also set
(ps2sdk mcman_open2 keeps the old length). A rewrite that shortened the ip therefore left the old
file's last bytes after the new content -- `]`, `"]`, `EE"]` -- Neutrino could no longer parse the
toml and every UDPFS game dropped to the browser before reaching the network. The tear sits after
the ip, so later syncs saw the ip in sync and never rewrote the file again.

This compiles the real functions from src/system.c against a fake file that behaves like mcman
(and, as a control, like FAT) and checks both the write and the repair of an already torn file.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
system = (root / 'src/system.c').read_text(encoding='utf-8').replace('\r\n', '\n')
failures = []


def extract_function(source, signature):
    """Return the full text of the C function whose definition starts with `signature`."""
    start = source.find(signature)
    if start < 0:
        return None
    i = source.index('{', start)
    depth = 0
    while i < len(source):
        c = source[i]
        if source.startswith('//', i):
            i = source.index('\n', i)
            continue
        if source.startswith('/*', i):
            i = source.index('*/', i) + 2
            continue
        if c in '"\'':
            i += 1
            while source[i] != c:
                i += 2 if source[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    return None


def extract_define(source, name):
    for line in source.splitlines():
        if line.startswith('#define %s ' % name):
            return line
    return None


pieces = []
for signature in ('static const char *sysLastPathSeparator(',
                  'static int sysTomlTornTailCut(',
                  'static int sysSyncNeutrinoUdpfsToml('):
    body = extract_function(system, signature)
    if body is None:
        failures.append('src/system.c: %s not found' % signature)
    pieces.append(body or '')
defines = []
for name in ('NEUTRINO_TOML_REWRITE_FLAGS', 'NEUTRINO_TOML_TORN_TAIL_MAX'):
    line = extract_define(system, name)
    if line is None:
        failures.append('src/system.c: %s is not defined' % name)
    defines.append(line or '')

# Neutrino's stock config/bsd-udpfs.toml, byte for byte (rickgaiser/neutrino ee/loader/config).
STOCK = (
    '# Name of loaded config, to show to user\n'
    'name = "UDPFS driver"\n'
    '\n'
    '# Drivers this driver depends on (config file must exist)\n'
    'depends = ["i_dev9_hidden"]\n'
    '\n'
    '# Modules to load\n'
    '[[module]]\n'
    'file = "iomanX.irx"\n'
    'env = ["LE"]\n'
    '[[module]]\n'
    'file = "fileXio.irx"\n'
    'env = ["LE"]\n'
    '[[module]]\n'
    'file = "smap.irx"\n'
    'env = ["LE", "EE"]\n'
    '[[module]]\n'
    'file = "ministack.irx"\n'
    'args = ["ip=192.168.1.10"]\n'
    'env = ["LE", "EE"]\n'
    '[[module]]\n'
    'file = "udpfs_ioman.irx"\n'
    'env = ["LE"]\n'
    '[[module]]\n'
    'file = "udpfs_fhi.irx"\n'
    'env = ["EE"]\n'
)

# A valid hand-edited toml the scanner must not mistake for a torn one: multi-line arrays, comments and
# strings that hold brackets and quotes, a literal string and a multi-line string.
HAND = (
    '# custom ] " [ notes\n'
    "name = 'my [udpfs] build'\n"
    'note = """two\n'
    'lines ] here"""\n'
    '[[module]]\n'
    'file = "ministack.irx"\n'
    'args = [\n'
    '    "ip=192.168.1.10", # trailing ] comment\n'
    '    "x=\\"q\\"",\n'
    ']\n'
    'env = ["LE", "EE"]\n'
)


def c_string(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


PROGRAM = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* PS2 (iomanX / mcman) flag values, so the fake file sees exactly what mcman would. */
#define O_RDONLY 0x0001
#define O_WRONLY 0x0002
#define O_CREAT  0x0200
#define O_TRUNC  0x0400

#define LOG(...) ((void)0)
static int ps2_ip[4];

/* One fake file. mc = 1 behaves like mcman: O_TRUNC is ignored unless O_CREAT is set, and O_CREAT
   recreates the file empty. mc = 0 behaves like FAT: O_TRUNC empties it. */
static char file[8192];
static int fileLen, filePos, fileMc, writes;

static int fake_open(const char *path, int flags, ...)
{
    (void)path;
    filePos = 0;
    if (flags & O_CREAT)
        fileLen = 0;
    else if ((flags & O_TRUNC) && !fileMc)
        fileLen = 0;
    return 3;
}
static int fake_read(int fd, void *buf, int size)
{
    (void)fd;
    int n = fileLen - filePos < size ? fileLen - filePos : size;
    memcpy(buf, file + filePos, n);
    filePos += n;
    return n;
}
static int fake_write(int fd, const void *buf, int size)
{
    (void)fd;
    memcpy(file + filePos, buf, size);
    filePos += size;
    if (filePos > fileLen)
        fileLen = filePos;
    writes++;
    return size;
}
static int fake_close(int fd) { (void)fd; return 0; }
#define open fake_open
#define read fake_read
#define write fake_write
#define close fake_close

@DEFINES@
@FUNCTIONS@

static int fails;
static void setFile(const char *text, int mc) { fileLen = (int)strlen(text); memcpy(file, text, fileLen); fileMc = mc; writes = 0; }
static void setIp(int a, int b, int c, int d) { ps2_ip[0] = a; ps2_ip[1] = b; ps2_ip[2] = c; ps2_ip[3] = d; }
static void expect(const char *want, int rc, const char *what)
{
    if (rc != 0) { printf("FAIL %s: sync returned %d\n", what, rc); fails++; return; }
    if ((int)strlen(want) != fileLen || memcmp(want, file, fileLen) != 0) {
        printf("FAIL %s: file is %d bytes, want %d; tail \"%.*s\"\n", what, fileLen, (int)strlen(want),
               fileLen > 12 ? 12 : fileLen, file + (fileLen > 12 ? fileLen - 12 : 0));
        fails++;
    }
}
static char *withIp(const char *text, const char *ip)
{
    static char out[8192];
    const char *at = strstr(text, "ip=192.168.1.10");
    snprintf(out, sizeof(out), "%.*sip=%s%s", (int)(at - text), text, ip, at + strlen("ip=192.168.1.10"));
    return out;
}

int main(void)
{
    const char *stock = @STOCK@;
    const char *hand = @HAND@;
    const char *path = "mc1:/neutrino/neutrino.elf";
    char torn[8192];
    int k;

    /* The #1010 write: a shorter ip on a memory card must not leave the old tail behind. */
    for (int mc = 0; mc <= 1; mc++) {
        const char *fs = mc ? "mc" : "fat";
        char what[64];
        setFile(stock, mc);
        setIp(10, 0, 0, 5);
        snprintf(what, sizeof(what), "%s: ip shortened by 3", fs);
        expect(withIp(stock, "10.0.0.5"), sysSyncNeutrinoUdpfsToml(path, "udpfs"), what);
        setIp(192, 168, 100, 123);
        snprintf(what, sizeof(what), "%s: ip lengthened again", fs);
        expect(withIp(stock, "192.168.100.123"), sysSyncNeutrinoUdpfsToml(path, "udpfs"), what);
        setIp(192, 168, 1, 10);
        snprintf(what, sizeof(what), "%s: back to the stock ip", fs);
        expect(stock, sysSyncNeutrinoUdpfsToml(path, "udpfs"), what);
    }

    /* A card torn by an older RiptOPL: the ip already matches, the tail still has to go. */
    for (k = 2; k <= 6; k++) {
        char what[64];
        snprintf(torn, sizeof(torn), "%s%s", stock, stock + strlen(stock) - k);
        setFile(torn, 1);
        setIp(192, 168, 1, 10);
        snprintf(what, sizeof(what), "torn tail of %d bytes, ip in sync", k);
        expect(stock, sysSyncNeutrinoUdpfsToml(path, "udpfs"), what);
    }
    /* The same tear on a toml whose last line has no newline: the stale bytes land on that line, and
       the repair must keep the line itself (`env = ["EE"]"]` -> `env = ["EE"]`). */
    {
        char bare[4096];
        snprintf(bare, sizeof(bare), "%s", stock);
        bare[strlen(bare) - 1] = '\0';
        for (k = 2; k <= 8; k++) {
            char what[64];
            snprintf(torn, sizeof(torn), "%s%s", bare, bare + strlen(bare) - k);
            setFile(torn, 1);
            setIp(192, 168, 1, 10);
            snprintf(what, sizeof(what), "no final newline, torn by %d bytes", k);
            expect(bare, sysSyncNeutrinoUdpfsToml(path, "udpfs"), what);
        }
        snprintf(torn, sizeof(torn), "%s\"]", bare);
        setFile(torn, 1);
        setIp(10, 0, 0, 9);
        expect(withIp(bare, "10.0.0.9"), sysSyncNeutrinoUdpfsToml(path, "udpfs"), "no final newline, torn, new ip");
        if (sysTomlTornTailCut(bare, (int)strlen(bare)) != (int)strlen(bare)) { printf("FAIL stock without a final newline judged torn\n"); fails++; }
    }
    {
        /* The hand-edited toml without its final newline, torn on that last line. */
        char want[4096];
        snprintf(want, sizeof(want), "%.*s", (int)strlen(hand) - 1, hand);
        snprintf(torn, sizeof(torn), "%s\"]", want);
        setFile(torn, 1);
        setIp(192, 168, 1, 10);
        expect(want, sysSyncNeutrinoUdpfsToml(path, "udpfs"), "hand-edited, no final newline, torn");

        /* A multi-line array that closes the file, torn right after its `]`. */
        snprintf(want, sizeof(want), "args = [\n    \"ip=192.168.1.10\",\n    \"x\",\n]");
        snprintf(torn, sizeof(torn), "%s\"]", want);
        setFile(torn, 1);
        setIp(192, 168, 1, 10);
        expect(want, sysSyncNeutrinoUdpfsToml(path, "udpfs"), "multi-line array, no final newline, torn");
    }

    snprintf(torn, sizeof(torn), "%s\"]\n]\n", stock);
    setFile(torn, 1);
    setIp(192, 168, 1, 10);
    expect(stock, sysSyncNeutrinoUdpfsToml(path, "udpfs"), "tail torn twice");
    snprintf(torn, sizeof(torn), "%sEE\"]\n", stock);
    setFile(torn, 1);
    setIp(10, 1, 1, 7);
    expect(withIp(stock, "10.1.1.7"), sysSyncNeutrinoUdpfsToml(path, "udpfs"), "torn tail and a new ip");

    /* Nothing else changes: a valid hand-edited file in sync is never written. */
    setFile(hand, 1);
    setIp(192, 168, 1, 10);
    expect(hand, sysSyncNeutrinoUdpfsToml(path, "udpfs"), "hand-edited toml in sync");
    if (writes) { printf("FAIL hand-edited toml in sync was written\n"); fails++; }
    setFile(hand, 1);
    setIp(10, 0, 0, 2);
    expect(withIp(hand, "10.0.0.2"), sysSyncNeutrinoUdpfsToml(path, "udpfs"), "hand-edited toml, new ip");

    /* Broken far from its end: the user's file, left exactly as it is. */
    snprintf(torn, sizeof(torn), "]\n%s", stock);
    setFile(torn, 1);
    setIp(192, 168, 1, 10);
    expect(torn, sysSyncNeutrinoUdpfsToml(path, "udpfs"), "broken at the top");
    if (writes) { printf("FAIL a toml broken at the top was written\n"); fails++; }

    if (sysTomlTornTailCut(stock, (int)strlen(stock)) != (int)strlen(stock)) { printf("FAIL stock toml judged torn\n"); fails++; }
    if (sysTomlTornTailCut(hand, (int)strlen(hand)) != (int)strlen(hand)) { printf("FAIL hand-edited toml judged torn\n"); fails++; }
    return fails ? 1 : 0;
}
'''

if not failures:
    program = (PROGRAM.replace('@DEFINES@', '\n'.join(defines))
               .replace('@FUNCTIONS@', '\n\n'.join(pieces))
               .replace('@STOCK@', c_string(STOCK))
               .replace('@HAND@', c_string(HAND)))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'tomlsync.c'
        exe = Path(tmp) / ('tomlsync.exe' if sys.platform == 'win32' else 'tomlsync')
        src.write_text(program, encoding='utf-8')
        try:
            build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-o', str(exe), str(src)],
                                   capture_output=True, text=True, check=False, timeout=120)
        except subprocess.TimeoutExpired:
            build = None
            failures.append('gcc did not finish within 120 s')
        if build is not None and build.returncode != 0:
            failures.append('harness did not compile:\n%s' % build.stderr)
        elif build is not None:
            try:
                run = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=10)
                if run.returncode != 0:
                    failures.extend(run.stdout.strip().splitlines() or ['exited %d' % run.returncode])
            except subprocess.TimeoutExpired:
                failures.append('harness did not finish within 10 s')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('toml ip sync: memory-card rewrites and torn-tail repair OK')
