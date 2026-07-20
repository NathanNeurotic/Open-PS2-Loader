#!/bin/bash
set -euo pipefail

for i in $(seq 1 120); do
  if git fetch origin agent/unified-stage2-mmce; then
    break
  fi
  sleep 5
done
git rev-parse --verify FETCH_HEAD
git reset --hard FETCH_HEAD
git clean -fdx

# Import the already-reviewed transactional implementation, then repair the one malformed
# NUL character introduced by an earlier source-publication script.
git fetch origin agent/final-bdma-transaction-integrity-v2
git show origin/agent/final-bdma-transaction-integrity-v2:src/vcdsupport.c > src/vcdsupport.c
python3 - <<'PY'
from pathlib import Path
path = Path('src/vcdsupport.c')
data = path.read_bytes()
bad = b"mcDir[0] == '\x00'"
if bad not in data:
    raise SystemExit('expected malformed NUL expression not found')
data = data.replace(bad, b"mcDir[0] == 0", 1)
if b'\x00' in data:
    raise SystemExit('unexpected NUL byte remains in vcdsupport.c')
path.write_bytes(data)
PY

git add src/vcdsupport.c
export GIT_AUTHOR_NAME="ChatGPT"
export GIT_AUTHOR_EMAIL="noreply@openai.com"
export GIT_COMMITTER_NAME="ChatGPT"
export GIT_COMMITTER_EMAIL="noreply@openai.com"
parent=$(git rev-parse HEAD)
tree=$(git write-tree)
commit=$(printf '%s\n' "Make BDMA driver replacement transactional" | git commit-tree "$tree" -p "$parent")
git push --force origin "$commit":refs/heads/agent/unified-mmce-vcd-fixes
