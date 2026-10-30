#!/usr/bin/env python3
"""Publish a validated two-theme RA asset set without changing standard releases."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TAG = "rolling-ra"
THEMES = ("inceBtion", "Korium")
# GitHub's release API intermittently answers 5xx (a 500 once cost the standard release its loose ELF
# mid-publish, #855). Every call below is safe to repeat, so retry before giving up.
RETRY_DELAYS = (5, 15)
REPUBLISH_DELAY = 60


def gh(*args):
    for delay in (*RETRY_DELAYS, None):
        try:
            return subprocess.check_output(["gh", *args], text=True).strip()
        except subprocess.CalledProcessError:
            if delay is None:
                raise
            print(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)


def validate(folder):
    manifest = json.loads((folder / "RA-RELEASE.json").read_text())
    if manifest.get("preview", True):
        raise ValueError("preview packages cannot be published")
    version = manifest["version"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
        raise ValueError("unsafe release version")
    revision = manifest["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or manifest["themes"] != list(THEMES):
        raise ValueError("release requires both themes and a full source SHA")
    required = {f"RIPTOPL-RetroAchievements-src-{version}.zip"}
    for theme in THEMES:
        required.update((f"RIPTOPL-RA-{theme}.ELF", f"APP_RIPTOPL-RA-{theme}.psu",
                         f"RIPTOPL-RetroAchievements-{theme}-{version}.zip"))
    if set(manifest["assets"]) != required:
        raise ValueError("incomplete or unexpected RA asset set")
    if {file.name for file in folder.iterdir()} != required | {"RA-RELEASE.json", "SHA256SUMS.txt"}:
        raise ValueError("unexpected publication files")
    for name, expected in manifest["assets"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"release digest mismatch: {name}")
    sums = "".join(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
                   for file in sorted(folder.iterdir()) if file.name != "SHA256SUMS.txt")
    if (folder / "SHA256SUMS.txt").read_text() != sums:
        raise ValueError("release checksum manifest mismatch")
    return revision


def refresh_release_date(repository):
    """GitHub dates a release by publishedAt, which only a draft -> published transition sets, so a
    rolling-ra with new notes and assets still read as weeks old. Flip it to draft and straight back,
    as rolling-release.yml does for rolling and rolling-korium: the release keeps its id, tag, assets,
    download links and counts. It is hidden for the moment between the two calls, so the republish
    runs even if the first call fails, and a release still a draft afterwards fails the run."""
    before = json.loads(gh("release", "view", TAG, "--repo", repository, "--json", "publishedAt"))["publishedAt"]
    try:
        gh("release", "edit", TAG, "--repo", repository, "--draft=true")
    except subprocess.CalledProcessError as error:
        # Only the date is lost; still republish, check the state and go on to the other channels.
        print(f"{TAG}: could not switch to draft ({error}); checking it is still published", file=sys.stderr)
    # A draft cannot hold the Latest marker, so the flags are asserted again. A hidden release is worse
    # than a stale date, so the republish gets one more try after GitHub has had a minute to recover.
    for delay in (REPUBLISH_DELAY, None):
        try:
            gh("release", "edit", TAG, "--repo", repository, "--draft=false", "--prerelease", "--latest=false")
            break
        except subprocess.CalledProcessError:
            if delay is None:
                raise
            print(f"{TAG}: republish failed; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
    state = json.loads(gh("release", "view", TAG, "--repo", repository, "--json", "isDraft,publishedAt"))
    if state["isDraft"]:
        raise RuntimeError(f"{TAG} is still a draft after its date refresh; it is hidden from users")
    if state["publishedAt"] == before:
        print(f"{TAG}: GitHub kept the release date {before}", file=sys.stderr)
    else:
        print(f"{TAG}: release date refreshed {before} -> {state['publishedAt']}")


def publish(folder, notes, repository):
    revision = validate(folder)
    # A queued older run must never replace a newer standard revision's RA release.
    current = json.loads(gh("api", f"repos/{repository}/git/ref/tags/rolling"))["object"]["sha"]
    if current != revision:
        raise ValueError("standard rolling revision changed; refusing stale RA publication")
    releases = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"))
    existing = next((release for page in releases for release in page if release["tag_name"] == TAG), None)
    assets = sorted(folder.iterdir())
    title = "RetroAchievements"
    with tempfile.TemporaryDirectory() as backup:
        if existing:
            # Back up every clobbered name before mutation. Restore all of them,
            # including successfully uploaded earlier files, if any upload fails.
            previous = {asset["name"] for asset in existing["assets"]}
            replaced = sorted(previous & {asset.name for asset in assets})
            for name in replaced:
                gh("release", "download", TAG, "--repo", repository, "--pattern", name, "--dir", backup)
            try:
                for asset in assets:
                    gh("release", "upload", TAG, str(asset), "--repo", repository, "--clobber")
                gh("release", "edit", TAG, "--repo", repository, "--title", title,
                   "--notes-file", str(notes), "--latest=false", "--prerelease", "--draft=false")
            except subprocess.CalledProcessError:
                for name in replaced:
                    gh("release", "upload", TAG, str(Path(backup) / name), "--repo", repository, "--clobber")
                # Keep the previous full kits and tag; cleanup is only after success.
                raise
            for name in sorted(previous - {asset.name for asset in assets}):
                # The complete new set is already published. A stale extra file left by a failed delete
                # is harmless and the next publication removes it; it must not skip the tag update.
                try:
                    gh("release", "delete-asset", TAG, name, "--repo", repository, "--yes")
                except subprocess.CalledProcessError:
                    print(f"warning: could not delete stale asset {name}", file=sys.stderr)
            refresh_release_date(repository)  # a first publication below is already dated now
        else:
            # Draft first: users cannot see a partial first publication.
            gh("release", "create", TAG, *map(str, assets), "--repo", repository,
               "--target", revision, "--title", title, "--notes-file", str(notes),
               "--draft", "--prerelease", "--latest=false")
            gh("release", "edit", TAG, "--repo", repository, "--draft=false", "--latest=false")
        gh("api", "--method", "PATCH", f"repos/{repository}/git/refs/tags/{TAG}",
           "-f", f"sha={revision}", "-F", "force=true")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    publish(args.assets, args.notes, args.repository)


if __name__ == "__main__":
    main()
