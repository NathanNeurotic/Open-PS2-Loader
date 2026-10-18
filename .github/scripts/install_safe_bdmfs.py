#!/usr/bin/env python3
"""Rebuild the installed SDK's own BDM driver with the reviewed VMC walker guard.

Using that SDK's source and headers preserves its BDM module ABI. Refuse unknown
walker revisions and never silently fall back to an unpatched release IRX.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

STOCK_SHA256 = 'aacd29d99b77e1c00c80f59dc970ca763d31ba4f00d85b98865b3776baa4269f'
MARKER = b'RiptOPL BDM VMC extent guard v1'


def stage(sdk_source, replacement):
    driver = sdk_source / 'iop/fs/bdmfs_fatfs/src/fs_driver.c'
    main = driver.with_name('main.c')
    source = driver.read_text(encoding='utf-8')
    start = source.index('static int get_frag_list(')
    end = source.index('\n}\n', start) + 3
    old = source[start:end]
    replacement = replacement[replacement.index('static int get_frag_list('):]
    if old != replacement and hashlib.sha256(old.encode()).hexdigest() != STOCK_SHA256:
        raise RuntimeError('Unknown BDM fragment walker revision; audit it before changing the SDK pin')
    source = source[:start] + replacement + source[end:]
    pattern = r'ret\s*=\s*get_frag_list\(file,\s*NULL,\s*0\)\s*==\s*1\s*\?\s*1\s*:\s*0;'
    source, changed = re.subn(pattern, 'ret = get_frag_list(file, NULL, 0);\n            if (ret >= 0)\n                ret = ret == 1 ? 1 : 0;', source)
    if changed != 1 and 'if (ret >= 0)\n                ret = ret == 1 ? 1 : 0;' not in source:
        raise RuntimeError('Unknown CHECK_CHAIN implementation')
    entry = main.read_text(encoding='utf-8')
    if MARKER.decode() not in entry:
        entry, changed = re.subn(r'(?m)^(\s*)(if\s*\(InitFS\(\))',
                                lambda m: m[1] + 'printf("' + MARKER.decode() + '\\n");\n' + m[1] + m[2], entry)
        if changed != 1:
            raise RuntimeError('Cannot mark the rebuilt BDM module entry point')
    # Validate all inputs before writing either source file.
    driver.write_text(source, encoding='utf-8')
    main.write_text(entry, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-source', type=Path)
    parser.add_argument('--sdk-install', type=Path)
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    installed = args.sdk_install or (Path(os.environ['PS2SDK']) if os.environ.get('PS2SDK') else None)
    sdk_source = args.sdk_source or (Path(os.environ['PS2SDKSRC']) if os.environ.get('PS2SDKSRC') else installed)
    if sdk_source is None or installed is None:
        parser.error('PS2SDK (and SDK source, if separate) is required')
    sdk_source, installed = sdk_source.resolve(), installed.resolve()
    replacement = Path(__file__).resolve().parents[1] / 'patches/bdmfs-vmc-fragment-walk.c'
    stage(sdk_source, replacement.read_text(encoding='utf-8'))
    if args.stage_only:
        return
    module = sdk_source / 'iop/fs/bdmfs_fatfs'
    subprocess.run(['make', '-C', str(module), 'PS2SDKSRC=' + str(sdk_source),
                    'PS2SDK=' + str(installed), 'clean', 'all'], check=True)
    irx = module / 'irx/bdmfs_fatfs.irx'
    if not irx.is_file() or MARKER not in irx.read_bytes():
        raise RuntimeError('Rebuilt BDM IRX missing or safety marker absent; refusing release packaging')
    destination = installed / 'iop/irx/bdmfs_fatfs.irx'
    if irx.resolve() != destination.resolve():
        shutil.copyfile(irx, destination)
    print('Installed verified VMC-safe BDM IRX:', destination)
    print('SHA256:', hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
