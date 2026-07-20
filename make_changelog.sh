#!/bin/bash
set -euo pipefail

for i in $(seq 1 120); do
  if git fetch origin agent/unified-stage1-hdd; then
    break
  fi
  sleep 5
done
git rev-parse --verify FETCH_HEAD
git reset --hard FETCH_HEAD
git clean -fdx

python3 - <<'PY'
from pathlib import Path
path = Path('src/mmcesupport.c')
text = path.read_text()
old = '''    // VCD view: hand off to POPSTARTER (by name) instead of the disc path below. Menu-launch only.\n    if (gAutoLaunchBDMGame == NULL && game != NULL && vcdViewActive(itemList->mode)) {\n        mmceLaunchVcd(itemList, game->name, configSet);\n        return;\n    }\n\n    if (!cacheAbortMmceImageLoadsTimed(MMCE_ART_ABORT_WAIT_TICKS)) {\n        // #120: the art worker is wedged in a blocking fileXio on a slow/desynced card. Do NOT cacheEnd(1)\n        // here -- its TerminateThread(gArtThreadId) kills the worker MID-RPC and orphans the SHARED mmceman\n        // channel (TK>0). The launch reads below then FAIL and RETURN to a still-running OPL (unlike a launch\n        // that LoadExecPS2's away), poisoning every later card read. Abandon-and-retry instead (mirrors\n        // thmLoad's redesign): toast and bail so the user retries once the card is calm. NEVER a hard\n        // freeze -- guiWarning is non-blocking.\n        guiWarning(_l(_STR_ERR_FILE_INVALID), 8);\n        return;\n    }\n'''
new = '''    // Quiesce every MMCE art read before either launch path performs card IO. The VCD handoff\n    // resolves POPSTARTER and may equip BDMA modules from MMCE before deinit(), so allowing its early\n    // return to bypass this guard can contend with the persistent art worker on the same mmceman channel.\n    if (!cacheAbortMmceImageLoadsTimed(MMCE_ART_ABORT_WAIT_TICKS)) {\n        // #120: the art worker is wedged in a blocking fileXio on a slow/desynced card. Do NOT cacheEnd(1)\n        // here -- its TerminateThread(gArtThreadId) kills the worker MID-RPC and orphans the SHARED mmceman\n        // channel (TK>0). Abandon-and-retry instead so the user can retry once the card is calm.\n        guiWarning(_l(_STR_ERR_FILE_INVALID), 8);\n        return;\n    }\n\n    // VCD view: hand off to POPSTARTER (by name) instead of the disc path below. Menu-launch only.\n    if (gAutoLaunchBDMGame == NULL && game != NULL && vcdViewActive(itemList->mode)) {\n        mmceLaunchVcd(itemList, game->name, configSet);\n        return;\n    }\n'''
if old not in text:
    raise SystemExit('MMCE launch block anchor missing')
path.write_text(text.replace(old, new, 1))
PY

apk add --no-cache clang18-extra-tools
/usr/lib/llvm18/bin/clang-format --lines=610:650 -i src/mmcesupport.c

git add src/mmcesupport.c
export GIT_AUTHOR_NAME="ChatGPT"
export GIT_AUTHOR_EMAIL="noreply@openai.com"
export GIT_COMMITTER_NAME="ChatGPT"
export GIT_COMMITTER_EMAIL="noreply@openai.com"
parent=$(git rev-parse HEAD)
tree=$(git write-tree)
commit=$(printf '%s\n' "Quiesce MMCE art before VCD launch IO" | git commit-tree "$tree" -p "$parent")
git push --force origin "$commit":refs/heads/agent/unified-stage2-mmce
