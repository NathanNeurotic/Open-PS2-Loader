"""pc/apa-recovery/apa_recover.py against synthetic APA disk images.

Each scenario builds a small sparse APA image (a real __mbr, system partitions, PFS partitions and
an HDL game with a sub-partition, all linked the way ps2sdk links them), damages it the way a disk
can be damaged, and runs the tool. A rebuilt __mbr must pass three independent checks: the IOP
driver's own write fence (modules/hdd/apa/src/table_fence.h, compiled here), ps2hdd's apaGetFormat
rules, and the __mbr password computed by ps2sdk's own DES routine (password.c, compiled here). And
the tool must never change a byte outside LBA 0-7.
"""
from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import os
import struct
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('apa_recover', root / 'pc/apa-recovery/apa_recover.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

SECTOR = 512
MAGIC = 0x00415041
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def seal(raw):
    words = struct.unpack_from('<256I', raw, 0)
    struct.pack_into('<I', raw, 0, sum(words[1:]) & 0xFFFFFFFF)


def header(start, length, nxt, prev, ident, kind, flags=0, subs=(), main=0, number=0):
    raw = bytearray(1024)
    struct.pack_into('<4I', raw, 0, 0, MAGIC, nxt, prev)
    raw[0x10:0x10 + len(ident)] = ident.encode()
    struct.pack_into('<IIHHI', raw, 0x40, start, length, kind, flags, len(subs))
    struct.pack_into('<II', raw, 0x58, main, number)
    for i, (s, l) in enumerate(subs):
        struct.pack_into('<II', raw, 0x200 + 8 * i, s, l)
    seal(raw)
    return raw


def build_image(path, password):
    """__mbr (128 MB) followed by eight 8 MB partitions, tiled and doubly linked, then free space."""
    layout = [('__net', 0x0100, 0, 0), ('__system', 0x0100, 0, 0), ('__sysconf', 0x0100, 0, 0),
              ('__common', 0x0100, 0, 0), ('+OPL', 0x0100, 0, 0), ('PP.SLUS-20002.POPS.GAME', 0x0100, 0, 0),
              ('PP.SLUS-20001..GAME', 0x1337, 0, 0), ('', 0x1337, 1, 1)]
    part = 0x4000
    starts = [0x40000 + i * part for i in range(len(layout))]
    total = starts[-1] + part + 0x8000
    with open(path, 'wb') as f:
        f.truncate(total * SECTOR)
        mbr = bytearray(1024)
        struct.pack_into('<4I', mbr, 0, 0, MAGIC, starts[0], starts[-1])
        mbr[0x10:0x15] = b'__mbr'
        mbr[0x30:0x38] = password
        mbr[0x38:0x40] = password
        struct.pack_into('<IIHHI', mbr, 0x40, 0, 0x40000, 0x0001, 0, 0)
        mbr[0x100:0x120] = b'Sony Computer Entertainment Inc.'
        struct.pack_into('<II', mbr, 0x120, 2, 0)
        struct.pack_into('<II', mbr, 0x130, 0x200, 0x1000)  # an installed HDD-OSD boot area
        seal(mbr)
        f.seek(0)
        f.write(mbr)
        for i, (ident, kind, flags, number) in enumerate(layout):
            nxt = starts[i + 1] if i + 1 < len(starts) else 0
            prev = starts[i - 1] if i > 0 else 0
            subs = [(starts[7], part)] if ident == 'PP.SLUS-20001..GAME' else ()
            main = starts[6] if flags else 0
            f.seek(starts[i] * SECTOR)
            f.write(header(starts[i], part, nxt, prev, ident, kind, flags, subs, main, number))
        # Markers just outside the table sector, which the tool must never touch.
        f.seek(8 * SECTOR)
        f.write(struct.pack('<II', 0x4150414C, 0) + b'journal-marker')
        f.seek(0x2000 * SECTOR)
        f.write(b'data-marker')
    return starts, total


def read(path, lba, count):
    with open(path, 'rb') as f:
        f.seek(lba * SECTOR)
        return f.read(count * SECTOR)


def write(path, lba, data):
    with open(path, 'r+b') as f:
        f.seek(lba * SECTOR)
        f.write(data)


def digest_outside_table(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        f.seek(8 * SECTOR)
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def digest_all(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_tool(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tool.main([str(a) for a in argv])
    return code, out.getvalue()


def compile_helpers(tmp):
    fence = Path(tmp) / 'fence_check.c'
    fence.write_text(r'''
#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32;
#include "table_fence.h"
int main(int argc, char **argv)
{
    unsigned char hdr[1024];
    unsigned long total = strtoul(argv[2], 0, 0);
    FILE *f = fopen(argv[1], "rb");
    if (f == NULL || fread(hdr, 1, sizeof(hdr), f) != sizeof(hdr))
        return 2;
    fclose(f);
    (void)argc;
    return apaFenceWriteAllowed(0, 2, hdr, (u32)total) ? 0 : 1;
}
'''.replace('#include <stdio.h>', '#include <stdio.h>\n#include <stdlib.h>'))
    fence_exe = Path(tmp) / 'fence_check'
    subprocess.run(['cc', '-std=c99', '-Wall', '-Werror', '-I', str(root / 'modules/hdd/apa/src'),
                    str(fence), '-o', str(fence_exe)], check=True)

    source = (root / 'modules/hdd/apa/src/password.c').read_text().replace('\r\n', '\n')
    wrapper_start = source.index('void apaEncryptPassword(')
    wrapper_end = source.index('\n}\n', wrapper_start) + 3
    des_start = source.index('struct KeyPair')
    des_def = source.index('static void DESEncryptPassword(u32 id_lo, u32 id_hi, char *password_out, const char *password)\n{')
    des_end = source.index('\n}\n', des_def) + 3
    pw = Path(tmp) / 'password.c'
    pw.write_text('#include <stdio.h>\n#include <string.h>\n#include <stdint.h>\n'
                  'typedef uint8_t u8;\ntypedef uint32_t u32;\ntypedef int32_t s32;\n#define APA_PASSMAX 8\n'
                  'static void DESEncryptPassword(u32 id_lo, u32 id_hi, char *password_out, const char *password);\n' +
                  source[wrapper_start:wrapper_end] + source[des_start:des_end] + r'''
int main(void)
{
    char id[32] = "__mbr", pw[8] = "sce_mbr", out[8];
    apaEncryptPassword(id, out, pw);
    fwrite(out, 1, 8, stdout);
    return 0;
}
''')
    pw_exe = Path(tmp) / 'password'
    # -O0: the SDK routine shifts by negative amounts; optimizers are free to fold that differently
    # from the IOP's runtime shifts. At -O0 it matches standard DES (checked when this was written).
    subprocess.run(['cc', '-O0', '-std=gnu99', '-w', str(pw), '-o', str(pw_exe)], check=True)
    password = subprocess.run([str(pw_exe)], capture_output=True, check=True).stdout
    return fence_exe, password


def fence_accepts(fence_exe, image, total):
    tmp_header = Path(image).with_suffix('.hdr')
    tmp_header.write_bytes(read(image, 0, 2))
    return subprocess.run([str(fence_exe), str(tmp_header), str(total)]).returncode == 0


def main():
    with tempfile.TemporaryDirectory() as tmp:
        fence_exe, password = compile_helpers(tmp)
        check(password == tool.MBR_PASSWORD,
              'tool MBR_PASSWORD %s != ps2sdk apaEncryptPassword("__mbr","sce_mbr") %s' % (tool.MBR_PASSWORD.hex(), password.hex()))

        def fresh(name):
            image = Path(tmp) / (name + '.img')
            starts, total = build_image(image, password)
            return image, starts, total

        # Healthy disk: diagnosis only, nothing to do.
        image, starts, total = fresh('healthy')
        before = digest_all(image)
        code, out = run_tool(image)
        check(code == 0 and 'Nothing to repair.' in out, 'healthy image not reported healthy:\n' + out)
        check('HDL' in out and 'PFS' in out, 'partition summary missing types:\n' + out)
        code, out = run_tool(image, '--repair', '--yes', '--backup', Path(tmp) / 'healthy.bak')
        check(code == 0 and digest_all(image) == before, 'repair touched a healthy image')
        check(not (Path(tmp) / 'healthy.bak').exists(), 'backup written for a healthy image')

        # The incident shape: the whole table sector zeroed or torn.
        image, starts, total = fresh('wiped')
        write(image, 0, b'\0' * 8 * SECTOR)
        damaged_head = read(image, 0, 0x2000)
        outside = digest_outside_table(image)
        code, out = run_tool(image)
        check(code == 1 and 'Repairable' in out and 'Do NOT format' in out, 'wiped table not reported repairable:\n' + out)
        check(digest_all(image) != '' and read(image, 0, 8) == b'\0' * 8 * SECTOR, 'diagnosis wrote to the disk')
        backup = Path(tmp) / 'wiped.bak'
        code, out = run_tool(image, '--repair', '--yes', '--backup', backup)
        check(code == 0 and 'Repaired and verified' in out, 'wiped table repair failed:\n' + out)
        check(digest_outside_table(image) == outside, 'repair changed bytes outside LBA 0-7')
        check(backup.read_bytes() == damaged_head, 'backup does not match the pre-repair first 4 MB')
        table = read(image, 0, 8)
        ok, rebuilt, dirty = tool.format_check(table)
        check(ok, 'rebuilt table fails the apaGetFormat rules')
        check(fence_accepts(fence_exe, image, total), 'rebuilt __mbr is refused by the IOP driver fence')
        check(rebuilt.next == starts[0] and rebuilt.prev == starts[-1] and rebuilt.length == starts[0],
              'rebuilt __mbr links/length wrong: next %#x prev %#x length %#x' % (rebuilt.next, rebuilt.prev, rebuilt.length))
        check(table[0x30:0x40] == password * 2, 'rebuilt __mbr passwords do not match ps2sdk')
        check(rebuilt.id == '__mbr' and rebuilt.type == 1 and rebuilt.nsub == 0 and rebuilt.start == 0, 'rebuilt __mbr fields wrong')
        code, out = run_tool(image)
        check(code == 0 and 'Nothing to repair.' in out, 'repaired image not healthy on re-check:\n' + out)

        # Garbage only in the error-record sectors: the header must survive byte for byte.
        image, starts, total = fresh('errors')
        original_header = read(image, 0, 2)
        write(image, 6, bytes(range(256)) * 4)
        outside = digest_outside_table(image)
        code, out = run_tool(image, '--repair', '--yes', '--backup', Path(tmp) / 'errors.bak')
        check(code == 0, 'error-sector repair failed:\n' + out)
        check(read(image, 0, 2) == original_header, 'a valid __mbr header was rewritten')
        check(read(image, 6, 2) == b'\0' * 2 * SECTOR, 'LBA 6-7 not cleared')
        check(digest_outside_table(image) == outside, 'error-sector repair changed bytes outside LBA 0-7')

        # A corrupt checksum: rebuilt, keeping the sane HDD-OSD boot area it still names.
        image, starts, total = fresh('checksum')
        write(image, 0, b'\x13\x37\x13\x37')
        code, out = run_tool(image, '--repair', '--yes', '--backup', Path(tmp) / 'checksum.bak')
        _, rebuilt, _ = tool.format_check(read(image, 0, 8))
        check(code == 0 and rebuilt.valid_mbr and (rebuilt.osd_start, rebuilt.osd_size) == (0x200, 0x1000),
              'checksum repair failed or lost the OSD area:\n' + out)

        # A valid header with a stale tail link: only the links change.
        image, starts, total = fresh('relink')
        raw = bytearray(read(image, 0, 2))
        struct.pack_into('<I', raw, 0x0C, starts[2])
        seal(raw)
        write(image, 0, bytes(raw))
        code, out = run_tool(image, '--repair', '--yes', '--backup', Path(tmp) / 'relink.bak')
        fixed = read(image, 0, 2)
        check(code == 0 and struct.unpack_from('<I', fixed, 0x0C)[0] == starts[-1], 'relink failed:\n' + out)
        check(fixed[0x10:] == bytes(raw[0x10:]), 'relink changed fields other than the links')

        # A broken chain: refuse, and write nothing.
        image, starts, total = fresh('broken')
        write(image, 0, b'\0' * 8 * SECTOR)
        write(image, starts[4], b'\0' * 2 * SECTOR)
        before = digest_all(image)
        code, out = run_tool(image, '--repair', '--yes', '--backup', Path(tmp) / 'broken.bak')
        check(code == 1 and 'BROKEN' in out and digest_all(image) == before, 'broken chain was not refused untouched:\n' + out)

        # A GPT/APA hybrid: refuse, and write nothing.
        image, starts, total = fresh('gpt')
        write(image, 1, b'EFI PART' + b'\0' * 504)
        before = digest_all(image)
        code, out = run_tool(image, '--repair', '--yes', '--backup', Path(tmp) / 'gpt.bak')
        check(code == 1 and 'GPT' in out and digest_all(image) == before, 'GPT hybrid was not refused untouched:\n' + out)

        # An existing backup file is never overwritten, and then nothing is written at all.
        image, starts, total = fresh('exists')
        write(image, 0, b'\0' * 8 * SECTOR)
        existing = Path(tmp) / 'exists.bak'
        existing.write_bytes(b'keep me')
        before = digest_all(image)
        code, out = run_tool(image, '--repair', '--yes', '--backup', existing)
        check(code == 1 and existing.read_bytes() == b'keep me' and digest_all(image) == before,
              'existing backup overwritten or disk written:\n' + out)

    if failures:
        print('apa_recover checks FAILED:')
        for failure in failures:
            print(' - ' + failure)
        sys.exit(1)
    print('apa_recover: all scenarios passed')


main()
