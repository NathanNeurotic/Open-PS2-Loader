#!/usr/bin/env python3
"""Publish a verified rolling-lite asset set (package_lite_release.py). Never Latest; never touches
another release. Follows publish_ra_release.py: back up what it replaces, restore on failure."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import package_lite_release as lite
from publish_ra_release import gh, refresh_release_date

TAG = lite.TAG


def validate(folder):
    manifest = json.loads((folder / "LITE-RELEASE.json").read_text())
    if manifest.get("preview", True):
        raise ValueError("preview packages cannot be published")
    version, revision = manifest["version"], manifest["revision"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("unsafe version or revision")
    required = lite.expected_assets(version)
    if set(manifest["assets"]) != required:
        raise ValueError("incomplete or unexpected lite asset set")
    if {file.name for file in folder.iterdir()} != required | {"LITE-RELEASE.json", "SHA256SUMS.txt"}:
        raise ValueError("unexpected publication files")
    for name, expected in manifest["assets"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"release digest mismatch: {name}")
    sums = "".join(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
                   for file in sorted(folder.iterdir()) if file.name != "SHA256SUMS.txt")
    if (folder / "SHA256SUMS.txt").read_text() != sums:
        raise ValueError("release checksum manifest mismatch")
    return revision


def publish(folder, notes, repository):
    revision = validate(folder)
    # A queued older run must never replace a newer revision's lite release.
    for tag in ("rolling", "rolling-ra"):
        current = json.loads(gh("api", f"repos/{repository}/git/ref/tags/{tag}"))["object"]["sha"]
        if current != revision:
            raise ValueError(f"{tag} moved on from {revision}; refusing stale lite publication")
    releases = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"))
    existing = next((release for page in releases for release in page if release["tag_name"] == TAG), None)
    assets = sorted(folder.iterdir())
    title = "RiptOPLite"
    with tempfile.TemporaryDirectory() as backup:
        if existing:
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
                raise
            for name in sorted(previous - {asset.name for asset in assets}):
                try:
                    gh("release", "delete-asset", TAG, name, "--repo", repository, "--yes")
                except subprocess.CalledProcessError:
                    print(f"warning: could not delete stale asset {name}", file=sys.stderr)
            refresh_release_date(repository, TAG)
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
