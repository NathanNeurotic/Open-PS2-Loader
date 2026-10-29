#!/usr/bin/env python3
"""End every release ZIP name with the build version.

The download version (asset_version.sh) can carry a channel label after the revision, and the
source snapshot puts "-src" after the version:

    RIPTOPL-v1.2.0-Beta-4420-Korium.zip         -> RIPTOPL-Korium-v1.2.0-Beta-4420.zip
    RIPTOPL-DEBUG-v1.2.0-Beta-4420-Korium.zip   -> RIPTOPL-DEBUG-Korium-v1.2.0-Beta-4420.zip
    RIPTOPL-v1.2.0-Beta-4420-src.zip            -> RIPTOPL-src-v1.2.0-Beta-4420.zip
    RIPTOPL-v1.2.0-Beta-4420.zip                   (already ends with the version)

so the number a tester compares is always the last thing before ".zip". Only the names change: the
version inside the packages, the language-pack folders and the RA kit's provenance stay as built.
SHA256SUMS.txt, when present, is rewritten to the new names. ELFs, PSUs and other files keep theirs.

Usage: version_last.py <assets-dir> --version <download version> [--channel Korium]
"""
import argparse
import re
import sys
from pathlib import Path


def target(name, version, channel=""):
    """The version-last name for one asset, or the name unchanged when it is not a versioned ZIP."""
    if not (name.startswith("RIPTOPL-") and name.endswith(".zip")):
        return name
    # A version without the channel label (a v* tag, the "rolling" fallback) has nothing to move.
    if not channel or not version.endswith("-" + channel):
        channel = ""
    base = version[:-len(channel) - 1] if channel else version
    stem = name[len("RIPTOPL-"):-len(".zip")]
    match = re.fullmatch(r"(?:(?P<kind>[A-Za-z0-9-]+?)-)?" + re.escape(version) + r"(?P<src>-src)?", stem)
    if not match:
        return name
    parts = [match["kind"], "src" if match["src"] else None, channel or None, base]
    return "RIPTOPL-" + "-".join(p for p in parts if p) + ".zip"


def rename(folder, version, channel=""):
    renames = {}
    for path in sorted(folder.iterdir()):
        if path.is_file():
            new = target(path.name, version, channel)
            if new != path.name:
                renames[path.name] = new
    if len(set(renames.values())) != len(renames):
        raise ValueError("two assets would take the same name")
    for old, new in renames.items():
        if (folder / new).exists():
            raise ValueError(f"{new} already exists")
    for old, new in renames.items():
        (folder / old).rename(folder / new)
        print(f"{old} -> {new}")
    sums = folder / "SHA256SUMS.txt"
    if sums.is_file() and renames:
        lines = []
        for line in sums.read_text(encoding="utf-8").splitlines():
            digest, sep, name = line.partition("  ")
            lines.append(digest + sep + renames.get(name, name) if sep else line)
        sums.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return renames


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", default="")
    args = parser.parse_args()
    try:
        rename(args.folder, args.version, args.channel)
    except ValueError as error:
        sys.exit(f"ERROR: {error}")


if __name__ == "__main__":
    main()
