"""Verify the installer is source-guarded, idempotent and applied to every release build."""
from pathlib import Path
import importlib.util
import hashlib
import io
import json
import tempfile

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('safe_bdmfs', root / '.github/scripts/install_safe_bdmfs.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
replacement = (root / '.github/patches/bdmfs-vmc-fragment-walk.c').read_text()
stock = (root / '.github/scripts/fixtures/bdmfs-frag-stock.txt').read_text()

with tempfile.TemporaryDirectory() as temp:
    sdk = Path(temp)
    folder = sdk / 'iop/fs/bdmfs_fatfs/src'
    folder.mkdir(parents=True)
    driver = folder / 'fs_driver.c'
    main = folder / 'main.c'
    driver.write_text(stock + '\nret = get_frag_list(file, NULL, 0) == 1 ? 1 : 0;\n')
    main.write_text('int _start(void) {\n    if (InitFS() != 0) return 1;\n}\n')
    installer.stage(sdk, replacement)
    once = (driver.read_text(), main.read_text())
    assert 'iClusterNext == 0xFFFFFFFF' in once[0]
    assert 'if (ret >= 0)' in once[0]
    assert installer.MARKER.decode() in once[1]
    installer.stage(sdk, replacement)
    assert (driver.read_text(), main.read_text()) == once

    driver.write_text(stock.replace('int iFragCount = 0;', 'int iFragCount = 1;'))
    before = (driver.read_text(), main.read_text())
    try:
        installer.stage(sdk, replacement)
    except RuntimeError:
        pass
    else:
        raise AssertionError('unknown source revision was accepted')
    assert (driver.read_text(), main.read_text()) == before

    real_urlopen = installer.urllib.request.urlopen
    installer.urllib.request.urlopen = lambda *args, **kwargs: io.BytesIO(b'known source')
    target = sdk / 'download.c'
    entry = dict(repo='example/repo', ref='a' * 40, path='file.c',
                 sha256=hashlib.sha256(b'known source').hexdigest())
    installer.download(entry, target)
    assert target.read_bytes() == b'known source'
    entry['sha256'] = '0' * 64
    try:
        installer.download(entry, target)
    except RuntimeError:
        pass
    else:
        raise AssertionError('incorrect source hash was accepted')
    assert target.read_bytes() == b'known source'
    installer.urllib.request.urlopen = real_urlopen

lock = json.loads((root / '.github/patches/bdmfs-vmc-sources.json').read_text())
assert len(lock) == 13
assert all(len(entry['ref']) == 40 and len(entry['sha256']) == 64 for entry in lock)

for path in (root / '.github/workflows').glob('*.yml'):
    source = path.read_text()
    if path.name in ('korium-background-diagnostic.yml', 'korium-pr-test.yml'):
        # These intentionally check out historical release/PR references. They
        # must not inject new dependencies into an exact-source comparison.
        assert 'python3 .github/scripts/install_safe_bdmfs.py' not in source
        continue
    assert source.count('sh .github/scripts/install_coherent_mmce.sh') == source.count(
        'python3 .github/scripts/install_safe_bdmfs.py'), str(path)
print('BDM installer: known source only, idempotence, failure preserves input, all build entry points pass')
