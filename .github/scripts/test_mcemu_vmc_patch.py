"""Every native launch hands mcemu its VMC slots, even after an earlier launch went back to the menu.

mcemu reads its VMC settings from vmcSpec[slot] inside its own image, so the native legs (BDM, SMB, APA,
MMCE) write them into the embedded IRX before they launch. vmcSpec[slot] is found by its starting value:
`active` begins as 0xC0DEFAC0 + slot (modules/mcemu/mcemu_var.c). The first write replaces that marker and
nothing puts it back. When every launch searched for it, a launch that went back to the menu after the
write (a declined VMC prompt, a cancelled cheats prompt, a failed open, a Neutrino abort) left the next one
nothing to find: size_mcemu_irx stayed 0, the same as "no VMC", and the game saved to the real card.

sbPatchVmcSpec (src/supportbase.c) now searches once per slot and keeps the word it found in a static the
leg owns, so every later launch writes at the same place.

The first part compiles the real sbPatchVmcSpec against a fake IRX that ends right before a page nobody
may touch, and replays launches that go back to the menu: every slot lands where its marker was, a plain
search finds nothing once a launch has written, and neither a missing marker nor a marker too near the
end makes it read or write past the image.

The second part reads the four legs. Each must patch through sbPatchVmcSpec, with its own IRX, its own
struct and size, and a `static int name[2] = {-1, -1}` that nothing else touches; reset its struct and then
patch on every pass of the slot loop, set up or not, so a slot an aborted launch marked active never
reaches mcemu; turn mcemu on only for a slot that was written and is active; and launch that same IRX.
Nothing outside sbPatchVmcSpec may look for the marker itself.

The last part breaks the code on purpose, one way at a time, and checks that each break is caught.
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
        return None
    return source[match.start():source.index('\n}', match.start()) + 2]


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#define LOG(...) ((void)0)
typedef unsigned char u8;
typedef unsigned int u32;

@FUNCTION@

/* Stands in for a leg's *_vmc_infos_t: `active` first, like all four of them. Six words. */
typedef struct {
    int active;
    u8 card[20];
} infos_t;

#define WORDS 64 /* the fake IRX: the last 64 words before a page that faults on any access */
static u32 *image, pristine[WORDS];

static void fresh(int slot0, int slot1)
{
    for (int i = 0; i < WORDS; i++)
        image[i] = 0xA5A5A5A5u - (u32)i;
    if (slot0 >= 0)
        image[slot0] = 0xC0DEFAC0u;
    if (slot1 >= 0)
        image[slot1] = 0xC0DEFAC1u;
    memcpy(pristine, image, sizeof(pristine));
}

static infos_t card(int active, int fill)
{
    infos_t infos;
    memset(&infos, 0, sizeof(infos));
    infos.active = active;
    memset(infos.card, fill, sizeof(infos.card));
    return infos;
}

static void patch(const char *what, int slot, infos_t infos, int *specWord)
{
    int r = sbPatchVmcSpec(image, WORDS * (int)sizeof(u32), slot, &infos, sizeof(infos), specWord);
    printf("%s: %d at %d\n", what, r, specWord[slot]);
    fflush(stdout);
}

static const char *untouched(void) { return memcmp(image, pristine, sizeof(pristine)) ? "changed" : "untouched"; }

int main(void)
{
    long page = sysconf(_SC_PAGESIZE);
    u8 *map = mmap(NULL, 2 * page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (map == MAP_FAILED || mprotect(map + page, page, PROT_NONE) != 0)
        return 2;
    image = (u32 *)(map + page) - WORDS;

    /* Kept across launches, the way each leg keeps its static. */
    int specWord[2] = {-1, -1};
    fresh(40, 46);
    patch("launch 1, slot 0", 0, card(1, 0x11), specWord);
    /* The VMC prompt for slot 1 is declined: back to the menu, slot 0's marker already written over. */
    patch("launch 2, slot 0", 0, card(1, 0x21), specWord);
    patch("launch 2, slot 1", 1, card(1, 0x22), specWord);
    /* Back to the menu again (a cancelled cheats prompt, say). The next game has a card in slot 1 only. */
    patch("launch 3, slot 0", 0, card(0, 0x00), specWord);
    patch("launch 3, slot 1", 1, card(1, 0x32), specWord);

    u32 want[WORDS];
    infos_t slot0 = card(0, 0x00), slot1 = card(1, 0x32);
    memcpy(want, pristine, sizeof(want));
    memcpy(&want[40], &slot0, sizeof(slot0));
    memcpy(&want[46], &slot1, sizeof(slot1));
    printf("image: %s\n", memcmp(image, want, sizeof(want)) ? "not launch 3's slots" : "launch 3's slots, nothing else");

    /* What every launch after the first used to do: search again. Both markers are gone. */
    int searchAgain[2] = {-1, -1};
    memcpy(pristine, image, sizeof(pristine));
    patch("searching again after a launch", 0, card(1, 0x41), searchAgain);
    printf("  image %s\n", untouched());

    /* No marker anywhere: the search has to stop at the end of the image, or the next page faults. */
    int none[2] = {-1, -1};
    fresh(-1, -1);
    patch("no marker", 0, card(1, 0x51), none);
    printf("  image %s\n", untouched());

    /* A six-word slot still fits after word 58 of 64. One word later it would run past the end. */
    int last[2] = {-1, -1}, over[2] = {-1, -1};
    fresh(58, -1);
    patch("marker where the slot just fits", 0, card(1, 0x61), last);
    fresh(59, -1);
    patch("marker one word later", 0, card(1, 0x71), over);
    printf("  image %s\n", untouched());
    return 0;
}
'''

WANT = ['launch 1, slot 0: 1 at 40',
        'launch 2, slot 0: 1 at 40',
        'launch 2, slot 1: 1 at 46',
        'launch 3, slot 0: 1 at 40',
        'launch 3, slot 1: 1 at 46',
        "image: launch 3's slots, nothing else",
        'searching again after a launch: 0 at -1',
        '  image untouched',
        'no marker: 0 at -1',
        '  image untouched',
        'marker where the slot just fits: 1 at 58',
        'marker one word later: 0 at -1',
        '  image untouched']


def helper_failures(helper, tmp, name):
    src, exe = tmp / (name + '.c'), tmp / name
    src.write_text(HARNESS.replace('@FUNCTION@', helper), encoding='utf-8')
    built = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(src)],
                           capture_output=True, text=True, check=False)
    if built.returncode != 0:
        return ['sbPatchVmcSpec: the harness did not compile:\n' + built.stderr]
    ran = subprocess.run([str(exe)], capture_output=True, text=True, check=False, timeout=60)
    out = ran.stdout.splitlines()
    if ran.returncode != 0:
        return ['sbPatchVmcSpec: the harness died (exit %d) after %r -- a read or write past the image' % (ran.returncode, out[-1:])]
    if out != WANT:
        return ['sbPatchVmcSpec:\n  got  %r\n  want %r' % (out, WANT)]
    return []


def blank(source):
    """Comments and string and character literals turned to spaces (newlines kept), so nothing inside one
    counts, and every offset still matches the file."""
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


def arguments(code, opening):
    args, depth, k, first = [], 0, opening + 1, opening + 1
    while True:
        ch = code[k]
        if ch == '(':
            depth += 1
        elif ch == ')' and depth > 0:
            depth -= 1
        elif ch in ',)' and depth == 0:
            args.append(' '.join(code[first:k].split()))
            if ch == ')':
                return args
            first = k + 1
        k += 1


def statement_start(code, pos):
    """True when pos begins a statement, rather than being the unbraced body of an if or else."""
    return code[:pos].rstrip()[-1:] in (';', '{', '}')


LEGS = (('src/bdmsupport.c', 'void bdmLaunchGame(', 'bdm_mcemu_irx', 'bdm_vmc_infos'),
        ('src/ethsupport.c', 'static void ethLaunchGame(', 'smb_mcemu_irx', 'smb_vmc_infos'),
        ('src/hddsupport.c', 'void hddLaunchGame(', 'hdd_mcemu_irx', 'hdd_vmc_infos'),
        ('src/mmcesupport.c', 'void mmceLaunchGame(', 'mmce_mcemu_irx', 'mmce_vmc_infos'))


def leg_failures(path, source, signature, irx, infos):
    code = blank(source)
    head = re.search(r'^' + re.escape(signature) + r'[^;{]*\)\s*\{', code, re.M)
    if head is None:
        return ['%s: %s...) not found' % (path, signature)]
    start, end = head.end() - 1, code.index('\n}', head.end()) + 2
    body = code[start:end]
    found = []

    def line(pos):
        return '%s:%d' % (path, source.count('\n', 0, pos) + 1)

    depth, d = [], 0
    for ch in body:
        depth.append(d)
        d += {'{': 1, '}': -1}.get(ch, 0)

    calls = [start + m.start() for m in re.finditer(r'\bsbPatchVmcSpec\(', body)]
    if len(calls) != 1:
        return ['%s: expected one sbPatchVmcSpec call in %s...), found %d -- a leg that searches for the marker '
                'itself finds nothing after its first launch' % (path, signature, len(calls))]
    call = calls[0]
    opening = call + len('sbPatchVmcSpec')
    args = arguments(code, opening)
    want = ['&' + irx, 'size_' + irx, 'vmc_id', '&' + infos]
    if len(args) != 6 or args[:4] != want or args[4] not in ('sizeof(%s)' % infos, 'sizeof(%s_t)' % infos):
        found.append('%s: sbPatchVmcSpec(%s) must patch this leg\'s own IRX with this slot\'s %s: (%s, sizeof(%s_t), <static>)' %
                     (line(call), ', '.join(args), infos, ', '.join(want), infos))
        return found

    # The word each slot was found at has to outlive the launch, so a static only this call uses.
    word = args[5]
    if not re.search(r'\bstatic int ' + re.escape(word) + r'\[2\] = \{-1, -1\};', code[start:call]):
        found.append('%s: %s must be `static int %s[2] = {-1, -1};` in this function, before the slot loop -- '
                     'the first launch writes over the markers that find the slots' % (line(call), word, word))
    uses = [start + m.start() for m in re.finditer(r'\b' + re.escape(word) + r'\b', body)]
    if len(uses) != 2:
        found.append('%s: nothing but its declaration and sbPatchVmcSpec may touch %s (found %d uses)' %
                     (line(call), word, len(uses)))

    # Every pass of the slot loop resets this slot's struct, then writes it, set up or not.
    loop = re.search(r'\bfor \(vmc_id = 0; vmc_id < 2; vmc_id\+\+\) \{', body)
    if loop is None:
        found.append('%s: the slot loop `for (vmc_id = 0; vmc_id < 2; vmc_id++) {` is gone' % line(call))
        return found
    brace = start + loop.end() - 1
    level, close = 0, brace
    while True:
        level += {'{': 1, '}': -1}.get(code[close], 0)
        if level == 0:
            break
        close += 1
    inner = depth[brace - start] + 1
    lead = re.search(r'\bif \(\s*$', code[:call])
    stmt = lead.start() if lead else call
    if not (brace < stmt < close and depth[stmt - start] == inner and statement_start(code, stmt)):
        found.append('%s: sbPatchVmcSpec must run on every pass of the slot loop, set up or not -- a slot left '
                     'alone keeps what an aborted launch wrote, maybe an active card' % line(call))
    if re.search(r'\bcontinue\b', code[brace:call]):
        found.append('%s: a `continue` before sbPatchVmcSpec skips writing that slot' % line(call))
    resets = [brace + m.start() for m in re.finditer(r'\bmemset\(&%s, 0, sizeof\(%s(?:_t)?\)\);|\b%s\.active = 0;' %
                                                      (infos, infos, infos), code[brace:call])]
    if not any(depth[pos - start] == inner and statement_start(code, pos) for pos in resets):
        found.append('%s: each pass of the slot loop must start from a cleared %s (memset, or %s.active = 0) -- '
                     'a slot with no card would otherwise be written with the last one\'s' % (line(brace), infos, infos))

    # mcemu is loaded only for a slot that was written and is active.
    if lead is None or not re.match(r'\s*&&\s*%s\.active\)\s*size_mcemu_irx = size_%s;' % (infos, irx),
                                    code[close_paren(code, opening) + 1:]):
        found.append('%s: write `if (sbPatchVmcSpec(...) && %s.active) size_mcemu_irx = size_%s;`' % (line(call), infos, irx))
    sizes = sorted(m.group(1) for m in re.finditer(r'\bsize_mcemu_irx = (\w+)[;,]', body))
    if sizes != ['0', 'size_' + irx]:
        found.append('%s: size_mcemu_irx may only start at 0 and be set for a written, active slot (found %r)' %
                     (line(call), sizes))

    # ...and the launch hands mcemu that same IRX.
    launches = [start + m.start() for m in re.finditer(r'\bsysLaunchLoaderElf\(', body)]
    if not launches:
        found.append('%s: no sysLaunchLoaderElf in %s...)' % (path, signature))
    for pos in launches:
        given = arguments(code, pos + len('sysLaunchLoaderElf'))
        if given[4:6] != ['size_mcemu_irx', irx]:
            found.append('%s: sysLaunchLoaderElf must get size_mcemu_irx, %s (got %s)' % (line(pos), irx, ', '.join(given[4:6])))
    return found


def marker_failures(sources):
    """The marker is sbPatchVmcSpec's business alone: anything else that looks for it finds nothing after
    the first launch."""
    found = []
    for rel, source in sorted(sources.items()):
        if not re.search(r'0xC0DEFAC', source, re.I):
            continue
        code = blank(source)
        helper = re.search(r'^int sbPatchVmcSpec\([^;{]*\)\s*\{', code, re.M) if rel == 'src/supportbase.c' else None
        span = (helper.start(), code.index('\n}', helper.start())) if helper else (0, -1)
        for m in re.finditer(r'0xC0DEFAC', code, re.I):
            if not span[0] <= m.start() <= span[1]:
                found.append('%s:%d: looks for the mcemu marker itself -- go through sbPatchVmcSpec' %
                             (rel, source.count('\n', 0, m.start()) + 1))
    return found


SOURCES = {p.relative_to(root).as_posix(): text(p.relative_to(root).as_posix())
           for p in sorted(list((root / 'src').glob('*.c')) + list((root / 'include').glob('*.h')))}
support = SOURCES['src/supportbase.c']
helper = function(support, 'int sbPatchVmcSpec(')
if helper is None:
    failures.append('src/supportbase.c: int sbPatchVmcSpec(...) not found')
if 'int sbPatchVmcSpec(void *mcemu_irx, int size_mcemu_irx, int slot, const void *vmc_infos, int size_vmc_infos, int *specWord);' not in SOURCES['include/supportbase.h']:
    failures.append('include/supportbase.h: declare sbPatchVmcSpec for the legs')
for path, signature, irx, infos in LEGS:
    failures += leg_failures(path, SOURCES[path], signature, irx, infos)
failures += marker_failures(SOURCES)

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    if helper is not None:
        failures += helper_failures(helper, tmp, 'patch')

    # ---- each of these breaks the fix one way; every one of them has to be caught -----------------------
    if not failures:
        names = [re.search(r'(\w+)\s*$', p).group(1) for p in helper[helper.index('(') + 1:helper.index(')')].split(',')]
        size, slot, word = names[1], names[2], names[5]
        BROKEN_HELPER = (
            ('searches on every launch, as before', r'\{', '{\n    %s[%s] = -1;' % (word, slot)),
            ('counts the byte size in words', r'for \((\w+) = 0; [^;]+;', lambda m: 'for (%s = 0; %s < %s;' % (m[1], m[1], size)),
            ('ignores how much the slot needs', r'for \((\w+) = 0; [^;]+;',
             lambda m: 'for (%s = 0; (%s + 1) * (int)sizeof(u32) <= %s;' % (m[1], m[1], size)),
            ('looks for slot 0\'s marker for both slots', r'0xC0DEFAC0\s*\+\s*' + slot, '0xC0DEFAC0'),
            ('writes when the slot was not found', r'return 0;', ';'),
        )
        for k, (what, pattern, replacement) in enumerate(BROKEN_HELPER):
            broken, n = re.subn(pattern, replacement, helper, count=1)
            if n != 1:
                failures.append('mutation check: "%s" found nothing to change in sbPatchVmcSpec -- update this test' % what)
            elif not helper_failures(broken, tmp, 'broken%d' % k):
                failures.append('mutation check: sbPatchVmcSpec that %s passed' % what)

        OLD_LOOP = '''for (i = 0; i < size_bdm_mcemu_irx; i++) {
            if (((u32 *)&bdm_mcemu_irx)[i] == (0xC0DEFAC0 + vmc_id)) {
                if (bdm_vmc_infos.active)
                    size_mcemu_irx = size_bdm_mcemu_irx;
                memcpy(&((u32 *)&bdm_mcemu_irx)[i], &bdm_vmc_infos, sizeof(bdm_vmc_infos_t));
                break;
            }
        }'''
        BROKEN_LEG = (
            (0, 'the search that finds nothing after the first launch', r'if \(sbPatchVmcSpec\([^;]*;', lambda m: OLD_LOOP),
            (0, 'the word forgotten at every launch', r'(for \(vmc_id = 0; vmc_id < 2; vmc_id\+\+\) \{)',
             r'vmcSpecWord[0] = vmcSpecWord[1] = -1;\n    \1'),
            (1, 'the word kept on the stack', r'\bstatic (int vmcSpecWord\[2\])', r'\1'),
            (1, 'another leg\'s struct size', r'(sbPatchVmcSpec\([^;]*?)sizeof\(smb_vmc_infos_t\)', r'\1sizeof(bdm_vmc_infos_t)'),
            (1, 'a slot skipped', r'(\n\s*)(if \(sbPatchVmcSpec\()', r'\1if (!vmc_name[0])\1    continue;\1\2'),
            (1, 'the launch without the patched IRX', r'size_mcemu_irx, smb_mcemu_irx', '0, smb_mcemu_irx'),
            (2, 'another leg\'s IRX', r'&hdd_mcemu_irx, size_hdd_mcemu_irx', '&bdm_mcemu_irx, size_bdm_mcemu_irx'),
            (2, 'set-up slots only, as before', r'(if \(sbPatchVmcSpec\([^;]*;)', r'if (vmc_name[vmc_id][0]) {\n                \1\n            }'),
            (2, 'the active flag cleared only for a set-up slot', r'hdd_vmc_infos\.active = 0;\n(\s*if \(vmc_name\[vmc_id\]\[0\]\) \{)',
             r'\1\n                hdd_vmc_infos.active = 0;'),
            (3, 'mcemu loaded for an inactive slot', r' && mmce_vmc_infos\.active\)', ')'),
        )
        for leg, what, pattern, replacement in BROKEN_LEG:
            path, signature, irx, infos = LEGS[leg]
            broken, n = re.subn(pattern, replacement, SOURCES[path], count=1)
            if n != 1:
                failures.append('mutation check: "%s" found nothing to change in %s -- update this test' % (what, path))
                continue
            caught = leg_failures(path, broken, signature, irx, infos) + marker_failures(dict(SOURCES, **{path: broken}))
            if not caught:
                failures.append('mutation check: %s with %s passed' % (path, what))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('mcemu VMC slots: found once, written at the same place on every launch, both slots every time, '
      'never past the IRX; all 15 deliberate breaks caught')
