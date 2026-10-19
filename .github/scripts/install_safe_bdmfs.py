#!/usr/bin/env python3
"""Rebuild the installed SDK's own BDM driver with the reviewed VMC walker guard.

Using that SDK's source and headers preserves its BDM module ABI. Refuse unknown
walker revisions and never silently fall back to an unpatched release IRX.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

STOCK_SHA256 = 'aacd29d99b77e1c00c80f59dc970ca763d31ba4f00d85b98865b3776baa4269f'
MARKER = b'RiptOPL BDM VMC extent and allocation guard v2'


def download(entry, destination):
    url = 'https://raw.githubusercontent.com/{repo}/{ref}/{path}'.format(**entry)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise RuntimeError('BDM source hash mismatch: ' + entry['path'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


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


def stage_allocation(sdk_source, repo):
    driver = sdk_source / 'iop/fs/bdmfs_fatfs/src/fs_driver.c'
    source = driver.read_text(encoding='utf-8')
    if '#include "vmc_alloc.h"' in source:
        raise RuntimeError('Allocation source already patched; rebuild from the pinned SDK source')
    anchor = '    ret = f_open(fd->privdata, modified_name, f_mode);'
    if source.count(anchor) != 1:
        raise RuntimeError('Unknown BDM open implementation')
    source = source.replace(anchor,
        '    if ((flags & (O_CREAT | FIO_O_EXCL)) == (O_CREAT | FIO_O_EXCL))\n'
        '        f_mode = (f_mode & (FA_READ | FA_WRITE)) | FA_CREATE_NEW;\n\n' + anchor)
    start = source.index('int fs_ioctl2(')
    helper = (repo / '.github/patches/bdmfs-vmc-allocation.c').read_text()
    source = source[:start] + helper + '\n' + source[start:]
    start = source.index('int fs_ioctl2(')
    anchor = '        case USBMASS_IOCTL_RENAME:'
    index = source.index(anchor, start)
    cases = '        case VMC_ALLOC_RESERVE:\n        case VMC_ALLOC_VERIFY: {\n            vmc_alloc_request_t request;\n            if (!(fd->mode & FIO_O_EXCL) || data == NULL || datalen != sizeof(request)) {\n                ret = -EINVAL;\n                break;\n            }\n            memcpy(&request, data, sizeof(request));\n            ret = vmc_allocate_contiguous(file, &request, cmd == VMC_ALLOC_RESERVE);\n            break;\n        }\n'
    source = source[:index] + cases + source[index:]
    start = source.index('static int fs_devctl(')
    index = source.index('        case USBMASS_DEVCTL_STOP_UNIT:', start)
    source = source[:index] + '        case VMC_ALLOC_CAPS:\n            ret = VMC_ALLOC_V1;\n            break;\n' + source[index:]
    source = '#include "vmc_alloc.h"\n' + source
    driver.write_text(source, encoding='utf-8')
    shutil.copyfile(repo / 'include/vmc_alloc.h', driver.with_name('vmc_alloc.h'))


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
    if args.stage_only:
        stage(sdk_source, replacement.read_text(encoding='utf-8'))
        return
    repo = Path(__file__).resolve().parents[2]
    lock = json.loads((repo / '.github/patches/bdmfs-vmc-sources.json').read_text())
    with tempfile.TemporaryDirectory(prefix='ript-bdmfs-') as temp:
        scratch = Path(temp)
        staged_sdk = scratch / 'sdk'
        module = staged_sdk / 'iop/fs/bdmfs_fatfs'
        existing = sdk_source / 'iop/fs/bdmfs_fatfs/src'
        if existing.is_dir():
            shutil.copytree(existing, module / 'src')
        else:
            # Some SDK images retain headers/IRXs but discard their source tree.
            # Pin the source in that case, but compile against the installed SDK's
            # BDM/import headers so its actual ABI remains authoritative.
            for entry in lock:
                if entry['group'] == 'sdk':
                    download(entry, staged_sdk / entry['path'])
        stage(staged_sdk, replacement.read_text(encoding='utf-8'))
        stage_allocation(staged_sdk, repo)
        build = scratch / 'build'
        build.mkdir()
        for source_file in (module / 'src').rglob('*'):
            if source_file.is_file() and source_file.suffix in ('.c', '.h', '.lst'):
                shutil.copyfile(source_file, build / source_file.name)
        # The images can keep an empty dependency directory; always use the
        # content-verified FatFs pin instead of trusting directory existence.
        for entry in lock:
            if entry['group'] == 'fatfs':
                download(entry, build / Path(entry['path']).name)
        config = build / 'ffconf.h'
        config_text = config.read_text()
        config_text, changed = re.subn(r'(#define FF_USE_EXPAND\s+)0\b', r'\g<1>1', config_text)
        if changed != 1:
            raise RuntimeError('Unknown FatFs expand configuration')
        config.write_text(config_text)
        (build / 'Makefile').write_text(
            'IOP_BIN = bdmfs_fatfs.irx\n'
            'IOP_OBJS = main.o imports.o fs_driver.o diskio.o ff.o ffsystem.o ffunicode.o\n'
            'IOP_LIBS += -lgcc\n'
            'include $(PS2SDK)/Defs.make\n'
            'include ' + (repo / 'modules/Rules.bin.make').as_posix() + '\n'
            'include $(PS2SDK)/samples/Makefile.iopglobal\n')
        subprocess.run(['make', '-C', str(build), 'PS2SDK=' + str(installed), 'all'], check=True)
        irx = build / 'bdmfs_fatfs.irx'
        if not irx.is_file() or MARKER not in irx.read_bytes():
            raise RuntimeError('Rebuilt BDM IRX missing or safety marker absent; refusing release packaging')
        destination = installed / 'iop/irx/bdmfs_fatfs.irx'
        shutil.copyfile(irx, destination)
    print('Installed verified VMC-safe BDM IRX:', destination)
    print('SHA256:', hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
