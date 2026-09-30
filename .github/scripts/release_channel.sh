#!/bin/sh
# Prints GITHUB_ENV lines naming the rolling channel the current ref publishes to. Run from each
# rolling-release build job BEFORE "make oplversion":  sh .github/scripts/release_channel.sh >> "$GITHUB_ENV"
#
#   rebuild/main (and any other ref): prints nothing -- the Makefile's own version stands.
#   test/korium-audit-remediation (the Korium test line, PR #687): RELEASE_CHANNEL=Korium, and REVISION
#     set to the revision of the rebuild/main commit that line was last synced to. The Korium branch
#     carries extra merge commits, so its own commit count would give a different Beta number for the
#     same code; this makes a Korium build read Beta-N-Korium beside the Rolling build's Beta-N.
set -eu

case "${GITHUB_REF:-}" in
refs/heads/test/korium-audit-remediation) ;;
*) exit 0 ;;
esac

# The pinned job does not unshallow, and a merge-base needs history on both sides.
git fetch --quiet --prune --unshallow origin 2>/dev/null || true
git fetch --quiet origin rebuild/main
base=$(git merge-base HEAD FETCH_HEAD)

echo "RELEASE_CHANNEL=Korium"
echo "REVISION=$(($(git rev-list --count "$base") + 2))"
