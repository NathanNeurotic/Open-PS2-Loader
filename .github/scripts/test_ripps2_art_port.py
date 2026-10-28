"""Game art ported from RIPPS2 (akilluminati47/RIPPS2, builds 95/115/118).

1. The art index keeps the pictures' real names, so findPicture answers for any letter case and for .png,
   .jpg and .jpeg (a .png wins), and hands back the name the device lists (PFS minds case).
2. texArtAlias maps OPL Manager's names (_BG_00, _SCR_00, _SCR_01) to OPL's (_BG, _SCR, _SCR2) and back,
   and only inside an ART folder.
3. Art lookups go through texDiscoverArt -> texFindArt (index first, then <stem>.png, .jpg and .jpeg) and then the alias; the
   ART .tar tries the alias too and decodes JPG members.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
tex = (root / 'src/textures.c').read_text()


def function(source, signature):
    pos = source.index(signature)
    start = source.index('{', pos)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[pos:i + 1]
    raise AssertionError('unterminated ' + signature)


with tempfile.TemporaryDirectory(prefix='ripps2-art-') as temp:
    t = Path(temp)
    (t / 'include').mkdir()
    shutil.copy(root / 'include/artindex.h', t / 'include/artindex.h')
    (t / 'include/opl.h').write_text('')
    (t / 'include/ioman.h').write_text('#define LOG(...) ((void)0)\n')
    (t / 'kernel.h').write_text('static inline int GetThreadId(void) { return 7; }\n')
    art = t / 'ART'
    art.mkdir()
    for name in ('Slus_123.45_cov.JPG', 'SLUS_999.99_COV.jpg', 'SLUS_999.99_COV.png', 'SLES_500.00_BG_00.jpeg',
                 'SCUS_111.11_COV.txt', 'SCUS_222.22_COV.png.bak', 'readme.txt'):
        (art / name).write_text('x')
    (t / 'main.c').write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "include/artindex.h"
int main(void) {
    char out[256];
    artIndexSetOwnerThread(7);
    assert(artIndexFindPicture("ART/SLUS_123.45_COV", out, sizeof(out)) == 1 && !strcmp(out, "ART/Slus_123.45_cov.JPG"));
    assert(artIndexFindPicture("ART/SLUS_999.99_COV", out, sizeof(out)) == 1 && !strcmp(out, "ART/SLUS_999.99_COV.png"));
    assert(artIndexFindPicture("ART/sles_500.00_bg_00", out, sizeof(out)) == 1 && !strcmp(out, "ART/SLES_500.00_BG_00.jpeg"));
    assert(artIndexFindPicture("ART/SCUS_111.11_COV", out, sizeof(out)) == 0);  /* not a picture */
    assert(artIndexFindPicture("ART/SCUS_222.22_COV", out, sizeof(out)) == 0);  /* .png.bak is not .png */
    assert(artIndexFindPicture("ART/SLUS_000.00_COV", out, sizeof(out)) == 0);  /* absent, from RAM */
    assert(artIndexMayExist("ART/slus_999.99_cov.JPG") == 1);                   /* the hash index still answers */
    assert(artIndexFindPicture("smb0:ART/SLUS_123.45_COV", out, sizeof(out)) == -1);
    assert(artIndexFindPicture("udpfs:ART/SLUS_123.45_COV", out, sizeof(out)) == -1);
    assert(artIndexFindPicture("NOPE/SLUS_123.45_COV", out, sizeof(out)) == -1); /* cannot list: don't know */
    artIndexSetOwnerThread(8);
    assert(artIndexFindPicture("ART/SLUS_123.45_COV", out, sizeof(out)) == -1); /* wrong thread */
    return 0;
}
''')
    exe = t / 'artindex.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-I', str(t), str(t / 'main.c'),
                    str(root / 'src/artindex.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], cwd=temp, check=True)
print('ok   art index: any letter case, .png/.jpg/.jpeg, real name returned, absent answered from RAM')

alias = function(tex, 'int texArtAlias(')
with tempfile.TemporaryDirectory(prefix='ripps2-alias-') as temp:
    src = Path(temp) / 'alias.c'
    src.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
''' + alias + r'''
static const char *a(const char *stem) { static char out[256]; return texArtAlias(stem, out, sizeof(out)) ? out : ""; }
int main(void) {
    assert(!strcmp(a("mass0:ART/SLUS_123.45_BG"), "mass0:ART/SLUS_123.45_BG_00"));
    assert(!strcmp(a("mass0:ART/SLUS_123.45_BG_00"), "mass0:ART/SLUS_123.45_BG"));
    assert(!strcmp(a("pfs0:ART/SLUS_123.45_SCR"), "pfs0:ART/SLUS_123.45_SCR_00"));
    assert(!strcmp(a("pfs0:ART/SLUS_123.45_SCR2"), "pfs0:ART/SLUS_123.45_SCR_01"));
    assert(!strcmp(a("pfs0:ART/SLUS_123.45_SCR_01"), "pfs0:ART/SLUS_123.45_SCR2"));
    assert(!strcmp(a("smb0:ART\\SLUS_123.45_SCR"), "smb0:ART\\SLUS_123.45_SCR_00"));
    assert(!strcmp(a("ART/SLUS_123.45_SCR"), "ART/SLUS_123.45_SCR_00"));
    assert(!strcmp(a("mass0:ART/SLUS_123.45_COV"), ""));             /* covers have one name */
    assert(!strcmp(a("mass0:THM/mytheme/SLUS_123.45_BG"), ""));      /* theme files keep theirs */
    assert(!strcmp(a("mass0:CART/SLUS_123.45_BG"), ""));             /* CART is not ART */
    return 0;
}
''')
    exe = Path(temp) / 'alias.exe'
    subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('ok   OPL Manager names: _BG <-> _BG_00, _SCR <-> _SCR_00, _SCR2 <-> _SCR_01, ART folders only')

discover = function(tex, 'int texDiscoverArt(')
assert discover.index('texFindArt(texture, path)') < discover.index('texArtAlias(path'), 'alias must come after the asked-for name'
find = function(tex, 'static int texFindArt(')
assert 'artIndexFindPicture(' in find and '"png", "jpg", "jpeg"' in find, 'texFindArt must use the index, then probe .png, .jpg and .jpeg'
# Theme images keep one .png probe: only game art looks for JPGs (CodeRabbit on #1084).
theme_load = function(tex, 'int texDiscoverLoad(')
assert 'texFindArt(' not in theme_load and '"%s.%s", path, "png"' in theme_load, 'theme images must keep the single .png probe'
for f in ('hddsupport.c', 'udpfssupport.c', 'bdmsupport.c', 'ethsupport.c', 'mmcesupport.c', 'appsupport.c', 'httpsupport.c'):
    body = (root / 'src' / f).read_text()
    assert 'texDiscoverArt(resultTex, path)' in body and 'texDiscoverLoad(resultTex, path, -1)' not in body, f + ' must load game art through texDiscoverArt'
art_file = function(tex, 'static int texLoadArtFile(')
for code in ('ERR_BAD_FILE', 'ERR_FILE_IO', 'ERR_LOAD_ABORTED'):
    assert code in art_file, code + ' must not be retried as a JPG'
jpg = function(tex, 'static int texLoadJpgMemory(')
assert 'scale_denom' in jpg and 'texLoadAbortRequested()' in jpg and 'GS_PSM_CT24' in jpg
artload = (root / 'src/texcache.c').read_text()
piece = function(artload, 'static TarEntryBase *artTarFindPiece(')
assert 'texArtAlias(' in piece, 'the ART .tar must try OPL Manager names too'
assert 'texLoadArtFromMemory(' in function(artload, 'static int artTarDecode('), 'the ART .tar must decode JPG members'
for build_file, needle in (('Makefile', '-ljpeg'),):
    assert needle in (root / build_file).read_text(), build_file + ' must link libjpeg'
print('ok   art lookup order, JPG fallback rules, .tar alias + JPG, libjpeg linked')

# The JPG decoder itself, compiled against the host's libjpeg when the runner has it (headers + Pillow to make
# the pictures). Skipped, and said so, when it does not.
probe = subprocess.run(['cc', '-x', 'c', '-fsyntax-only', '-'], input='#include <stdio.h>\n#include <jpeglib.h>\n',
                       text=True, capture_output=True)
try:
    from PIL import Image
except ImportError:
    Image = None
if probe.returncode != 0 or Image is None:
    print('skip JPG decode: host has no libjpeg headers or Pillow')
else:
    block = tex[tex.index('#define TEX_ART_MAX_W'):tex.index('// A whole art file read into RAM')]
    with tempfile.TemporaryDirectory(prefix='ripps2-jpg-') as temp:
        t = Path(temp)
        pics = {
            'cover.jpg': ((140, 200), 'RGB', {}),
            'prog.jpg': ((512, 725), 'RGB', {'progressive': True}),
            'gray.jpg': ((300, 300), 'L', {}),
            'huge.jpg': ((3000, 2000), 'RGB', {}),
            'odd.jpg': ((1100, 1500), 'RGB', {}),
        }
        for name, (size, mode, opts) in pics.items():
            img = Image.new(mode, size, 200 if mode == 'L' else (200, 40, 40))
            img.save(t / name, 'JPEG', quality=95, **opts)
        (t / 'notjpg.jpg').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 64)
        (t / 'trunc.jpg').write_bytes((t / 'cover.jpg').read_bytes()[:300])
        (t / 'jpg.c').write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
#include <setjmp.h>
#include <jpeglib.h>
typedef unsigned char u8; typedef unsigned int u32;
typedef struct { int Width, Height, PSM; u32 *Mem; void *Clut; } GSTEXTURE;
#define GS_PSM_CT24 1
#define ERR_SET_JMP -4
#define ERR_LOAD_ABORTED -8
static int aborted;
static int texLoadAbortRequested(void) { return aborted; }
static void texPrepare(GSTEXTURE *t) { memset(t, 0, sizeof(*t)); }
static void texFree(GSTEXTURE *t) { free(t->Mem); t->Mem = NULL; }
static int texSizeValidate(int w, int h, int psm) { (void)psm; return (w > 1024 || h > 1024 || w * h * 4 > 720 * 512 * 4) ? -1 : 0; }
static size_t gsKit_texture_size_ee(int w, int h, int psm) { (void)psm; return (size_t)w * h * 3; }
''' + block + r'''
static void *slurp(const char *n, u32 *size) { FILE *f = fopen(n, "rb"); fseek(f, 0, SEEK_END); *size = ftell(f); rewind(f);
    void *b = malloc(*size); assert(fread(b, 1, *size, f) == *size); fclose(f); return b; }
static int dec(const char *n, int bg, GSTEXTURE *t) { u32 s; void *b = slurp(n, &s);
    int r = texLoadJpgMemory(t, b, s, bg ? TEX_BG_MAX_W : TEX_ART_MAX_W, bg ? TEX_BG_MAX_H : TEX_ART_MAX_H); free(b); return r; }
static int red(GSTEXTURE *t, int x, int y) { return ((u8 *)t->Mem)[(y * t->Width + x) * 3]; }
int main(void) {
    GSTEXTURE t;
    assert(dec("cover.jpg", 0, &t) == 0 && t.Width == 140 && t.Height == 200 && t.PSM == GS_PSM_CT24 && red(&t, 70, 100) > 180); texFree(&t);
    assert(dec("prog.jpg", 0, &t) == 0 && t.Height == 512 && t.Width <= 512 && t.Width >= 360); texFree(&t);
    assert(dec("gray.jpg", 0, &t) == 0 && t.Width == 300 && red(&t, 10, 10) > 180); texFree(&t);
    assert(dec("huge.jpg", 1, &t) == 0 && t.Width == 720 && t.Height == 480); texFree(&t);
    assert(dec("huge.jpg", 0, &t) == 0 && t.Width == 512 && t.Height <= 512); texFree(&t);
    assert(dec("odd.jpg", 0, &t) == 0 && t.Height == 512 && t.Width == 375 && red(&t, t.Width - 1, t.Height - 1) > 180); texFree(&t);
    assert(dec("notjpg.jpg", 0, &t) == ERR_SET_JMP && t.Mem == NULL);
    int r = dec("trunc.jpg", 0, &t); assert(r == ERR_SET_JMP || r == 0); texFree(&t); /* libjpeg pads a short file */
    aborted = 1; assert(dec("prog.jpg", 0, &t) == ERR_LOAD_ABORTED && t.Mem == NULL);
    return 0;
}
''')
        exe = t / 'jpg.exe'
        subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', str(t / 'jpg.c'), '-ljpeg', '-o', str(exe)], check=True)
        subprocess.run([str(exe)], cwd=temp, check=True)
    print('ok   JPG decode: baseline, progressive, grayscale, shrunk to its box, refuses non-JPG, abort frees')
