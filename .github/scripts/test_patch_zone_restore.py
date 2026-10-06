"""Every way back to the menu after sbPrepare restores the cdvdman patch zone.

sbPrepare (src/supportbase.c) finds the settings block of an embedded cdvdman IRX by searching the image
for the pristine cdvdman_settings_common_sample, then fills that block in place; sbUnprepare copies the
sample back. A launch that returns to the menu with the block still filled in leaves nothing for the NEXT
launch from that IRX to find: its sbPrepare logs "unable to locate patch zone." and fails, and a leg that
does not check for that carries on with an index sbPrepare never set.

The first half compiles the real sbPrepare, sbUnprepare and sbCheatsMissingContinue against a fake IRX and
shows exactly that: a filled-in zone is not found again, the failure leaves the caller's index untouched,
and sbUnprepare at irx + index (directly, or through a cancelled cheats prompt) puts the image back byte
for byte.

The second half reads the six launch legs. After sbPrepare, each return must be one of:
  - the check of sbPrepare's own result (< 0), as the very next statement, before the index is used;
  - inside `if (!sbCheatsMissingContinue(zone, ...))`, which restores the zone when it says stop;
  - after an sbUnprepare(zone) in the same or an enclosing block;
  - after a deinit, deinitEx or miniDeinit in the same or an enclosing block (no menu to return to).
`zone` must be the block sbPrepare found: (u8 *)<irx> + <index>, or &settings->common once settings has
been set to that same address.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


def function(source, signature):
    match = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', source, re.M)
    if match is None:
        sys.exit('missing ' + signature)
    return source[match.start():source.index('\n}', match.start()) + 2]


support = text('src/supportbase.c')

STUB_TAMTYPES = 'typedef unsigned char u8;\ntypedef unsigned short u16;\ntypedef unsigned int u32;\ntypedef unsigned long long u64;\n'
STUB_USBHDFSD = 'typedef struct { u64 sector; u32 count; } __attribute__((packed)) bd_fragment_t;\n'

HARNESS = r'''
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <tamtypes.h>
#include <cdvd_config.h>
#define LOG(...) ((void)0)
#define COMPAT_MODE_1 0x01
#define COMPAT_MODE_2 0x02
#define COMPAT_MODE_4 0x08
#define COMPAT_MODE_5 0x10
#define COMPAT_MODE_6 0x20
#define CONFIG_GAME 2
#define CONFIG_ITEM_OSD_SETTINGS_SOURCE "src"
#define CONFIG_ITEM_OSD_SETTINGS_ENABLE "en"
#define CONFIG_ITEM_OSD_SETTINGS_LANGID "lang"
#define CONFIG_ITEM_OSD_SETTINGS_TV_ASP "asp"
#define CONFIG_ITEM_OSD_SETTINGS_VMODE "vmode"
#define _STR_ERR_CHEATS_LOAD_FAILED 1
typedef struct config_set config_set_t;
typedef struct { u8 parts, media; } base_game_info_t;
struct UIItem;
static int gOSDLanguageSource, gOSDLanguageEnable, gOSDLanguageValue, gOSDTVAspectRatio, gOSDVideOutput;
static void *gAutoLaunchGame, *gAutoLaunchBDMGame;
static int answer;
static int sbGetCompatModes(config_set_t *c) { (void)c; return COMPAT_MODE_1; }
static void configGetDiscIDBinary(config_set_t *c, void *dst) { (void)c; memcpy(dst, "SLUS2", 5); }
static void InitGSMConfig(config_set_t *c) { (void)c; }
static void InitCheatsConfig(config_set_t *c) { (void)c; }
static config_set_t *configGetByType(int type) { (void)type; return NULL; }
static int configGetInt(config_set_t *c, const char *key, int *value) { (void)c; (void)key; (void)value; return 0; }
static const char *sbCheatsNotFoundText(void) { return ""; }
static const char *_l(int id) { (void)id; return ""; }
static int GetCheatsFromGlobalDefault(void) { return 0; }
static int guiMsgBox(const char *t, int accept, struct UIItem *ui) { (void)t; (void)accept; (void)ui; return answer; }

@FUNCTIONS@

int main(void)
{
    static u8 image[256], pristine[256];
    struct cdvdman_settings_common sample = CDVDMAN_SETTINGS_DEFAULT_COMMON;
    base_game_info_t game = {1, 0x14};
    /* sbPrepare compares a whole block at every offset it tries, so stop where one still fits. */
    int size = sizeof(image) - sizeof(sample);
    int index, r;

    memset(image, 0xA5, sizeof(image));
    memcpy(image + 64, &sample, sizeof(sample));
    memcpy(pristine, image, sizeof(image));

    index = -7;
    r = sbPrepare(&game, NULL, size, (void **)image, &index);
    printf("prepare: %d at %d\n", r, index);
    /* The leg then fills in the rest of the block (layer1_start, zso_cache, its own fields), so the
       restore has to cover every byte of it, not just the ones sbPrepare wrote. */
    memset(image + index, 0x5A, sizeof(sample));
    index = -7;
    r = sbPrepare(&game, NULL, size, (void **)image, &index);
    printf("prepare again, zone still filled in: %d at %d\n", r, index);
    sbUnprepare(image + 64);
    printf("unprepare: %s\n", memcmp(image, pristine, sizeof(image)) ? "changed" : "pristine");

    sbPrepare(&game, NULL, size, (void **)image, &index);
    memset(image + index, 0x5A, sizeof(sample));
    answer = 1;
    r = sbCheatsMissingContinue(image + index, -ENOENT);
    printf("cheats prompt, continue: %d, %s\n", r, memcmp(image, pristine, sizeof(image)) ? "filled in" : "pristine");
    answer = 0;
    r = sbCheatsMissingContinue(image + index, -ENOENT);
    printf("cheats prompt, back: %d, %s\n", r, memcmp(image, pristine, sizeof(image)) ? "filled in" : "pristine");
    index = -7;
    r = sbPrepare(&game, NULL, size, (void **)image, &index);
    printf("prepare after back: %d at %d\n", r, index);
    return 0;
}
'''

sample = re.search(r'^static const struct cdvdman_settings_common cdvdman_settings_common_sample = .*;$', support, re.M)
if sample is None:
    sys.exit('src/supportbase.c: cdvdman_settings_common_sample not found')
functions = '\n\n'.join([sample.group(0)] + [function(support, sig) for sig in (
    'int sbPrepare(', 'void sbUnprepare(', 'int sbCheatsMissingContinue(')])

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'tamtypes.h').write_text(STUB_TAMTYPES, encoding='utf-8')
    (tmp / 'usbhdfsd-common.h').write_text(STUB_USBHDFSD, encoding='utf-8')
    src, exe = tmp / 'zone.c', tmp / 'zone'
    src.write_text(HARNESS.replace('@FUNCTIONS@', functions), encoding='utf-8')
    result = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-I', str(tmp),
                             '-I', str(root / 'modules/iopcore/common'), '-o', str(exe), str(src)],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit('the sbPrepare harness did not compile:\n' + result.stderr)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=60).stdout.splitlines()
    want = ['prepare: 1 at 64',
            'prepare again, zone still filled in: -1 at -7',
            'unprepare: pristine',
            'cheats prompt, continue: 1, filled in',
            'cheats prompt, back: 0, pristine',
            'prepare after back: 1 at 64']
    if out != want:
        failures.append('sbPrepare / sbUnprepare:\n  got  %r\n  want %r' % (out, want))


def blank(source):
    """Comments and string and character literals turned to spaces (newlines kept), so a brace or a
    `return` inside one does not count and every offset still matches the file."""
    out, i = list(source), 0
    while i < len(source):
        if source.startswith('//', i):
            end = source.find('\n', i)
            end = len(source) if end < 0 else end
        elif source.startswith('/*', i):
            end = source.index('*/', i + 2) + 2
        elif source[i] in '"\'':
            end = i + 1
            while source[end] != source[i]:
                end += 2 if source[end] == '\\' else 1
            end += 1
        else:
            i += 1
            continue
        for k in range(i, end):
            if out[k] != '\n':
                out[k] = ' '
        i = end
    return ''.join(out)


def close_paren(code, opening):
    depth = 0
    for k in range(opening, len(code)):
        if code[k] == '(':
            depth += 1
        elif code[k] == ')':
            depth -= 1
            if depth == 0:
                return k
    raise ValueError('unbalanced parentheses')


def first_argument(code, opening):
    depth, k = 0, opening + 1
    while depth > 0 or code[k] not in ',)':
        depth += {'(': 1, ')': -1}.get(code[k], 0)
        k += 1
    return ' '.join(code[opening + 1:k].split())


def statement_start(code, pos):
    """True when the call at pos begins a statement, rather than being the unbraced body of an if or else
    (which runs only on that branch, so it cannot cover the code after it)."""
    before = code[:pos].rstrip()
    return before[-1:] in (';', '{', '}')


LEGS = (('src/bdmsupport.c', 'void bdmLaunchGame('), ('src/ethsupport.c', 'static void ethLaunchGame('),
        ('src/hddsupport.c', 'void hddLaunchGame('), ('src/httpsupport.c', 'static void httpLaunchGame('),
        ('src/mmcesupport.c', 'void mmceLaunchGame('), ('src/udpfssupport.c', 'static void udpfsLaunchGame('))

for path, signature in LEGS:
    source = text(path)
    code = blank(source)
    head = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', code, re.M)
    if head is None:
        sys.exit('%s: %s...) not found' % (path, signature))
    start, end = head.end() - 1, code.index('\n}', head.end()) + 2

    def line(pos):
        return '%s:%d' % (path, source.count('\n', 0, pos) + 1)

    depth, d = [], 0
    for ch in code[start:end]:
        depth.append(d)
        d += {'{': 1, '}': -1}.get(ch, 0)

    def covers(pos, ret):
        """pos runs before ret on every path: same block or an enclosing one, never closed in between."""
        return pos < ret and min(depth[pos - start:ret - start]) >= depth[pos - start]

    calls = [m.start() for m in re.finditer(r'\bsbPrepare\(', code[start:end])]
    if len(calls) != 1:
        failures.append('%s: expected one sbPrepare call in %s...), found %d' % (path, signature, len(calls)))
        continue
    prep = start + calls[0]
    opening = prep + len('sbPrepare')
    args = [' '.join(a.split()) for a in code[opening + 1:close_paren(code, opening)].split(',')]
    irx, index = args[3].lstrip('&'), args[4].lstrip('&')
    after = close_paren(code, opening) + 1

    # sbPrepare sets the index only when it finds the zone, so its result is checked before anything uses
    # the index: `x = sbPrepare(...);` then `if (x < 0) return;`, or `if (sbPrepare(...) < 0) return;`.
    lead = code[max(code.rfind(c, start, prep) for c in ';{}') + 1:prep]
    assigned = re.fullmatch(r'\s*(\w+) = ', lead)
    if assigned:
        guard = re.match(r';\s*if \(' + assigned.group(1) + r' < 0\)\s*(?:\{\s*)?return;', code[after:])
    else:
        guard = re.match(r' < 0\)\s*(?:\{\s*)?return;', code[after:]) if re.fullmatch(r'\s*if \(', lead) else None
    if guard is None:
        failures.append('%s: check sbPrepare\'s result (< 0) and return before `%s` is used' % (line(prep), index))
        guarded = after
    else:
        guarded = after + guard.end()

    zone = re.compile(r'\(u8 \*\)\s*\(?&?' + re.escape(irx) + r'\)?\s*\+\s*' + re.escape(index))
    settings = re.search(r'\bsettings = \(struct cdvdman_settings_\w+ \*\)\s*\(' + zone.pattern + r'\);', code[guarded:end])
    settings = guarded + settings.start() if settings else end

    def is_zone(arg, pos):
        return zone.fullmatch(arg) is not None or (arg == '&settings->common' and settings < pos)

    restores, cheats = [], []
    for m in re.finditer(r'\bsbUnprepare\(', code[guarded:end]):
        pos = guarded + m.start()
        arg = first_argument(code, pos + len('sbUnprepare'))
        if not is_zone(arg, pos):
            failures.append('%s: sbUnprepare(%s) is not the zone sbPrepare found (%s + %s)' % (line(pos), arg, irx, index))
        elif statement_start(code, pos):
            restores.append(pos)
    for m in re.finditer(r'\bif \(!sbCheatsMissingContinue\(', code[guarded:end]):
        pos = guarded + m.start()
        call = pos + len('if (!sbCheatsMissingContinue')
        arg = first_argument(code, call)
        if not is_zone(arg, pos):
            failures.append('%s: sbCheatsMissingContinue(%s) is not the zone sbPrepare found (%s + %s)' % (line(pos), arg, irx, index))
            continue
        body = close_paren(code, pos + len('if ')) + 1
        body += len(code[body:]) - len(code[body:].lstrip())
        if code[body] == '{':
            level, stop = 0, body
            while True:
                level += {'{': 1, '}': -1}.get(code[stop], 0)
                if level == 0:
                    break
                stop += 1
        else:
            stop = code.index(';', body)
        cheats.append((body, stop))
    teardowns = [guarded + m.start() for m in re.finditer(r'\b(?:deinit|deinitEx|miniDeinit)\(', code[guarded:end])
                 if statement_start(code, guarded + m.start())]

    for m in re.finditer(r'\breturn\b', code[guarded:end]):
        ret = guarded + m.start()
        if any(body <= ret <= stop for body, stop in cheats):
            continue
        if any(covers(pos, ret) for pos in restores + teardowns):
            continue
        failures.append('%s: returns to the menu with the patch zone still filled in -- '
                        'sbUnprepare(%s) first, or the next launch cannot find it' %
                        (line(ret), '&settings->common' if settings < ret else '(u8 *)%s + %s' % (irx, index)))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('patch zone: sbPrepare/sbUnprepare round trip, and every way back to the menu after sbPrepare restores it')
