#!/usr/bin/env python3
"""Verify every payload shipped from POPS against its checked-in manifest."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


EXCLUDED_MANIFEST_FILES = {"POPS/PROVENANCE.md", "POPS/provenance.json"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the checkout containing this script)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / "POPS/provenance.json"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: cannot read {manifest_path}: {error}", file=sys.stderr)
        return 1

    errors = []
    entries = manifest.get("files")
    if manifest.get("schemaVersion") != 1 or not isinstance(entries, list):
        errors.append("manifest must use schemaVersion 1 and contain a files array")
        entries = []

    expected = set()
    for entry in entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative.startswith("POPS/"):
            errors.append(f"invalid manifest path: {relative!r}")
            continue
        if relative in expected:
            errors.append(f"duplicate manifest path: {relative}")
            continue
        expected.add(relative)

        path = root / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
            continue
        actual_size = path.stat().st_size
        if actual_size != entry.get("bytes"):
            errors.append(
                f"size mismatch: {relative}: expected {entry.get('bytes')}, got {actual_size}"
            )
        actual_hash = sha256(path)
        if actual_hash != entry.get("sha256"):
            errors.append(
                f"sha256 mismatch: {relative}: expected {entry.get('sha256')}, got {actual_hash}"
            )

    pops_root = root / "POPS"
    actual = {
        path.relative_to(root).as_posix()
        for path in pops_root.rglob("*")
        if path.is_file()
    } - EXCLUDED_MANIFEST_FILES
    for relative in sorted(actual - expected):
        errors.append(f"unexpected unmanifested file: {relative}")
    for relative in sorted(expected - actual):
        if (root / relative).is_file():
            errors.append(f"manifested path was excluded unexpectedly: {relative}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Verified {len(expected)} POPS payloads against {manifest_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
