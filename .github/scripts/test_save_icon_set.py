#!/usr/bin/env python3
"""The settings folder's memory-card icon (#314): the committed art is well formed and RiptOPL's, and
the real stamping code in src/util.c writes it once, never over somebody else's icon,
restamps only our own pre-#314 artwork, and never latches a half-written set."""
from pathlib import Path
import struct
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
icon_sys = (root / 'misc/icon.sys').read_bytes()
icn = (root / 'misc/list.icn').read_bytes()

# --- The assets -------------------------------------------------------------------------------
assert len(icon_sys) == 964 and icon_sys[:4] == b'PS2D', 'icon.sys header'
brk = struct.unpack_from('<H', icon_sys, 6)[0]
title = icon_sys[0xC0:0xC0 + 68].rstrip(b'\0')
assert title[:brk].decode('shift_jis') == 'ＲｉｐｔＯＰＬ', title
assert title[brk:].decode('shift_jis') == 'Ｏｐｅｎ　ＰＳ２　Ｌｏａｄｅｒ', title
names = [icon_sys[o:o + 64].split(b'\0')[0] for o in (0x104, 0x144, 0x184)]
assert names == [b'list.icn', b'copy.icn', b'del.icn'], names

magic, shapes, ttype, _, nv = struct.unpack_from('<IIIfI', icn, 0)
assert magic == 0x010000 and shapes == 1 and ttype & 8 and nv and nv % 3 == 0, (magic, shapes, ttype, nv)
off = 20 + nv * (shapes * 8 + 16)
frames = struct.unpack_from('<IIfII', icn, off)[4]
off += 20
for _ in range(frames):
    off += 8 + 8 * struct.unpack_from('<2I', icn, off)[1]
size = struct.unpack_from('<I', icn, off)[0]
off += 4
end, pixels = off + size, 0
while off < end:
    code = struct.unpack_from('<H', icn, off)[0]
    if code & 0x8000:
        pixels += 0x10000 - code
        off += 2 + 2 * (0x10000 - code)
    else:
        pixels += code
        off += 4
assert off == end == len(icn) and pixels == 128 * 128, (off, end, len(icn), pixels)
for i in range(nv):
    u, v = struct.unpack_from('<2h', icn, 20 + i * (shapes * 8 + 16) + shapes * 8 + 8)
    assert 0 <= u <= 4096 and 0 <= v <= 4096, (i, u, v)

# --- The stamping code, extracted verbatim and run against a real directory --------------------
source = (root / 'src/util.c').read_text(encoding='utf-8')
names_decl = source[source.index('static const char *const saveIconName'):]
names_decl = names_decl[:names_decl.index(';') + 1]
size_fn = source[source.index('int getFileSize(int fd)'):]
size_fn = size_fn[:size_fn.index('\n}') + 2]
start = source.index('static int buildIconPath(')
body = source[start:source.index('// Ensure mc?:OPL/ exists', start)]


def carray(name, data):
    return 'unsigned char %s[] = {%s};\nunsigned int size_%s = %d;\n' % (
        name, ','.join(str(b) for b in data), name, len(data))


old_icon_sys = bytearray(icon_sys)
old_title = 'ＲｉｐｔＯＰＬＯｐｅｎＰＳ２Ｌｏａｄｅｒ'
old_icon_sys[0xC0:0xC0 + 68] = old_title.encode('shift_jis').ljust(68, b'\0')

program = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
static int writeBudget = -1; // bytes the "card" still takes; -1 = unlimited
static long realWrite(int fd, const void *p, unsigned long n) { return ::write(fd, p, n); }
static long cardWrite(int fd, const void *p, unsigned long n) {
    if (writeBudget >= 0 && (long)n > writeBudget) n = writeBudget;
    long w = realWrite(fd, p, n);
    if (writeBudget >= 0) writeBudget -= (int)w;
    return w;
}
#define write cardWrite
''' + carray('icon_sys', icon_sys) + carray('save_icn', icn) + carray('old_sys', old_icon_sys) + \
    names_decl + '\n' + size_fn + '\n' + body + r'''
#undef write
static std::string D;
static std::string slurp(const char *name) {
    std::string s; FILE *f = fopen((D + "/" + name).c_str(), "rb");
    if (!f) return "<missing>";
    char b[4096]; size_t n;
    while ((n = fread(b, 1, sizeof(b), f)) > 0) s.append(b, n);
    fclose(f); return s;
}
static void put(const char *name, const void *p, size_t n) {
    FILE *f = fopen((D + "/" + name).c_str(), "wb"); fwrite(p, 1, n, f); fclose(f);
}
static bool isSet() {
    std::string icn((const char *)save_icn, size_save_icn);
    return slurp("icon.sys") == std::string((const char *)icon_sys, size_icon_sys) &&
           slurp("list.icn") == icn && slurp("copy.icn") == icn && slurp("del.icn") == icn;
}
static void wipe() { for (const char *n : {"icon.sys", "list.icn", "copy.icn", "del.icn", "settings.cfg"}) unlink((D + "/" + n).c_str()); }
int main(int, char **argv) {
    D = argv[1];
    // checkMCSaveIcons only acts on memory cards; aim it at the test directory through writeSaveIconSet.
    assert(slurp("icon.sys") == "<missing>");
    writeSaveIconSet(D.c_str());
    assert(isSet());
    // Second save: nothing rewritten (a marker in list.icn survives).
    put("list.icn", "X", 1);
    writeSaveIconSet(D.c_str());
    assert(slurp("list.icn") == "X");
    // Somebody else's icon.sys (as long as ours, other title) is never touched, nor its files.
    wipe();
    std::string foreign(964, 'F'); memcpy(&foreign[0], "PS2D", 4);
    put("icon.sys", foreign.data(), foreign.size());
    writeSaveIconSet(D.c_str());
    assert(slurp("icon.sys") == foreign && slurp("list.icn") == "<missing>");
    // Our own pre-#314 stamp is restamped once, then left alone.
    wipe();
    put("icon.sys", old_sys, size_old_sys); put("list.icn", "APP", 3);
    writeSaveIconSet(D.c_str());
    assert(isSet());
    put("list.icn", "X", 1);
    writeSaveIconSet(D.c_str());
    assert(slurp("list.icn") == "X");
    // A short icon.sys (card filled mid-stamp) is restamped.
    wipe();
    put("icon.sys", "PS2D", 4);
    writeSaveIconSet(D.c_str());
    assert(isSet());
    // Card fills during the second .icn: icon.sys must not appear, and the next save completes the set.
    wipe();
    writeBudget = (int)size_save_icn + 100;
    writeSaveIconSet(D.c_str());
    assert(slurp("icon.sys") == "<missing>");
    writeBudget = -1;
    writeSaveIconSet(D.c_str());
    assert(isSet());
    // The card root and non-card paths are ignored; a folder path stamps that folder.
    wipe();
    checkMCSaveIcons("mass0:/OPL/conf_opl.cfg");
    checkMCSaveIcons("mmce1:/OPL/conf_opl.cfg");
    checkMCSaveIcons("mc0:conf_opl.cfg");
    checkMCSaveIcons(NULL);
    assert(slurp("icon.sys") == "<missing>");
    puts("save icon set: assets, first stamp, no rewrite, foreign icon kept, old stamp upgraded once, "
         "short icon.sys, full card and non-card paths passed");
}
'''
with tempfile.TemporaryDirectory() as temp:
    cpp = Path(temp) / 'saveicon.cpp'
    exe = Path(temp) / 'saveicon'
    card = Path(temp) / 'card'
    card.mkdir()
    cpp.write_text(program, encoding='utf-8')
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe), str(card)], check=True, timeout=30)
