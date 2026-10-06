"""The rolling publish never leaves the public release missing files, even when GitHub fails mid-way.

On 2026-10-06 the publish step deleted every old asset first, GitHub answered HTTP 500 before the
upload, and the release sat without RIPTOPL.ELF, APP_RIPTOPL.psu and the DEBUG and VARIANTS packages.

Runs the real "update an existing release" commands from rolling-release.yml under bash, against a
fake `gh` that keeps the release as files in a temporary folder and behaves like the real one where
it matters: `--clobber` deletes a same-name asset before uploading its replacement, deleting a
missing asset is an error, and any call can be made to fail. Checks:
- a normal run leaves exactly the new set, including an old asset whose name has a space;
- a transient failure on any call is retried and the run still completes;
- when GitHub keeps failing, the step fails and the release still holds a complete set (old or new);
- a new RIPTOPL.ELF that GitHub keeps rejecting fails the step with the previous RIPTOPL.ELF put back.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
workflow = (root / '.github/workflows/rolling-release.yml').read_text(encoding='utf-8').replace('\r\n', '\n')

step = workflow[workflow.index('- name: Publish (rolling on the publishing branch'):]
step = step[:step.index('\n      - name:', 1)]
lines = [line[10:] if line.startswith(' ' * 10) else line.strip() for line in step.split('\n')]

failures = []
try:
    helper = next(line for line in lines if line.startswith('retry() {'))
    start = next(i for i, line in enumerate(lines) if 'echo "Updating existing release: $TAG"' in line)
    end = next(i for i, line in enumerate(lines) if i > start and '# REFRESH THE ROLLING RELEASE DATE' in line)
except StopIteration:
    sys.exit('rolling-release.yml: the publish step no longer has the retry helper or the existing-release block')
update = '\n'.join(lines[start:end])

FAKE_GH = r'''
#!/usr/bin/env bash
# gh, as far as the publish block uses it. The release lives in $RELEASE as one file per asset.
set -u
verb="$1 $2"
key=$(echo "$verb" | tr ' -' '__')
left=$(cat "$STATE/fail_$key" 2>/dev/null || echo 0)
if [ "$left" -gt 0 ]; then
  echo $((left - 1)) > "$STATE/fail_$key"
  echo "HTTP 500 ($verb)" >&2
  exit 1
fi
case "$verb" in
  "release view")
    ls -1 "$RELEASE" ;;
  "release download")
    shift 3
    pattern=""; dir=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --pattern) pattern="$2"; shift 2 ;;
        --dir) dir="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [ -e "$RELEASE/$pattern" ] || { echo "no assets match $pattern" >&2; exit 1; }
    cp "$RELEASE/$pattern" "$dir/$pattern" ;;
  "release upload")
    shift 3
    clobber=0
    for f in "$@"; do [ "$f" = "--clobber" ] && clobber=1; done
    for f in "$@"; do
      case "$f" in --*) continue ;; esac
      name=$(basename "$f")
      if [ -e "$RELEASE/$name" ]; then
        [ "$clobber" = 1 ] || { echo "asset under the same name already exists: $name" >&2; exit 1; }
        rm -f "$RELEASE/$name"   # what gh does: the old asset goes BEFORE the new one is sent
      fi
      bad=$(cat "$STATE/badnew_$name" 2>/dev/null || echo 0)
      if [ "$bad" -gt 0 ] && grep -q '^new ' "$f"; then
        echo $((bad - 1)) > "$STATE/badnew_$name"
        echo "HTTP 422 (upload $name)" >&2
        exit 1
      fi
      cp "$f" "$RELEASE/$name"
    done ;;
  "release edit")
    echo edited > "$STATE/edited" ;;
  "release delete-asset")
    [ -e "$RELEASE/$4" ] || { echo "release asset not found: $4" >&2; exit 1; }
    rm -f "$RELEASE/$4" ;;
  *)
    echo "fake gh: unexpected call: $*" >&2
    exit 2 ;;
esac
'''

HARNESS = '''set -eu
sleep() { :; }
TAG=rolling; TITLE=Rolling; RELEASE_FLAGS="--prerelease=false --latest"
@HELPER@
@UPDATE@
'''


def run_case(tmp, old, new, fail=None, badnew=None):
    release, state, rolling = (Path(tmp) / d for d in ('release', 'state', 'rolling'))
    for d in (release, state, rolling, Path(tmp) / 'replaced'):
        shutil.rmtree(d, ignore_errors=True)
    for d in (release, state, rolling):
        d.mkdir()
    for name in old:
        (release / name).write_text('old ' + name)
    for name in new:
        (rolling / name).write_text('new ' + name)
    for key, count in (fail or {}).items():
        (state / ('fail_' + key)).write_text(str(count))
    for name, count in (badnew or {}).items():
        (state / ('badnew_' + name)).write_text(str(count))
    (Path(tmp) / 'notes.md').write_text('notes')
    env = dict(os.environ, RELEASE=str(release), STATE=str(state), PATH=str(Path(tmp) / 'bin') + os.pathsep + os.environ['PATH'])
    result = subprocess.run(['bash', str(Path(tmp) / 'publish.sh')], cwd=tmp, env=env, capture_output=True, text=True,
                            check=False)
    after = {p.name: p.read_text() for p in release.iterdir()}
    return result.returncode, after, result.stderr


if not failures:
    old = ['RIPTOPL.ELF', 'APP_RIPTOPL.psu', 'RIPTOPL-v1.2.0-Beta-3482.zip', 'RIPTOPL-VARIANTS-v1.2.0-Beta-3482.zip',
           'legacy install.zip']
    new = ['RIPTOPL.ELF', 'APP_RIPTOPL.psu', 'RIPTOPL-v1.2.0-Beta-3484.zip', 'RIPTOPL-VARIANTS-v1.2.0-Beta-3484.zip']
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'bin').mkdir()
        gh = Path(tmp) / 'bin' / 'gh'
        gh.write_text(FAKE_GH.lstrip(), newline='\n')
        gh.chmod(0o755)
        (Path(tmp) / 'publish.sh').write_text(HARNESS.replace('@HELPER@', helper).replace('@UPDATE@', update), newline='\n')

        code, after, err = run_case(tmp, old, new)
        if code != 0 or sorted(after) != sorted(new) or any(not v.startswith('new ') for v in after.values()):
            failures.append('a normal publish must leave exactly the new set, an old name with a space included '
                            '(got %s, exit %d)\n%s' % (sorted(after), code, err))

        for key in ('release_view', 'release_download', 'release_upload', 'release_edit', 'release_delete_asset'):
            code, after, err = run_case(tmp, old, new, fail={key: 2})
            if code != 0 or sorted(after) != sorted(new):
                failures.append('two HTTP 500s on "%s" must be retried and the publish completed (got %s, exit %d)\n%s'
                                % (key.replace('_', ' '), sorted(after), code, err))

        code, after, err = run_case(tmp, old, new, badnew={'RIPTOPL.ELF': 2})
        if code != 0 or sorted(after) != sorted(new) or after.get('RIPTOPL.ELF') != 'new RIPTOPL.ELF':
            failures.append('a new RIPTOPL.ELF rejected twice after --clobber removed the old one must be retried '
                            '(got %s, exit %d)\n%s' % (sorted(after), code, err))

        # GitHub keeps failing: the step must fail, and the public release must still hold a full set.
        for key in ('release_upload', 'release_edit', 'release_delete_asset'):
            code, after, err = run_case(tmp, old, new, fail={key: 99})
            label = key.replace('_', ' ')
            if code == 0:
                failures.append('a publish whose "%s" never succeeds must fail the step' % label)
            if not (all(n in after for n in old) or all(n in after for n in new)):
                failures.append('when "%s" keeps failing, the release lost files: left %s' % (label, sorted(after)))
            if 'RIPTOPL.ELF' not in after:
                failures.append('when "%s" keeps failing, RIPTOPL.ELF must still be downloadable' % label)

        code, after, err = run_case(tmp, old, new, badnew={'RIPTOPL.ELF': 99})
        if code == 0:
            failures.append('a new RIPTOPL.ELF that GitHub always rejects must fail the step')
        if after.get('RIPTOPL.ELF') != 'old RIPTOPL.ELF':
            failures.append('a new RIPTOPL.ELF that GitHub always rejects must leave the PREVIOUS one downloadable '
                            '(got %r)\n%s' % (after.get('RIPTOPL.ELF'), err))
        if not all(n in after for n in old):
            failures.append('a rejected upload must not have deleted any old download: left %s' % sorted(after))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('rolling publish: uploads before it deletes, retries, restores a replaced file it lost, never leaves a partial release')
