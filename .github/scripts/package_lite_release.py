#!/usr/bin/env python3
"""Assemble the rolling-lite channel: one RiptOPLite download per game device (docs/RIPTOPLITE.md).

* RIPTOPLITE-<DEVICE>.ELF -- RiptOPL Korium with only that device's drivers (Makefile RIPTOPLITE=<device>).
  A bare ELF: it needs nothing the Korium kit does not already put on the device.
* RIPTOPLITE-RA-<DEVICE>-<version>.zip -- the RetroAchievements edition, the same way. RetroAchievements
  needs files outside the loader (ORBIT's Neutrino RA runtime, which replaces upstream Neutrino for every
  RA launch, and the PC companion link), so each RA download is a ZIP carrying them, copied from the
  verified Korium RetroAchievements kit of the same revision.

Mirrors NathanNeurotic/RiptOPL tools/publish_lite.py; the device list mirrors its tools/lite_devices.py.
"""
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAG = "rolling-lite"
# The Makefile's LITE_DEVICES, with each download's title.
DEVICES = {"usb": "USB", "mx4sio": "MX4SIO", "ilink": "ILINK", "hdd": "HDD", "smb": "SMB",
           "udpbd": "UDPBD", "udpfs": "UDPFS", "mmce": "MMCE"}
# What an RA lite ZIP takes from the RA kit besides everything under neutrino/.
RA_KIT_FILES = ("xeRAbora.url", "LICENSE-MBEDTLS.txt")
LIBSMB2_LICENCE = ROOT / "modules/network/smb2man/libsmb2/LICENCE-LGPL-2.1.txt"
ISSUES = "https://github.com/NathanNeurotic/Open-PS2-Loader/issues"
MAX_ELF = 6291456

RA_README = """RiptOPLite RetroAchievements {title}, {version}
{underline}

RiptOPL RetroAchievements (Korium theme) with only the {title} game drivers, for consoles that play
from {title} alone. MMCE and network modules stay in every RiptOPLite build, and so does everything
RetroAchievements uses on any device: the in-game network modules, the RA telemetry modules, the SMB
share drivers the achievements page reads from, and the Disc page.

What is in this ZIP
- {elf}: the loader. Put it where you start loaders from (for example APPS/APP_RIPTOPL-RA/).
- neutrino/: ORBIT's Neutrino RA runtime. RetroAchievements needs it for every Neutrino launch; it
  replaces upstream Neutrino. Copy the folder to the root of the device your games are on, where the
  RetroAchievements install kit puts it.
- xeRAbora.url: the PC companion RetroAchievements reports to.
- LICENSE, CREDITS and the LICENSE-*.txt files: the licences of RiptOPL and of the code this loader
  embeds (mbedTLS, libsmb2), and ORBIT's runtime (neutrino/LICENSE).

This build carries no drivers for other devices. It reads its settings where the full loader keeps
them, unless that is a device it has no drivers for; a memory card or a USB stick always works. It
does not change the settings of other devices that the full loader saved in the same file.

Problems: {issues}
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def elf_name(device, ra=False):
    return f"RIPTOPLITE-{'RA-' if ra else ''}{DEVICES[device]}.ELF"


def zip_name(device, version):
    return f"RIPTOPLITE-RA-{DEVICES[device]}-{version}.zip"


def expected_assets(version):
    names = {"LICENSE-LIBSMB2.txt"}
    for device in DEVICES:
        names |= {elf_name(device), zip_name(device, version)}
    return names


def check_build(folder, device, ra, revision, korium_revision):
    """One matrix build: its BUILD.json must name this device, flavour and frozen source."""
    record = json.loads((folder / "BUILD.json").read_text())
    elf = (folder / "RIPTOPLITE.ELF").read_bytes()
    if (record.get("revision") != revision or record.get("korium_revision") != korium_revision
            or record.get("device") != device or record.get("ra") is not ra or record.get("theme") != "Korium"
            or record.get("sdk") != "OFFICIALROLLING" or record.get("elf_sha256") != digest(elf)
            or not 0 < len(elf) <= MAX_ELF):
        raise ValueError(f"invalid lite build: {device} ra={ra}")
    return elf, record


def ra_kit_files(kit_zip):
    """neutrino/ and RA_KIT_FILES from the Korium RA kit, checked for ORBIT's runtime."""
    with zipfile.ZipFile(kit_zip) as kit:
        if kit.testzip():
            raise ValueError("RA kit is damaged")
        names = [n for n in kit.namelist() if not n.endswith("/")]
        runtime = sorted(n for n in names if n.startswith("neutrino/"))
        if "neutrino/neutrino.elf" not in runtime or "neutrino/modules/raagent.irx" not in runtime:
            raise ValueError("RA kit carries no ORBIT runtime")
        if b"-ra=<file>" not in kit.read("neutrino/neutrino.elf"):
            raise ValueError("RA kit's Neutrino lacks the RA handoff")
        return {name: kit.read(name) for name in (*runtime, *RA_KIT_FILES)}


def package(builds, ra_release, output, revision, preview=False):
    """The builds are of `revision`; a published set must be the revision of the published RA kit it
    takes ORBIT's runtime from. A PR preview builds the PR against the published RA kit."""
    ra = json.loads((ra_release / "RA-RELEASE.json").read_text())
    korium_revision, version = ra["korium_revision"], ra["version"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("expected a full source SHA")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
        raise ValueError("unsafe version")
    if not preview and (ra.get("preview", True) or ra["revision"] != revision):
        raise ValueError("a published lite release needs the published RA release of the same revision")
    kit = ra_release / f"RIPTOPL-RetroAchievements-Korium-{version}.zip"
    if digest(kit.read_bytes()) != ra["assets"][kit.name]:
        raise ValueError("RA kit digest mismatch")
    extras = ra_kit_files(kit)
    extras["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    extras["CREDITS"] = (ROOT / "CREDITS").read_bytes()
    extras["LICENSE-LIBSMB2.txt"] = LIBSMB2_LICENCE.read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty")
    records = {}
    for device, title in DEVICES.items():
        elf, record = check_build(builds / f"lite-{device}", device, False, revision, korium_revision)
        (output / elf_name(device)).write_bytes(elf)
        records[elf_name(device)] = record

        elf, record = check_build(builds / f"lite-ra-{device}", device, True, revision, korium_revision)
        name = elf_name(device, ra=True)
        heading = f"RiptOPLite RetroAchievements {title}, {version}"
        readme = RA_README.format(title=title, version=version, elf=name, issues=ISSUES, underline="=" * len(heading))
        target = output / zip_name(device, version)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(name, elf)
            bundle.writestr("BUILD.json", json.dumps(record, indent=2) + "\n")
            bundle.writestr("README.txt", readme.replace("\n", "\r\n"))
            for entry, data in sorted(extras.items()):
                bundle.writestr(entry, data)
        records[target.name] = record
    shutil.copyfile(LIBSMB2_LICENCE, output / "LICENSE-LIBSMB2.txt")
    assets = {p.name: digest(p.read_bytes()) for p in sorted(output.iterdir())}
    if set(assets) != expected_assets(version):
        raise ValueError("unexpected lite asset set")
    release = dict(revision=revision, korium_revision=korium_revision, version=version, preview=preview,
                   ra_kit_sha256=ra["assets"][kit.name], builds=records, assets=assets)
    (output / "LITE-RELEASE.json").write_text(json.dumps(release, indent=2) + "\n")
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{digest(p.read_bytes())}  {p.name}\n" for p in sorted(output.iterdir()) if p.name != "SHA256SUMS.txt"))
    return release


def release_notes(release, repository):
    base = f"https://github.com/{repository}"
    downloads = f"{base}/releases/download/{TAG}"
    revision, version = release["revision"], release["version"]
    rows = "".join(
        f"| {title} | [{elf_name(device)}]({downloads}/{elf_name(device)}) | "
        f"[{zip_name(device, version)}]({downloads}/{zip_name(device, version)}) |\n"
        for device, title in DEVICES.items())
    return (
        f"**RiptOPLite** `{version}` - Development build [{revision[:8]}]({base}/commit/{revision}).\n\n"
        "One loader per game device, for consoles that only play from one. Each is RiptOPL Korium with "
        "that device's drivers alone, so it is smaller; Memory Card (MMCE) and network modules stay in "
        "every build. HDD covers both APA and exFAT drives and DESR DVR games; UDPFS covers Files and IMG.\n\n"
        "## Downloads\n\n"
        "| Device | Korium | RetroAchievements |\n|---|---|---|\n" + rows +
        "\nThe Korium ELFs replace RIPTOPL.ELF in an existing install. RetroAchievements needs files outside "
        "the loader (ORBIT's Neutrino RA runtime), so each RA download is a ZIP that carries them; its "
        "README says where they go.\n\n"
        "A RiptOPLite loader reads its settings where the full loader keeps them, unless that is a device it "
        "has no drivers for; a memory card or a USB stick always works. It does not change the device "
        "settings the full loader saved in the same file.\n\n"
        "Built from the same revision as [rolling-korium](" + base + "/releases/tag/rolling-korium) and "
        "[rolling-ra](" + base + "/releases/tag/rolling-ra). Not tested on hardware by the maintainers "
        "before publication; report problems in [Issues](" + ISSUES + ").\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builds", type=Path, required=True, help="lite-<device> and lite-ra-<device> build folders")
    parser.add_argument("--ra-release", type=Path, required=True, help="the RA release folder (RA-RELEASE.json + kits)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    release = package(args.builds, args.ra_release, args.output, args.revision, args.preview)
    args.notes.write_text(release_notes(release, args.repository))


if __name__ == "__main__":
    main()
