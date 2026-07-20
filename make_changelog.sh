#!/bin/bash
set -euo pipefail

git fetch origin agent/unified-mmce-vcd-fixes
git reset --hard FETCH_HEAD
git clean -fdx

python3 - <<'PY'
from pathlib import Path
path = Path('src/vcdsupport.c')
text = path.read_text()
old = '''    if (stat(path, &st) != 0 || st.st_size <= 0 || st.st_size > VCD_BACKUP_MAX)
        return -1;
    size = (int)st.st_size;
'''
new = '''    if (stat(path, &st) != 0 || st.st_size < 0 || st.st_size > VCD_BACKUP_MAX)
        return -1;
    if (st.st_size == 0)
        return 0;
    size = (int)st.st_size;
'''
if old not in text:
    raise SystemExit('bounded read size anchor missing')
text = text.replace(old, new, 1)
old = '''    if (hadOldMarker && vcdReadFileAlloc(markerPath, &oldMarker, &oldMarkerSize) != 0) {
        free(old0);
        free(old1);
        unlink(tmp0);
        unlink(tmp1);
        return -3;
    }
'''
new = '''    if (hadOldMarker) {
        if (vcdReadFileAlloc(markerPath, &oldMarker, &oldMarkerSize) != 0) {
            free(old0);
            free(old1);
            unlink(tmp0);
            unlink(tmp1);
            return -3;
        }
        // An empty marker is corrupted state, not something worth restoring. Treat it as absent so a
        // replacement can proceed and rollback removes it rather than recreating the empty file.
        if (oldMarkerSize == 0)
            hadOldMarker = 0;
    }
'''
if old not in text:
    raise SystemExit('marker backup anchor missing')
path.write_text(text.replace(old, new, 1))
PY

apk add --no-cache clang18-extra-tools
/usr/lib/llvm18/bin/clang-format --lines=650:690 --lines=930:965 -i src/vcdsupport.c

git add src/vcdsupport.c
export GIT_AUTHOR_NAME="ChatGPT"
export GIT_AUTHOR_EMAIL="noreply@openai.com"
export GIT_COMMITTER_NAME="ChatGPT"
export GIT_COMMITTER_EMAIL="noreply@openai.com"
parent=$(git rev-parse HEAD)
tree=$(git write-tree)
commit=$(printf '%s\n' "Handle corrupted empty BDMA markers" | git commit-tree "$tree" -p "$parent")
git push --force origin "$commit":refs/heads/agent/reviewfix-empty-bdma-marker-stage
