"""An SMB game launch keeps the image's whole file name, from the EE to the path the game opens.

The EE (its ethsupport source) writes the image's file name into the settings block,
cdvdman_settings_smb.filename (modules/iopcore/common/cdvd_config.h), with snprintf, and the game's
modules/iopcore/cdvdman/device-smb.c opens "\\<prefix>\\DVD\\<file name>" built from that block. A
field too short for a name the menu lists cuts it, and the game opens a file that does not exist.

This checks, in the EE source:
- every write to settings->filename is an snprintf bounded by sizeof(settings->filename), and they are
  three, in this order: the old format's "%s.%s%s", the plain "%s%s" and USBExtreme's "ul.%08X.%s";
- tests/smb2-live/launchname.c and longname.c fill the block with the same three calls.
Then it builds launchname.c with device-smb.c and the real cdvd_config.h, under AddressSanitizer and
UBSan, and runs it: each format, the name lengths either side of each one the old 160-byte field cut
and the longest, with no prefix and the longest, on a DVD and a CD; the block must hold the whole name
and device-smb.c must open exactly the path it names.
This is a host check, not a console test. tests/smb2-live/run.sh launches the longest names against
Samba (longname.sh).
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
live = root / 'tests/smb2-live'
failures = []


def check(cond, what):
    if not cond:
        failures.append(what)


def strip_comments(src):
    """C or C++ source with each comment replaced by a space; string and character literals kept."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
            out.append(' ')
        elif src.startswith('//', i):
            j = src.find('\n', i)
            i = n if j < 0 else j
            out.append(' ')
        elif src[i] in '"\'':
            j = i + 1
            while j < n and src[j] != src[i]:
                j += 2 if src[j] == '\\' else 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def fills(src, field):
    """The (bound, format) of each snprintf into field, in order, and how many times field is named."""
    f = r'\s*'.join(map(re.escape, re.findall(r'\w+|\S', field)))
    calls = re.findall(r'\bsnprintf\s*\(\s*' + f + r'\s*,\s*([^,]+?)\s*,\s*"((?:[^"\\]|\\.)*)"', src)
    return [(re.sub(r'\s+', '', b), fmt) for b, fmt in calls], len(re.findall(r'(?<![\w.>])' + f + r'(?!\w)', src))


FORMATS = ['%s.%s%s', '%s%s', 'ul.%08X.%s']

ee = next((root / p for p in ('src/sources/ethsupport.cpp', 'src/ethsupport.c') if (root / p).is_file()), None)
check(ee is not None, 'no src/sources/ethsupport.cpp or src/ethsupport.c: update this check')
if ee is not None:
    calls, named = fills(strip_comments(ee.read_text(encoding='utf-8')), 'settings->filename')
    check([fmt for _, fmt in calls] == FORMATS,
          '%s fills settings->filename with %s; this check expects %s, in that order: update it, launchname.c and '
          'longname.c together' % (ee.relative_to(root), [fmt for _, fmt in calls], FORMATS))
    check(all(b == 'sizeof(settings->filename)' for b, _ in calls),
          '%s bounds an snprintf into settings->filename by %s, not by sizeof(settings->filename)' %
          (ee.relative_to(root), ', '.join(b for b, _ in calls if b != 'sizeof(settings->filename)')))
    # Every other mention is a sizeof (the static_asserts): nothing else writes the field.
    sizeofs = len(re.findall(r'\bsizeof\s*\(\s*settings\s*->\s*filename\s*\)', strip_comments(ee.read_text(encoding='utf-8'))))
    check(named == len(calls) + sizeofs,
          '%s names settings->filename %d times, %d of them in the snprintf calls and %d in sizeof: something else '
          'writes or reads it, check it keeps the whole name' % (ee.relative_to(root), named, len(calls), sizeofs))
for test in ('launchname.c', 'longname.c'):
    calls, _ = fills(strip_comments((live / test).read_text(encoding='utf-8')), 'cdvdman_settings.filename')
    check(calls == [('sizeof(cdvdman_settings.filename)', fmt) for fmt in FORMATS],
          'tests/smb2-live/%s fills the settings block with %s; it must make the EE\'s calls, %s, bounded by '
          'sizeof(cdvdman_settings.filename)' % (test, calls, FORMATS))

namemax = re.search(r'^#define\s+ISO_GAME_NAME_MAX\s+(\d+)', (root / 'include/supportbase.h').read_text(encoding='utf-8'), re.M)
check(namemax is not None, 'ISO_GAME_NAME_MAX is not defined in include/supportbase.h: update this check')
if namemax is not None:
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / 'launchname'
        p = subprocess.run(['cc', '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-fno-omit-frame-pointer',
                            '-g', '-O1', '-Wall', '-Wno-unused-parameter', '-DSMB_DRIVER',
                            '-DISO_GAME_NAME_MAX=' + namemax.group(1), '-I', str(live / 'inc-device'), '-I',
                            str(live / 'inc-ingame'), '-I', str(root / 'modules/iopcore/cdvdman'), '-I',
                            str(root / 'modules/iopcore/common'), str(live / 'launchname.c'),
                            str(root / 'modules/iopcore/cdvdman/device-smb.c'), '-o', str(exe)],
                           capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stdout + p.stderr)
            sys.exit('tests/smb2-live/launchname.c does not build on the host')
        p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        out = p.stdout + p.stderr
        check(p.returncode == 0 and 'Sanitizer' not in out and 'runtime error' not in out,
              'tests/smb2-live/launchname.c (exit %d):\n%s' % (p.returncode, out))
        summary = out.strip().splitlines()[-1] if out.strip() else ''

if failures:
    print('SMB launch name checks FAILED:')
    for failure in failures:
        print('  ' + failure)
    sys.exit(1)
print('smb launch name: the EE writes the whole file name into the settings block with the three formats launchname.c '
      'and longname.c use, and device-smb.c opens it whole (%s)' % summary)
