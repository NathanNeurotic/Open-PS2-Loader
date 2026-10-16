#!/usr/bin/env python3
"""Stage the digest-pinned standard Neutrino runtime with the UDPFS ACK repair."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "third_party/neutrino/release.json"
REQUIRED = (
    "neutrino.elf",
    "modules/ee_core.elf",
    "modules/udpfs_fhi.irx",
    "modules/udpfs_bd.irx",
    "modules/udpfs_ioman.irx",
    "config/system.toml",
    "config/bsd-udpfs.toml",
    "version.txt",
)


def stage(archive: Path, destination: Path, pin: dict, sevenzip: str) -> None:
    if destination.exists():
        raise ValueError("standard runtime destination must not already exist")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("standard Neutrino archive digest mismatch")
    license_data = (ROOT / "third_party/neutrino/LICENSE").read_bytes()
    if hashlib.sha256(license_data).hexdigest() != pin["license_sha256"]:
        raise ValueError("standard Neutrino license digest mismatch")
    extra = (ROOT / "neutrino/bsd-udpfsbd.toml").read_bytes()
    if not extra:
        raise ValueError("missing fork-private UDPFS block configuration")
    # Only extract the exact trusted archive; validate it before touching the package.
    with tempfile.TemporaryDirectory(prefix="neutrino-stage-") as temporary:
        runtime = Path(temporary) / "runtime"
        subprocess.run(
            [sevenzip, "x", "-y", f"-o{runtime}", str(archive.resolve())],
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=60,
        )
        for name in REQUIRED:
            if not (runtime / name).is_file() or not (runtime / name).stat().st_size:
                raise ValueError(f"missing standard Neutrino runtime entry: {name}")
        if (runtime / "version.txt").read_text(encoding="utf-8").strip() != pin[
            "version"
        ]:
            raise ValueError("standard Neutrino embedded version mismatch")
        (runtime / "LICENSE").write_bytes(license_data)
        (runtime / "config/bsd-udpfsbd.toml").write_bytes(extra)
        provenance = dict(pin)
        runtime_files = [
            path
            for path in runtime.rglob("*")
            if path.is_file()
            and (
                path.parent == runtime
                or path.relative_to(runtime).parts[0] in ("config", "modules")
            )
        ]
        provenance["runtime_sha256"] = {
            path.relative_to(runtime).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(runtime_files)
        }
        (runtime / "RIPTOPL-STANDARD.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        (runtime / "RIPTOPL-STANDARD.txt").write_text(
            "Standard RiptOPL Neutrino runtime by Maximus32 / rickgaiser. AFL-3.0.\n"
            "Includes Ripto's UDPFS stale-ACK repair in both send paths.\n"
            "Use the complete folder; an OPL ELF update alone does not update Neutrino.\n"
            "Source commits, archive digest and module hashes: RIPTOPL-STANDARD.json.\n"
            "Console acceptance for the reported Tekken Tag failure remains pending.\n",
            encoding="utf-8",
        )
        # The release archive also carries an old PC server. Ship the runtime
        # and its original README, with PS2-Servers supplied by the kit's shortcut.
        destination.mkdir(parents=True)
        for name in ("config", "modules"):
            shutil.copytree(runtime / name, destination / name)
        for name in (
            "neutrino.elf",
            "version.txt",
            "README.md",
            "LICENSE",
            "RIPTOPL-STANDARD.json",
            "RIPTOPL-STANDARD.txt",
        ):
            if (runtime / name).is_file():
                shutil.copy2(runtime / name, destination / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--sevenzip", default=shutil.which("7z") or shutil.which("7za"))
    args = parser.parse_args()
    if not args.sevenzip:
        parser.error("7z or 7za is required")
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="neutrino-download-") as temporary:
        archive = args.archive
        if archive is None:
            archive = Path(temporary) / pin["asset"]
            url = f"https://github.com/{pin['repository']}/releases/download/{pin['tag']}/{pin['asset']}"
            with urllib.request.urlopen(url, timeout=60) as response:
                archive.write_bytes(response.read())
        stage(archive, args.destination, pin, args.sevenzip)
    print(f"Staged standard Neutrino {pin['version']}")


if __name__ == "__main__":
    main()
