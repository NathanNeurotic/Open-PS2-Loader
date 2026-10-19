#!/usr/bin/env python3
"""Regression checks for release title and classification policy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def contains(path, *terms):
    content = (ROOT / path).read_text(encoding="utf-8")
    for term in terms:
        assert term in content, f"{path}: missing release policy {term!r}"


def main():
    contains(".github/workflows/rolling-release.yml",
             "'Korium' || 'inceBtion'",
             "'rolling-korium' || 'rolling'",
             "'--latest=false' || '--latest'",
             'RELEASE_FLAGS="--prerelease=false $ROLLING_LATEST"',
             'retry gh release edit "$TAG" --title "$TITLE" --notes-file notes.md $RELEASE_FLAGS')
    contains(".github/scripts/publish_ra_release.py",
             'title = "RetroAchievements"',
             '"--latest=false", "--prerelease", "--draft=false"',
             '"--draft", "--prerelease", "--latest=false"')
    contains(".github/workflows/promote-rolling-latest.yml",
             '--title "inceBtion"',
             'gh release edit rolling-korium',
             '--title "Korium"',
             'gh release edit rolling-ra',
             '--title "RetroAchievements"',
             'if [ "$LATEST" != "rolling" ]',
             "if: env.SUPERSEDED != '1'")
    print("Release titles and classification policy: OK")


if __name__ == "__main__":
    main()
