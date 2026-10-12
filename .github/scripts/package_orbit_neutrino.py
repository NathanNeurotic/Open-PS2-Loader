#!/usr/bin/env python3
"""Stage the pinned, unmodified ORBIT Neutrino runtime for the RA package only."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "third_party/orbit-neutrino/release.json"


def stage(archive: Path, destination: Path, pin: dict) -> None:
    if destination.name != "neutrino" or destination.is_symlink() or destination.resolve().name != "neutrino":
        raise ValueError("destination must be the package's neutrino directory")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("ORBIT release digest mismatch")
    with zipfile.ZipFile(archive) as source:
        payload = {}
        for entry in source.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.orig_filename:
                raise ValueError("unsafe ORBIT archive path")
            if entry.is_dir() or len(path.parts) < 3 or path.parts[1] != "neutrino":
                continue
            relative = PurePosixPath(*path.parts[2:]).as_posix()
            if relative in payload:
                raise ValueError("duplicate ORBIT runtime entry")
            payload[relative] = source.read(entry)
        for name in ("neutrino.elf", "modules/ee_core.elf", "modules/raagent.irx",
                     "config/system.toml", "config/bsd-udpfs.toml", "LICENSE"):
            if not payload.get(name):
                raise ValueError(f"missing ORBIT runtime entry: {name}")
        if b"-ra=<file>" not in payload["neutrino.elf"]:
            raise ValueError("ORBIT loader lacks the expected RA handoff")
    # Validate everything before modifying the package. Preserve our UDPFS block config.
    extra = destination / "config/bsd-udpfsbd.toml"
    if not extra.is_file():
        raise ValueError("missing required config/bsd-udpfsbd.toml before ORBIT staging")
    udpfsbd = extra.read_bytes()
    if destination.exists():
        shutil.rmtree(destination)
    for name, data in payload.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    extra.write_bytes(udpfsbd)
    (destination / "ORBIT-RA.json").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    (destination / "ORBIT-RA.txt").write_text(
        "RiptOPL ORBIT RA handoff v1\n"
        "ORBIT Neutrino RA runtime by Daniel (danielnuld), based on Neutrino by Maximus32\n"
        "and xeRAbora's protocol by hacan359. AFL-3.0; see LICENSE.\n"
        f"Source: https://github.com/{pin['repository']}/tree/{pin['source_commit']}/third_party/neutrino-igr\n"
        "Pinned release and archive SHA-256: see ORBIT-RA.json.\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    archive = args.archive
    if archive is None:
        archive = args.destination.parent / pin["asset"]
        url = f"https://github.com/{pin['repository']}/releases/download/{pin['tag']}/{pin['asset']}"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read())
    stage(archive, args.destination, pin)
    print(f"Staged ORBIT Neutrino {pin['tag']} for the RA package")


if __name__ == "__main__":
    main()
