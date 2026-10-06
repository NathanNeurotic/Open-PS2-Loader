"""The rolling publish never leaves the public release missing files, even when GitHub fails mid-way.

On 2026-10-06 the publish step deleted every old asset first, GitHub answered HTTP 500 before the
upload, and the release sat without RIPTOPL.ELF, APP_RIPTOPL.psu and the DEBUG and VARIANTS packages.

Runs the real "update an existing release" commands from rolling-release.yml under bash, against a
fake `gh` that keeps the release as files in a temporary folder and can fail any call. Checks:
- a normal run leaves exactly the new set (same-name files replaced, stale ones removed);
- a transient failure on any call is retried and the run still completes;
- when GitHub keeps failing, the step fails, and the release still holds a complete set (old or new).
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
script = '\n'.join(lines)

failures = []
try:
    helper = next(line for line in lines if line.startswith('retry() {'))
    start = next(i for i, line in enumerate(lines) if 'echo "Updating existing release: $TAG"' in line)
    end = next(i for i, line in enumerate(lines) if i > start and '# REFRESH THE ROLLING RELEASE DATE' in line)
except StopIteration:
    sys.exit('rolling-release.yml: the publish step no longer has the retry helper or the existing-release block')
update = '\n'.join(lines[start:end])
if '|| true' in update:
    failures.append('rolling-release.yml: a release write that may fail silently (|| true) can leave a partial release')

FAKE_GH = r'''
#!/usr/bin/env bash
# gh, as far as the publish block uses it: the release lives in $RELEASE as one file per asset.
set -u
call=$(( $(cat "$STATE/calls" 2>/dev/null || echo 0) + 1 ))
echo "$call" > "$STATE/calls"
verb="$1 $2"
fail_key=$(echo "$verb" | tr ' -' '__')
left=$(cat "$STATE/fail_$fail_key" 2>/dev/null || echo 0)
if [ "$left" -gt 0 ]; then
  echo $((left - 1)) > "$STATE/fail_$fail_key"
  echo "HTTP 500 ($verb)" >&2
  exit 1
fi
case "$verb" in
  "release view")
    ls "$RELEASE" ;;
  "release upload")
    shift 3
    for f in "$@"; do
      case "$f" in --*) continue ;; esac
      cp "$f" "$RELEASE/$(basename "$f")"
    done ;;
  "release edit")
    echo edited > "$STATE/edited" ;;
  "release delete-asset")
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


def run_case(tmp, old, new, fail):
    release, state, rolling = (Path(tmp) / d for d in ('release', 'state', 'rolling'))
    for d in (release, state, rolling):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
    for name in old:
        (release / name).write_text('old ' + name)
    for name in new:
        (rolling / name).write_text('new ' + name)
    for key, count in fail.items():
        (state / ('fail_' + key)).write_text(str(count))
    (Path(tmp) / 'notes.md').write_text('notes')
    env = dict(os.environ, RELEASE=str(release), STATE=str(state), PATH=str(Path(tmp) / 'bin') + os.pathsep + os.environ['PATH'])
    result = subprocess.run(['bash', str(Path(tmp) / 'publish.sh')], cwd=tmp, env=env, capture_output=True, text=True,
                            check=False)
    after = {p.name: p.read_text() for p in release.iterdir()}
    return result.returncode, after, result.stderr


if not failures:
    old = ['RIPTOPL.ELF', 'APP_RIPTOPL.psu', 'RIPTOPL-v1.2.0-Beta-3482.zip', 'RIPTOPL-VARIANTS-v1.2.0-Beta-3482.zip']
    new = ['RIPTOPL.ELF', 'APP_RIPTOPL.psu', 'RIPTOPL-v1.2.0-Beta-3484.zip', 'RIPTOPL-VARIANTS-v1.2.0-Beta-3484.zip']
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'bin').mkdir()
        gh = Path(tmp) / 'bin' / 'gh'
        gh.write_text(FAKE_GH.lstrip(), newline='\n')
        gh.chmod(0o755)
        (Path(tmp) / 'publish.sh').write_text(HARNESS.replace('@HELPER@', helper).replace('@UPDATE@', update), newline='\n')

        code, after, err = run_case(tmp, old, new, {})
        if code != 0 or sorted(after) != sorted(new) or any(not v.startswith('new ') for v in after.values()):
            failures.append('a normal publish must leave exactly the new set (got %s, exit %d)\n%s' % (sorted(after), code, err))

        for key in ('release_view', 'release_upload', 'release_edit', 'release_delete_asset'):
            code, after, err = run_case(tmp, old, new, {key: 2})
            if code != 0 or sorted(after) != sorted(new):
                failures.append('two HTTP 500s on "%s" must be retried and the publish completed (got %s, exit %d)\n%s'
                                % (key.replace('_', ' '), sorted(after), code, err))

        # GitHub keeps failing: the step must fail, and the public release must still hold a full set.
        for key in ('release_upload', 'release_edit', 'release_delete_asset'):
            code, after, err = run_case(tmp, old, new, {key: 99})
            complete_old = all(n in after for n in old)
            complete_new = all(n in after for n in new)
            if code == 0:
                failures.append('a publish whose "%s" never succeeds must fail the step' % key.replace('_', ' '))
            if not (complete_old or complete_new):
                failures.append('when "%s" keeps failing, the release lost files: left %s' % (key.replace('_', ' '), sorted(after)))
            if 'RIPTOPL.ELF' not in after:
                failures.append('when "%s" keeps failing, RIPTOPL.ELF must still be downloadable' % key.replace('_', ' '))

if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('rolling publish: uploads before it deletes, retries transient failures, never leaves a partial release')
