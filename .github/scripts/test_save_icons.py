"""3D Save Icons (fork-gaps OR1): the icon, icon.sys and memory-card-image readers, and their wiring.

Compiles the real src/saveicon.c (its pure half, -DSAVEICON_HOST_TEST) and checks it against an
independent Python reading of the icons this repository ships, against card images built here -- bare
and with the ECC spare, a fragmented icon chain, two saves of one game (the newer must win), damage
that must be refused rather than followed -- and against truncated and corrupted icons. Then checks
that the theme element, the setting and both built-in themes are wired as the feature needs.
"""
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
failures = []


def text(rel):
    return (root / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


# ---- an independent reading of the icon format ------------------------------------------------

def parse_icon(data):
    magic, shapes, textype, _, verts = struct.unpack_from('<IIIfI', data, 0)
    off, pos_sum, uv_sum, rgba_sum = 20, 0, 0, 0
    for _ in range(verts):
        for s in range(shapes):
            pos_sum += sum(struct.unpack_from('<hhh', data, off + 8 * s))
        off += 8 * shapes + 8
        uv_sum += sum(struct.unpack_from('<hh', data, off))
        off += 4
        rgba_sum += sum(data[off:off + 4])
        off += 4
    tag, frame_len, speed, _, frames = struct.unpack_from('<IIfII', data, off)
    off += 20
    for _ in range(frames):
        _, keys = struct.unpack_from('<II', data, off)
        off += 8 + 8 * keys
    tex_sum, end = None, off
    if textype & 4:
        pixels = []
        if textype & 8:
            packed, = struct.unpack_from('<I', data, off)
            end = off + 4 + packed
            src, i = data[off + 4:off + 4 + packed], 0
            while i + 2 <= len(src) and len(pixels) < 16384:
                code, = struct.unpack_from('<H', src, i)
                i += 2
                if code & 0x8000:
                    n = 0x10000 - code
                    pixels.extend(struct.unpack_from('<%dH' % n, src, i))
                    i += 2 * n
                else:
                    pixels.extend([struct.unpack_from('<H', src, i)[0]] * code)
                    i += 2
        else:
            pixels = list(struct.unpack_from('<16384H', data, off))
            end = off + 32768
        tex_sum = sum((pixels + [0] * 16384)[:16384])
    return {'shapes': shapes, 'verts': verts, 'pos': pos_sum, 'uv': uv_sum, 'rgba': rgba_sum,
            'tex': tex_sum, 'frame_len': frame_len, 'end': end}


def make_icon(shapes, verts, keys, textured=True):
    """A small synthetic icon: `verts` vertices, shape s offset by 100*s, per-shape key lists."""
    out = bytearray(struct.pack('<IIIfI', 0x00010000, shapes, 0x07 if textured else 0x03, 1.0, verts))
    for v in range(verts):
        for s in range(shapes):
            out += struct.pack('<hhhh', v * 10 + 100 * s, -v * 5, v, 0)
        out += struct.pack('<hhhh', 0, 0, -4096, 0)
        out += struct.pack('<hh', v * 64, v * 32)
        out += bytes([0x80, 0x40, 0x20, 0x80])
    out += struct.pack('<IIfII', 1, 60, 1.0, 0, len(keys))
    for shape, kl in keys:
        out += struct.pack('<II', shape, len(kl))
        for t, value in kl:
            out += struct.pack('<ff', t, value)
    if textured:
        out += struct.pack('<16384H', *[(i * 7) & 0xFFFF for i in range(16384)])
    return bytes(out)


# ---- memory-card images -------------------------------------------------------------------------

PAGE, PPC = 512, 2
CS = PAGE * PPC
CLUSTERS, ALLOC, IFC = 1024, 41, 8
FATS = [9, 10, 11, 12]  # 256 entries each: enough for the 983 allocatable clusters
DIR_MODE, FILE_MODE = 0x8027, 0x8017


class Card:
    def __init__(self):
        self.img = bytearray(b'\xFF' * (CLUSTERS * CS))
        self.fat = [0x7FFFFFFF] * (CLUSTERS - ALLOC)  # free
        self.used = set()
        sb = bytearray(0x154)
        sb[0:40] = b'Sony PS2 Memory Card Format 1.2.0.0\0\0\0\0\0'
        struct.pack_into('<HHHH', sb, 0x28, PAGE, PPC, 16, 0xFF00)
        struct.pack_into('<IIII', sb, 0x30, CLUSTERS, ALLOC, CLUSTERS - 1, 0)
        struct.pack_into('<I', sb, 0x50, IFC)
        self.img[0:len(sb)] = sb

    def alloc(self, count, pattern='contiguous'):
        free = [c for c in range(CLUSTERS - ALLOC) if c not in self.used]
        if pattern == 'fragmented':  # runs of two with gaps: exercises both coalescing and chain jumps
            picked = []
            for c in free:
                if len(picked) == count:
                    break
                if c % 4 in (1, 2):
                    picked.append(c)
        else:
            picked = free[:count]
        assert len(picked) == count
        self.used.update(picked)
        for a, b in zip(picked, picked[1:]):
            self.fat[a] = 0x80000000 | b
        self.fat[picked[-1]] = 0xFFFFFFFF
        return picked

    def write(self, data, pattern='contiguous'):
        clusters = self.alloc(max(1, (len(data) + CS - 1) // CS), pattern)
        for i, c in enumerate(clusters):
            chunk = data[i * CS:(i + 1) * CS]
            at = (ALLOC + c) * CS
            self.img[at:at + len(chunk)] = chunk
        return clusters[0]

    def finish(self):
        ifc = bytearray(CS)
        for i, f in enumerate(FATS):
            struct.pack_into('<I', ifc, 4 * i, f)
        self.img[IFC * CS:(IFC + 1) * CS] = ifc
        for i, f in enumerate(FATS):
            block = bytearray(CS)
            for k in range(256):
                n = i * 256 + k
                struct.pack_into('<I', block, 4 * k, self.fat[n] if n < len(self.fat) else 0x7FFFFFFF)
            self.img[f * CS:(f + 1) * CS] = block
        return bytes(self.img)


def entry(mode, length, cluster, name, stamp):
    sec, minute, hour, day, month, year = stamp
    e = bytearray(512)
    struct.pack_into('<HHI', e, 0, mode, 0, length)
    t = struct.pack('<BBBBBBH', 0, sec, minute, hour, day, month, year)
    e[0x08:0x10] = t
    struct.pack_into('<II', e, 0x10, cluster, 0)
    e[0x18:0x20] = t
    e[0x40:0x40 + len(name)] = name
    return bytes(e)


OLD, NEW = (1, 2, 3, 4, 5, 2019), (1, 2, 3, 4, 5, 2024)


def save_folder(card, name, sys_bytes, icon_bytes, stamp, icon_pattern='contiguous', extra=()):
    sys_cluster = card.write(sys_bytes)
    icon_cluster = card.write(icon_bytes, icon_pattern)
    files = [entry(FILE_MODE, len(sys_bytes), sys_cluster, b'icon.sys', stamp),
             entry(FILE_MODE, len(icon_bytes), icon_cluster, b'list.icn', stamp)] + list(extra)
    count = 2 + len(files)
    # A folder's "." entry needs its own cluster number, so lay out the entries after allocation.
    clusters = card.alloc((count * 512 + CS - 1) // CS)
    body = b''.join([entry(DIR_MODE, count, clusters[0], b'.', stamp),
                     entry(DIR_MODE, 0, 0, b'..', stamp)] + files)
    for i, c in enumerate(clusters):
        chunk = body[i * CS:(i + 1) * CS]
        at = (ALLOC + c) * CS
        card.img[at:at + len(chunk)] = chunk
    return entry(DIR_MODE, count, clusters[0], name, stamp)


def build_card(folders):
    """folders: entries for the root, made by save_folder. The root takes relative cluster 0."""
    card = Card()
    root_count = 2 + len(folders)
    root_clusters = card.alloc((root_count * 512 + CS - 1) // CS)
    assert root_clusters[0] == 0
    return card, root_clusters, root_count


def finish_root(card, root_clusters, root_count, folder_entries):
    body = b''.join([entry(DIR_MODE, root_count, 0, b'.', NEW), entry(DIR_MODE, 0, 0, b'..', NEW)] + folder_entries)
    for i, c in enumerate(root_clusters):
        chunk = body[i * CS:(i + 1) * CS]
        at = (ALLOC + c) * CS
        card.img[at:at + len(chunk)] = chunk
    return card.finish()


def with_ecc(bare):
    pages = len(bare) // PAGE
    out = bytearray()
    for p in range(pages):
        out += bare[p * PAGE:(p + 1) * PAGE] + bytes([p & 0xFF]) * 16
    return bytes(out)


HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/saveicon.h"

static int reads;

static unsigned char *slurp(const char *path, int *size)
{
    FILE *f = fopen(path, "rb");
    unsigned char *d;
    long n;
    if (f == NULL)
        return NULL;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    d = malloc(n > 0 ? n : 1);
    *size = (int)fread(d, 1, n, f);
    fclose(f);
    return d;
}

static int fileRead(void *ctx, unsigned int offset, void *buf, int size)
{
    reads++;
    if (fseek((FILE *)ctx, (long)offset, SEEK_SET) != 0)
        return -1;
    return (int)fread(buf, 1, size, (FILE *)ctx);
}

static void model(const char *path, int cut)
{
    int size, r, i;
    long long pos = 0, uv = 0, rgba = 0, tex = 0;
    unsigned char *d = slurp(path, &size);
    saveicon_model_t m;
    if (cut >= 0 && cut < size)
        size = cut;
    r = saveIconParseModel(d, size, &m);
    if (r != 0) {
        printf("ERR %d\n", r);
        free(d);
        return;
    }
    for (i = 0; i < m.shapes * m.verts * 3; i++)
        pos += m.pos[i];
    for (i = 0; i < m.verts * 2; i++)
        uv += m.uv[i];
    for (i = 0; i < m.verts * 4; i++)
        rgba += m.rgba[i];
    if (m.texels != NULL)
        for (i = 0; i < 128 * 128; i++)
            tex += m.texels[i];
    printf("OK shapes=%d verts=%d pos=%lld uv=%lld rgba=%lld tex=%lld frame_len=%d speed=%g\n", m.shapes, m.verts,
           pos, uv, rgba, m.texels != NULL ? tex : -1, m.frameLength, m.speed);
    saveIconFreeModel(&m);
    free(d);
}

static void sys(const char *path)
{
    int size;
    unsigned char *d = slurp(path, &size);
    char name[64];
    saveicon_light_t l;
    memset(&l, 0, sizeof(l));
    if (saveIconParseSys(d, size, name, sizeof(name), &l))
        printf("OK %s ambient=%.3f dir0=%.3f,%.3f,%.3f valid=%d\n", name, l.ambient[0], l.dir[0][0], l.dir[0][1], l.dir[0][2], l.valid);
    else
        printf("ERR\n");
    free(d);
}

static void card(const char *path, const char *serial)
{
    FILE *f = fopen(path, "rb");
    saveicon_model_t m;
    saveicon_light_t l;
    long size;
    int ok;
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    reads = 0;
    memset(&l, 0, sizeof(l));
    ok = saveIconFromCardImage(fileRead, f, (unsigned int)size, serial, &m, &l);
    if (ok)
        printf("FOUND verts=%d shapes=%d ambient=%.3f reads=%d\n", m.verts, m.shapes, l.ambient[0], reads);
    else
        printf("NONE reads=%d\n", reads);
    saveIconFreeModel(&m);
    fclose(f);
}

static void weights(void)
{
    saveicon_model_t m;
    saveicon_key_t k0[2] = {{0.0f, 1.0f}, {10.0f, 0.0f}}, k1[2] = {{0.0f, 0.0f}, {10.0f, 1.0f}};
    float w[4], t, sum;
    memset(&m, 0, sizeof(m));
    m.shapes = 2;
    m.keys[0] = k0;
    m.keys[1] = k1;
    m.keyCount[0] = m.keyCount[1] = 2;
    for (t = -1.0f; t <= 11.0f; t += 3.0f) {
        sum = saveIconShapeWeights(&m, t, w);
        printf("t=%.0f w0=%.2f w1=%.2f sum=%.2f\n", t, w[0], w[1], sum);
    }
    m.keyCount[0] = m.keyCount[1] = 0; // no keys at all: the first shape, never a collapsed model
    sum = saveIconShapeWeights(&m, 5.0f, w);
    printf("nokeys w0=%.2f w1=%.2f sum=%.2f\n", w[0], w[1], sum);
    m.shapes = 1; // one shape always has the full weight
    sum = saveIconShapeWeights(&m, 5.0f, w);
    printf("single w0=%.2f sum=%.2f\n", w[0], sum);
}

int main(int argc, char **argv)
{
    char serial[16];
    if (!strcmp(argv[1], "model"))
        model(argv[2], argc > 3 ? atoi(argv[3]) : -1);
    else if (!strcmp(argv[1], "sys"))
        sys(argv[2]);
    else if (!strcmp(argv[1], "card"))
        card(argv[2], argv[3]);
    else if (!strcmp(argv[1], "weights"))
        weights();
    else if (!strcmp(argv[1], "serial")) {
        int i;
        for (i = 2; i < argc; i++) {
            if (saveIconSerialForStartup(argv[i], serial, sizeof(serial)))
                printf("%s=%s\n", argv[i], serial);
            else
                printf("%s=-\n", argv[i]);
        }
    } else if (!strcmp(argv[1], "folder"))
        printf("%d\n", saveIconFolderMatches(argv[2], argv[3]));
    return 0;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'harness.c').write_text(HARNESS, encoding='utf-8')
    exe = tmp / 'harness'
    build = subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Werror', '-DSAVEICON_HOST_TEST', '-I', str(root),
                            '-o', str(exe), str(tmp / 'harness.c'), str(root / 'src/saveicon.c')],
                           capture_output=True, text=True, check=False)
    if build.returncode != 0:
        sys.exit('saveicon.c did not compile for the host test:\n' + build.stderr)

    def run(*args):
        return subprocess.run([str(exe)] + [str(a) for a in args], capture_output=True, text=True,
                              check=False, timeout=60).stdout.strip()

    # 1. The shipped icons parse exactly as the independent reading says.
    for rel in ('misc/list.icn', 'POPS/list.icn', 'POPS/del.icn'):
        data = (root / rel).read_bytes()
        ref = parse_icon(data)
        got = run('model', root / rel)
        want = 'OK shapes=%d verts=%d pos=%d uv=%d rgba=%d tex=%d frame_len=%d speed=1' % (
            ref['shapes'], ref['verts'], ref['pos'], ref['uv'], ref['rgba'], ref['tex'], ref['frame_len'])
        if got != want:
            failures.append('%s: parsed as %r, expected %r' % (rel, got, want))
        # Cut anywhere before the texture's last byte, an icon is refused; from there on it parses.
        cuts = set(range(0, 400, 7)) | set(range(400, len(data) + 1, max(1, len(data) // 47)))
        for cut in sorted(cuts | {ref['end'] - 1, ref['end']}):
            got = run('model', root / rel, cut)
            if not (got.startswith('ERR') or got.startswith('OK')):
                failures.append('%s cut at %d: crashed or printed %r' % (rel, cut, got))
            elif got.startswith('OK') != (cut >= ref['end']):
                failures.append('%s cut at %d (texture ends at %d): %r' % (rel, cut, ref['end'], got))

    # 2. Corrupted headers are refused before anything is allocated from them.
    base = bytearray((root / 'misc/list.icn').read_bytes())
    for label, offset, value in (('shapes 0', 4, 0), ('shapes 33', 4, 33), ('verts 0', 16, 0),
                                 ('verts not a triangle list', 16, 301), ('verts huge', 16, 0x7FFFFFF0),
                                 ('magic', 0, 0x00020000)):
        bad = bytearray(base)
        struct.pack_into('<I', bad, offset, value)
        (tmp / 'bad.icn').write_bytes(bad)
        if not run('model', tmp / 'bad.icn').startswith('ERR'):
            failures.append('a corrupted icon (%s) was accepted' % label)
    bad = bytearray(base)
    off = 20 + 300 * 24
    struct.pack_into('<I', bad, off + 16, 1)        # one frame...
    bad[off + 20:off + 28] = struct.pack('<II', 0, 0x7FFFFFFF)  # ...claiming 2^31 keys
    (tmp / 'bad.icn').write_bytes(bad[:off + 28])
    if not run('model', tmp / 'bad.icn').startswith('ERR'):
        failures.append('an icon claiming 2^31 animation keys was accepted')

    # 3. A morphing icon: two shapes, both keyed; untextured; speed honoured.
    (tmp / 'morph.icn').write_bytes(make_icon(2, 6, [(0, [(0.0, 1.0), (60.0, 0.0)]), (1, [(0.0, 0.0), (60.0, 1.0)]), (7, [(0.0, 1.0)])], textured=False))
    got = run('model', tmp / 'morph.icn')
    if not got.startswith('OK shapes=2 verts=6') or 'tex=-1' not in got:
        failures.append('two-shape untextured icon: %r' % got)
    got = run('weights').splitlines()
    want = ['t=-1 w0=1.00 w1=0.00 sum=1.00', 't=2 w0=0.80 w1=0.20 sum=1.00', 't=5 w0=0.50 w1=0.50 sum=1.00',
            't=8 w0=0.20 w1=0.80 sum=1.00', 't=11 w0=0.00 w1=1.00 sum=1.00', 'nokeys w0=1.00 w1=0.00 sum=1.00',
            'single w0=1.00 sum=1.00']
    if got != want:
        failures.append('shape weights: %r, expected %r' % (got, want))

    # 4. icon.sys: the list icon's name and the lights; unsafe names refused.
    got = run('sys', root / 'POPS/icon.sys')
    if not got.startswith('OK list.icn ambient=') or 'dir0=0.500,0.500,0.500 valid=1' not in got:
        failures.append('POPS/icon.sys: %r' % got)
    sysdata = bytearray((root / 'misc/icon.sys').read_bytes())
    for label, name in (('a path', b'../list.icn'), ('a separator', b'a/b.icn'), ('a device', b'mc0:x'),
                        ('nothing', b''), ('dot-dot', b'..'), ('no terminator', b'x' * 64)):
        bad = bytearray(sysdata)
        bad[0x104:0x144] = (name + b'\0' * 64)[:64]
        (tmp / 'bad.sys').write_bytes(bad)
        if run('sys', tmp / 'bad.sys') != 'ERR':
            failures.append('icon.sys naming %s as its list icon was accepted' % label)
    (tmp / 'short.sys').write_bytes(sysdata[:900])
    if run('sys', tmp / 'short.sys') != 'ERR':
        failures.append('a truncated icon.sys was accepted')

    # 5. Product codes and save folders.
    got = run('serial', 'SLUS_200.62', 'SCES_503.61', 'SLPM_123.45.Game.iso', 'SLUS-200.62', 'slus_200.62', 'SLUS_20A.62', 'SLUS_200.6')
    want = 'SLUS_200.62=SLUS-20062\nSCES_503.61=SCES-50361\nSLPM_123.45.Game.iso=SLPM-12345\nSLUS-200.62=-\nslus_200.62=-\nSLUS_20A.62=-\nSLUS_200.6=-'
    if got != want:
        failures.append('product codes: %r' % got)
    for folder, serial, want in (('BASLUS-20062GAME', 'SLUS-20062', '1'), ('BESLUS-20062', 'SLUS-20062', '1'),
                                 ('BASLUS-2006', 'SLUS-20062', '0'), ('XASLUS-20062', 'SLUS-20062', '0'),
                                 ('BASLUS-20063', 'SLUS-20062', '0')):
        if run('folder', folder, serial) != want:
            failures.append('folder %s for %s should be %s' % (folder, serial, want))

    # 6. Card images: the newer of two saves wins, through a fragmented chain, bare and with ECC.
    sys_bytes = (root / 'POPS/icon.sys').read_bytes()
    new_icon = (root / 'misc/list.icn').read_bytes()    # 300 vertices
    old_icon = (root / 'POPS/list.icn').read_bytes()    # 1044 vertices
    other = make_icon(1, 3, [])

    def standard_card(new_pattern='fragmented'):
        card, rc, count = build_card([None] * 4)
        folders = [save_folder(card, b'BASLUS-20062OLDSAVE', sys_bytes, old_icon, OLD),
                   save_folder(card, b'BESLES-99999OTHER', sys_bytes, other, NEW),
                   save_folder(card, b'BASLUS-20062NEWSAVE', sys_bytes, new_icon, NEW, new_pattern),
                   entry(FILE_MODE, 5, card.write(b'hello'), b'BASLUS-20062FILE', NEW)]  # a file, not a save
        return card, rc, count, folders

    card, rc, count, folders = standard_card()
    image = finish_root(card, rc, count, folders)
    (tmp / 'card.bin').write_bytes(image)
    got = run('card', tmp / 'card.bin', 'SLUS-20062')
    ambient = '%.3f' % struct.unpack_from('<f', sys_bytes, 0xB0)[0]
    if not got.startswith('FOUND verts=300 shapes=1 ambient=%s' % ambient):
        failures.append('bare card image: %r (the newer save, 300 vertices and its lights, should win)' % got)
    (tmp / 'ecc.bin').write_bytes(with_ecc(image))
    got = run('card', tmp / 'ecc.bin', 'SLUS-20062')
    if not got.startswith('FOUND verts=300 shapes=1'):
        failures.append('card image with the ECC spare: %r' % got)
    got = run('card', tmp / 'card.bin', 'SLES-99999')
    if not got.startswith('FOUND verts=3'):
        failures.append('second game on the same card: %r' % got)
    for serial in ('SLUS-20063', 'SCUS-97328'):
        if not run('card', tmp / 'card.bin', serial).startswith('NONE'):
            failures.append('a game with no save on the card found one (%s)' % serial)

    # A contiguous icon is read in one run, not cluster by cluster.
    card, rc, count, folders = standard_card('contiguous')
    (tmp / 'contig.bin').write_bytes(finish_root(card, rc, count, folders))
    got = run('card', tmp / 'contig.bin', 'SLUS-20062')
    contiguous = re.search(r'reads=(\d+)', got)
    fragmented = re.search(r'reads=(\d+)', run('card', tmp / 'card.bin', 'SLUS-20062'))
    if (not got.startswith('FOUND verts=300') or contiguous is None or fragmented is None or
            int(contiguous.group(1)) > 20 or int(contiguous.group(1)) + 4 > int(fragmented.group(1))):
        failures.append('contiguous icon on a bare image: %r (expected one run, fewer reads than the fragmented card)' % got)

    # 7. Damage is refused, never followed.
    def damaged(mutate):
        card, rc, count, folders = standard_card()
        mutate(card)
        return finish_root(card, rc, count, folders)

    cases = {
        'wrong magic': lambda img: b'Not a card' + img[10:],
        'too small for its clusters': lambda img: img[:len(img) // 2],
    }
    for label, mutate in cases.items():
        (tmp / 'bad.bin').write_bytes(mutate(image))
        if not run('card', tmp / 'bad.bin', 'SLUS-20062').startswith('NONE'):
            failures.append('a damaged card image (%s) was read' % label)

    def free_mid_chain(card):
        # The first link that jumps (the fragmented icon's): the cluster it jumps to becomes free.
        jump = next(c for c in sorted(card.used) if card.fat[c] != 0xFFFFFFFF and (card.fat[c] & 0x7FFFFFFF) != c + 1)
        card.fat[card.fat[jump] & 0x7FFFFFFF] = 0x7FFFFFFF
    (tmp / 'bad.bin').write_bytes(damaged(free_mid_chain))
    got = run('card', tmp / 'bad.bin', 'SLUS-20062')
    if not (got.startswith('NONE') or got.startswith('FOUND verts=1044')):
        failures.append('a chain running into a free cluster: %r' % got)

    big = bytearray(image)
    struct.pack_into('<I', big, ALLOC * CS + 4, 0x7FFFFFFF)  # root "." claims 2^31 entries
    (tmp / 'bad.bin').write_bytes(big)
    if not run('card', tmp / 'bad.bin', 'SLUS-20062').startswith('NONE'):
        failures.append('a root claiming 2^31 entries was walked')

    loop = bytearray(image)
    for i in range(256):  # every FAT link points back at itself: walks must end, not spin
        struct.pack_into('<I', loop, FATS[0] * CS + 4 * i, 0x80000000 | i)
    (tmp / 'loop.bin').write_bytes(loop)
    try:
        run('card', tmp / 'loop.bin', 'SLUS-20062')
    except subprocess.TimeoutExpired:
        failures.append('a looping FAT chain hung the reader')

# ---- the wiring --------------------------------------------------------------------------------

themes = text('src/themes.c')
if '"SaveIcon"' not in themes or 'ELEM_TYPE_SAVE_ICON' not in themes:
    failures.append('themes.c: the SaveIcon element type is not declared')
init = themes[themes.index('elementsType[ELEM_TYPE_SAVE_ICON], type'):][:400]
if 'needsSaveIconConfig = 1' not in init or 'drawSaveIcon' not in init:
    failures.append('themes.c: SaveIcon must ask for its per-game config and draw with drawSaveIcon')
draw = themes[themes.index('static void drawSaveIcon('):]
draw = draw[:draw.index('\n}\n')]
for needle, why in (('gEnableSaveIcons', 'the setting must gate the element'),
                    ('libListRowView(support, item->item.id) != LIB_VIEW_ISO', 'exclude non-game rows from PS2 save lookup'),
                    ('APP_MODE', 'apps have no saves'),
                    ('configGetVMCDisable', 'a slot switched off is not where the save is'),
                    ('favGetItemPrefix', "a favourite's VMC is on its source device"),
                    ('saveIconSelect(', 'the selection must reach the loader'),
                    ('saveIconDraw(', 'the icon must be drawn')):
    if needle not in draw:
        failures.append('themes.c drawSaveIcon: %s (%s missing)' % (why, needle))

menusys = text('src/menusys.c')
if '(elems->needsItemConfig || (elems->needsSaveIconConfig && gEnableSaveIcons))' not in menusys:
    failures.append('menusys.c: the per-game config must be fetched for SaveIcon only while the setting is on')

opl = text('src/opl.c')
if not re.search(r'gEnableSaveIcons = 0;', opl):
    failures.append('opl.c setDefaults: 3D Save Icons must default to off until it has run on hardware')
for needle in ('configGetInt(configOPL, CONFIG_OPL_ENABLE_SAVE_ICONS, &gEnableSaveIcons)',
               'configSetInt(configOPL, CONFIG_OPL_ENABLE_SAVE_ICONS, gEnableSaveIcons)'):
    if needle not in opl:
        failures.append('opl.c: %s missing' % needle)
gui = text('src/gui.c')
if 'UICFG_ENABLE_SAVE_ICONS, &gEnableSaveIcons' not in gui or 'saveIconReset()' not in gui:
    failures.append('gui.c: Artwork Settings must read the setting back and free the icon when it is switched off')
if 'saveicon.o' not in text('Makefile'):
    failures.append('Makefile: saveicon.o is not built')

for rel, families in (('misc/conf_theme_OPL.cfg', ('main', 'info')), ('misc/theme_coverflow.cfg', ('main', 'info'))):
    cfg = text(rel)
    for family in families:
        if not re.search(r'^%s\d+:\n\ttype=SaveIcon$' % family, cfg, re.M):
            failures.append('%s: no SaveIcon in the %s family' % (rel, family))

# Language labels are append-only: these two come after every label that existed before them.
base = text('lng_tmpl/_base.yml')
older, ours = base.find('- label: HINT_NARGS_EXTRA\n'), base.find('- label: SAVE_ICONS\n')
if older < 0 or ours < older or '- label: HINT_SAVE_ICONS\n' not in base[ours:]:
    failures.append('lng_tmpl/_base.yml: SAVE_ICONS and HINT_SAVE_ICONS must be appended after the existing labels')

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('save icons: OK')
