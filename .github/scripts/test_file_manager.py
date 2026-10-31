"""File Manager (after RIPPS2's Memory Files browser, akilluminati47): src/filemgr.c on the host.

The real filemgr.c is built with a small driver and run against a temporary folder; every result is checked
here with Python's own file calls, never with the code under test.

1. Paths: join, parent and base name on mass, card, SMB and pfs paths, device roots included; names that
   cannot be made are refused.
2. A folder lists folders first, each group by name with case ignored, files with their sizes.
3. Copy a file and a nested folder: every byte the same; progress reaches the total; a name already there is
   refused with the target untouched; a folder is never copied into itself.
4. Move within the drive (a rename) and a move whose rename fails (a copy, then the source removed): the tree
   arrives whole and the source is gone; a refused move leaves both sides as they were.
5. Rename and New folder: done, refused for a name already there or a bad name.
6. Delete: a nested folder goes; a device root is refused.
7. A copy that cannot finish (the drive fills part way, or the folder is read only) leaves no cut-short file
   behind, and a move that cannot finish keeps its source whole and takes back what it copied.
8. The GUI side: the dialog, the main-menu entry, the strings and the docs are wired up.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
CPP = (root / 'src/core/filemgr.cpp').exists()
SRC = root / ('src/core/filemgr.cpp' if CPP else 'src/filemgr.c')

DRIVER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/filemgr.h"

static unsigned long long lastDone, lastTotal;
static int calls;
static void progress(const char *name, unsigned long long done, unsigned long long total)
{
    (void)name;
    if (done < lastDone)
        printf("BACKWARDS\n");
    lastDone = done;
    lastTotal = total;
    calls++;
}

int main(int argc, char **argv)
{
    const char *op = argv[1];
    char out[400];
    int r = -1, i;

    if (!strcmp(op, "join")) {
        r = fmJoin(out, sizeof(out), argv[2], argv[3]);
        printf("%d %s\n", r, r ? out : "");
        return 0;
    }
    if (!strcmp(op, "parent")) {
        r = fmParent(out, sizeof(out), argv[2]);
        printf("%d %s\n", r, r ? out : "");
        return 0;
    }
    if (!strcmp(op, "base")) {
        printf("%s\n", fmBaseName(argv[2]));
        return 0;
    }
    if (!strcmp(op, "nameok")) {
        printf("%d\n", fmNameOk(argv[2]));
        return 0;
    }
    if (!strcmp(op, "size")) {
        char text[32];
        fmSizeText(strtoull(argv[2], NULL, 10), text, sizeof(text));
        printf("%s\n", text);
        return 0;
    }
    if (!strcmp(op, "list")) {
        static fm_entry_t e[200];
        int n = fmList(argv[2], e, 200);
        printf("%d\n", n);
        for (i = 0; i < n; i++)
            printf("%c %llu %s\n", e[i].isDir ? 'D' : 'F', e[i].size, e[i].name);
        return 0;
    }
    if (!strcmp(op, "tree")) {
        int count;
        unsigned long long size = fmTreeSize(argv[2], atoi(argv[3]), &count);
        printf("%llu %d\n", size, count);
        return 0;
    }
    if (!strcmp(op, "copy"))
        r = fmCopy(argv[2], atoi(argv[3]), argv[4], progress);
    else if (!strcmp(op, "move"))
        r = fmMove(argv[2], atoi(argv[3]), argv[4], progress);
    else if (!strcmp(op, "delete"))
        r = fmDelete(argv[2], atoi(argv[3]));
    else if (!strcmp(op, "rename"))
        r = fmRename(argv[2], argv[3]);
    else if (!strcmp(op, "mkdir"))
        r = fmMakeDir(argv[2], argv[3]);
    printf("%d %d %llu %llu %d\n", r, fmError(), lastDone, lastTotal, calls);
    return 0;
}
'''

# fmError() codes, from include/filemgr.h's order
ERR = {'OK': 0, 'EXISTS': 1, 'INSIDE': 2, 'NAME': 3, 'READ': 4, 'WRITE': 5, 'DELETE': 6, 'DEEP': 7, 'MEMORY': 8}
failures = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def build(tmp, rename_fails=False, disk_fills=False, rename_lies=False):
    drv = tmp / 'driver.c'
    drv.write_text(DRIVER)
    exe = tmp / ('fm_norename' if rename_fails else 'fm_full' if disk_fills else 'fm_lies' if rename_lies else 'fm')
    compiler = 'g++' if CPP else 'cc'
    lang = ['-x', 'c++'] if CPP else []
    extra = []
    if rename_fails:
        # a device that cannot rename: every rename() in filemgr fails, so moves take the copy path
        shim = tmp / 'norename.h'
        shim.write_text('#include <stdio.h>\n#include <errno.h>\nstatic int fakeRename(const char *a, const char *b)'
                        ' { (void)a; (void)b; errno = EXDEV; return -1; }\n#define rename fakeRename\n')
        extra = ['-include', str(shim)]
    if rename_lies:
        # a rename that moves the entry, then answers that it failed (as a card read back too soon can look)
        shim = tmp / 'lies.h'
        shim.write_text('#include <stdio.h>\n#include <errno.h>\nstatic int fakeRename(const char *a, const char *b)'
                        ' { (void)rename(a, b); errno = EIO; return -1; }\n#define rename fakeRename\n')
        extra = ['-include', str(shim)]
    if disk_fills:
        # a drive that fills after 100 KB: write() takes nothing more, as a full memory card answers
        shim = tmp / 'full.h'
        shim.write_text('#include <unistd.h>\nstatic long fullWritten;\n'
                        'static ssize_t fakeWrite(int fd, const void *b, size_t n) {\n'
                        '    if (fullWritten >= 100 * 1024) return 0;\n'
                        '    if (n > 4096) n = 4096; /* and takes only part of a block */\n'
                        '    ssize_t w = write(fd, b, n); if (w > 0) fullWritten += w; return w; }\n'
                        '#define write fakeWrite\n'
                        '#include <stdio.h>\n#include <errno.h>\n'  # and is another drive, so a move there is a copy
                        'static int fakeRename(const char *a, const char *b) { (void)a; (void)b; errno = EXDEV; return -1; }\n'
                        '#define rename fakeRename\n')
        extra = ['-include', str(shim)]
    obj = tmp / (exe.name + '.o')
    subprocess.run([compiler, '-Wall', '-Wextra', '-Werror', '-DFILEMGR_HOST_TEST', '-I', str(root)] + extra + lang +
                   ['-c', str(SRC), '-o', str(obj)], check=True)
    subprocess.run([compiler, '-Wall', '-I', str(root)] + lang + ['-c', str(drv), '-o', str(tmp / 'driver.o')],
                   check=True)  # the same language as filemgr, so the names link
    subprocess.run([compiler, str(obj), str(tmp / 'driver.o'), '-o', str(exe)], check=True)
    return exe


def run(exe, *args):
    return subprocess.run([str(exe)] + [str(a) for a in args], check=True, capture_output=True,
                          text=True).stdout


def result(out):
    r, err, done, total, calls = out.split()[:5]
    return int(r), int(err), int(done), int(total), int(calls)


def tree(path):
    """Every file under path with its bytes, and every folder, relative to path."""
    files, dirs = {}, set()
    for dirpath, dirnames, filenames in os.walk(path):
        rel = os.path.relpath(dirpath, path)
        for d in dirnames:
            dirs.add(os.path.normpath(os.path.join(rel, d)))
        for f in filenames:
            files[os.path.normpath(os.path.join(rel, f))] = Path(dirpath, f).read_bytes()
    return files, dirs


def make_tree(base):
    base.mkdir(parents=True)
    (base / 'icon.sys').write_bytes(bytes(range(256)) * 4)
    (base / 'big.bin').write_bytes(os.urandom(200 * 1024 + 17))  # more than one 64 KB buffer, not a multiple
    (base / 'empty.dat').write_bytes(b'')
    (base / 'sub' / 'deeper').mkdir(parents=True)
    (base / 'sub' / 'a.txt').write_bytes(b'hello')
    (base / 'sub' / 'deeper' / 'b.txt').write_bytes(b'world' * 1000)
    (base / 'emptydir').mkdir()


def main():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        exe = build(tmp)
        slow = build(tmp, rename_fails=True)
        full = build(tmp, disk_fills=True)
        lies = build(tmp, rename_lies=True)

        # 1. paths
        for d, n, want in (('mass0:/', 'A', 'mass0:/A'), ('mass0:/A', 'B', 'mass0:/A/B'),
                           ('mc0:/', 'BESLES', 'mc0:/BESLES'), ('smb0:', 'PS2', 'smb0:PS2'),
                           ('smb0:PS2', 'DVD', 'smb0:PS2\\DVD'), ('pfs0:/', 'APPS', 'pfs0:/APPS')):
            out = run(exe, 'join', d, n).split()
            check(out == ['1', want], 'join %s + %s = %s (got %s)' % (d, n, want, out))
        for p, want in (('mass0:/A/B', 'mass0:/A'), ('mass0:/A', 'mass0:/'), ('mass0:/A/', 'mass0:/'),
                        ('mc1:/SAVE/icon.sys', 'mc1:/SAVE'), ('mc1:/SAVE', 'mc1:/'), ('mc1:SAVE', 'mc1:/'),
                        ('smb0:PS2\\DVD', 'smb0:PS2'), ('smb0:PS2', 'smb0:'), ('pfs0:/APPS/x.elf', 'pfs0:/APPS')):
            out = run(exe, 'parent', p).split()
            check(out == ['1', want], 'parent of %s = %s (got %s)' % (p, want, out))
        for p in ('mass0:/', 'mc0:/', 'smb0:', 'smb0:\\', 'pfs0:/', 'mass0:'):
            check(run(exe, 'parent', p).split() == ['0'], 'a device root has no parent: ' + p)
        for p, want in (('mass0:/A/B.elf', 'B.elf'), ('smb0:PS2\\DVD', 'DVD'), ('mc0:/SAVE', 'SAVE'),
                        ('mc0:SAVE', 'SAVE')):
            check(run(exe, 'base', p).strip() == want, 'base name of %s = %s' % (p, want))
        for n, ok in (('GAME.ELF', 1), ('a b', 1), ('', 0), ('.', 0), ('..', 0), ('a/b', 0), ('a\\b', 0),
                      ('c:d', 0), ('x' * 127, 1), ('x' * 128, 0)):
            check(run(exe, 'nameok', n).strip() == str(ok), 'name %r %s' % (n[:20], 'allowed' if ok else 'refused'))
        for b, want in ((0, '0 KB'), (1, '1 KB'), (1024 * 1024, '1.0 MB'), (1536 * 1024, '1.5 MB'),
                        (3 * 1024 ** 3, '3.0 GB'), (5 * 1024 ** 4, '5120.0 GB')):
            check(run(exe, 'size', b).strip() == want, 'size %d = %s' % (b, want))

        # 2. listing
        lst = tmp / 'list'
        lst.mkdir()
        for name in ('zeta.txt', 'Alpha.bin', 'beta'):
            (lst / name).write_bytes(b'x' * len(name))
        for name in ('Zfolder', 'afolder', 'Mid'):
            (lst / name).mkdir()
        out = run(exe, 'list', lst).splitlines()
        check(out[0] == '6', 'six entries listed')
        check(out[1:] == ['D 0 afolder', 'D 0 Mid', 'D 0 Zfolder', 'F 9 Alpha.bin', 'F 4 beta', 'F 8 zeta.txt'],
              'folders first, by name with case ignored, files with sizes: %s' % out[1:])
        check(run(exe, 'list', tmp / 'nope').strip() == '-1', 'a missing folder lists as -1')

        # 3. copy
        src = tmp / 'drive' / 'SAVE'
        make_tree(src)
        want_files, want_dirs = tree(src)
        size, count = map(int, run(exe, 'tree', src, 1).split())
        check(size == sum(len(v) for v in want_files.values()) and count == len(want_files),
              'tree size and file count (%d bytes, %d files)' % (size, count))
        dst = tmp / 'other'
        dst.mkdir()
        r, err, done, total, calls = result(run(exe, 'copy', src, 1, dst))
        check(r == 1 and err == 0, 'copy a nested folder')
        check(tree(dst / 'SAVE') == (want_files, want_dirs), 'every file and folder the same, byte for byte')
        check(done == total == size and calls >= 4, 'progress reaches the total (%d of %d, %d calls)' % (done, total, calls))
        r, err, *_ = result(run(exe, 'copy', src / 'big.bin', 0, dst))
        check(r == 1 and (dst / 'big.bin').read_bytes() == want_files['big.bin'], 'copy one file')
        (dst / 'icon.sys').write_bytes(b'mine')
        r, err, *_ = result(run(exe, 'copy', src / 'icon.sys', 0, dst))
        check(r == 0 and err == ERR['EXISTS'] and (dst / 'icon.sys').read_bytes() == b'mine',
              'a name already there is refused, the file there untouched')
        r, err, *_ = result(run(exe, 'copy', src, 1, dst))
        check(r == 0 and err == ERR['EXISTS'] and tree(dst / 'SAVE') == (want_files, want_dirs),
              'a folder already there is refused, untouched')
        r, err, *_ = result(run(exe, 'copy', src, 1, src / 'sub'))
        check(r == 0 and err == ERR['INSIDE'] and not (src / 'sub' / 'SAVE').exists(),
              'a folder is never copied into itself')
        r, err, *_ = result(run(exe, 'copy', src, 1, src))
        check(r == 0 and err in (ERR['INSIDE'], ERR['EXISTS']) and tree(src) == (want_files, want_dirs),
              'nor into the folder it is in under its own name')

        # 4. move
        mv_src = tmp / 'drive' / 'MOVEME'
        make_tree(mv_src)
        mv_files = tree(mv_src)
        r, err, *_ = result(run(exe, 'move', mv_src, 1, dst))
        check(r == 1 and not mv_src.exists() and tree(dst / 'MOVEME') == mv_files, 'move a folder (a rename)')
        r, err, *_ = result(run(slow, 'move', dst / 'MOVEME', 1, tmp / 'drive'))
        check(r == 1 and not (dst / 'MOVEME').exists() and tree(mv_src) == mv_files,
              'move a folder where rename fails: copied whole, then the source removed')
        r, err, *_ = result(run(slow, 'move', mv_src / 'big.bin', 0, dst))
        check(r == 0 and err == ERR['EXISTS'] and (mv_src / 'big.bin').exists() and
              (dst / 'big.bin').read_bytes() == want_files['big.bin'], 'a refused move leaves both sides as they were')
        r, err, *_ = result(run(exe, 'move', mv_src, 1, mv_src / 'sub'))
        check(r == 0 and err == ERR['INSIDE'] and tree(mv_src) == mv_files, 'a folder is never moved into itself')
        r, err, *_ = result(run(lies, 'move', mv_src, 1, dst))
        check(not mv_src.exists() and tree(dst / 'MOVEME') == mv_files,
              'a rename that moves the folder but answers that it failed never costs the moved folder')
        r, err, *_ = result(run(exe, 'move', dst / 'MOVEME', 1, tmp / 'drive'))
        check(r == 1 and tree(mv_src) == mv_files, '(and it moves back)')

        # 5. rename and new folder
        r, err, *_ = result(run(exe, 'rename', mv_src / 'sub', 'renamed'))
        check(r == 1 and (mv_src / 'renamed' / 'deeper' / 'b.txt').exists() and not (mv_src / 'sub').exists(),
              'rename a folder')
        r, err, *_ = result(run(slow, 'rename', mv_src / 'renamed', 'again'))
        check(r == 1 and (mv_src / 'again' / 'deeper' / 'b.txt').read_bytes() == b'world' * 1000 and
              not (mv_src / 'renamed').exists(), 'rename where the device cannot rename: copied, old one removed')
        r, err, *_ = result(run(exe, 'rename', mv_src / 'big.bin', 'icon.sys'))
        check(r == 0 and err == ERR['EXISTS'] and (mv_src / 'big.bin').exists(), 'rename onto a name there is refused')
        r, err, *_ = result(run(exe, 'rename', mv_src / 'big.bin', 'a/b'))
        check(r == 0 and err == ERR['NAME'], 'rename to a bad name is refused')
        r, err, *_ = result(run(exe, 'mkdir', mv_src, 'NEW'))
        check(r == 1 and (mv_src / 'NEW').is_dir(), 'new folder')
        r, err, *_ = result(run(exe, 'mkdir', mv_src, 'NEW'))
        check(r == 0 and err == ERR['EXISTS'], 'a new folder over one there is refused')
        r, err, *_ = result(run(exe, 'mkdir', mv_src, '..'))
        check(r == 0 and err == ERR['NAME'], 'a new folder named .. is refused')

        # 6. delete
        r, err, *_ = result(run(exe, 'delete', mv_src, 1))
        check(r == 1 and not mv_src.exists(), 'delete a nested folder')
        r, err, *_ = result(run(exe, 'delete', dst / 'big.bin', 0))
        check(r == 1 and not (dst / 'big.bin').exists(), 'delete a file')
        r, err, *_ = result(run(exe, 'delete', 'mass0:/', 1))
        check(r == 0 and err == ERR['NAME'], 'a device root is never deleted')

        # 7. a copy that cannot finish leaves nothing cut short
        if os.geteuid() != 0:  # root ignores the read-only bit
            ro = tmp / 'readonly'
            ro.mkdir()
            os.chmod(ro, 0o555)
            r, err, *_ = result(run(exe, 'copy', src / 'big.bin', 0, ro))
            check(r == 0 and err == ERR['WRITE'] and not (ro / 'big.bin').exists(),
                  'a copy into a read-only folder fails as a write error, nothing left')
            os.chmod(ro, 0o755)
        else:
            print('SKIP read-only target (running as root)')
        fill = tmp / 'filling'
        fill.mkdir()
        r, err, *_ = result(run(full, 'copy', src / 'big.bin', 0, fill))
        check(r == 0 and err == ERR['WRITE'] and not (fill / 'big.bin').exists(),
              'a copy onto a drive that fills part way fails as a write error, the cut-short file removed')
        r, err, *_ = result(run(full, 'copy', src / 'sub' / 'deeper' / 'b.txt', 0, fill))
        check(r == 1 and (fill / 'b.txt').read_bytes() == b'world' * 1000,
              'writes that take part of a block are finished (a 5000-byte file copies whole)')
        r, err, *_ = result(run(full, 'copy', src, 1, fill))
        check(r == 0 and err == ERR['WRITE'] and not (fill / 'SAVE').exists(),
              'a folder copy onto a drive that fills part way takes back what it made')
        r, err, *_ = result(run(full, 'move', src, 1, fill))
        check(r == 0 and err == ERR['WRITE'] and tree(src) == (want_files, want_dirs) and not (fill / 'SAVE').exists(),
              'a move across drives that fills keeps its source whole and takes back what it copied')
        partial = tmp / 'partial'
        partial.mkdir()
        (partial / 'SAVE').mkdir()
        os.chmod(partial / 'SAVE', 0o555)
        if os.geteuid() != 0:
            r, err, *_ = result(run(slow, 'move', src, 1, partial / 'SAVE'))
            check(r == 0 and tree(src) == (want_files, want_dirs), 'a move that cannot copy keeps its source whole')
        os.chmod(partial / 'SAVE', 0o755)

    # 8. GUI wiring
    if CPP:
        gui = (root / 'src/ui/guifilemgr.cpp').read_text()
        menu = (root / 'src/ui/menusys.cpp').read_text()
        dialogs = (root / 'src/ui/dialogs.cpp').read_text()
        dia = (root / 'src/ui/dia.cpp').read_text()
        base = (root / 'lng/tmpl/_base.yml').read_text()
    else:
        gui = (root / 'src/guifilemgr.c').read_text()
        menu = (root / 'src/menusys.c').read_text()
        dialogs = (root / 'src/dialogs.c').read_text()
        dia = (root / 'src/dia.c').read_text()
        base = (root / 'lng_tmpl/_base.yml').read_text()
    check('MENU_FILE_MANAGER' in menu and 'guiShowFileManager()' in menu, 'the main menu opens the File Manager')
    check('diaFileManager[]' in dialogs and 'diaFileActions[]' in dialogs, 'its dialogs are defined')
    check('diaListUI' in dia and 'KEY_SQUARE' in dia and 'DIA_RESULT_NEXT' in dia, 'the dialog layer has list keys')
    for needle in ('gEnableWrite', 'fmCopy(', 'fmMove(', 'fmDelete(', 'fmRename(', 'fmMakeDir(',
                   'vmcSavesFolderToPsu(', 'vmcSavesPsuToFolder(', 'appLaunchElfPath(', 'guiMsgBox'):
        check(needle in gui, 'guifilemgr uses ' + needle)
    check('hdd0:' not in gui, 'no APA partition is ever listed or touched')
    check(not re.search(r'#define\s+FM_PATH\s', gui), 'nothing in guifilemgr redefines the FM_PATH label id')
    for key in ('FILE_MANAGER', 'HINT_FM_ROW', 'FM_DELETE_CONFIRM', 'FM_ERR_EXISTS', 'FM_PASTE', 'FM_PASTE_PSU'):
        check(('label: %s\n' % key) in base, 'string ' + key)
    docs = (root / 'docs/FILE_MANAGER.md')
    check(docs.exists() and 'akilluminati47' in docs.read_text(), 'docs/FILE_MANAGER.md, crediting AK')

    if failures:
        print('\n%d FAILED' % len(failures))
        raise SystemExit(1)
    print('\nAll File Manager checks passed')


if __name__ == '__main__':
    main()
