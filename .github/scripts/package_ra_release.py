#!/usr/bin/env python3
"""Assemble both RA themes from one standard kit and exact-revision RA builds."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

import package_orbit_neutrino as orbit
import package_release_app as app

THEMES = ("inceBtion", "Korium")
SDKS = ("OFFICIALROLLING", "PS2DEVROLLING", "PS2DEVPINNED")
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def standard_asset(assets):
    names = [asset["name"] for asset in assets
             if re.fullmatch(r"RIPTOPL-v?[0-9][A-Za-z0-9._+-]*\.zip", asset["name"])
             and not asset["name"].endswith("-src.zip")]
    if len(names) != 1:
        raise ValueError(f"expected one standard install kit, found {names}")
    return names[0]


def extract(archive, destination):
    with zipfile.ZipFile(archive) as source:
        seen = set()
        for entry in source.infolist():
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.orig_filename
                    or ":" in entry.filename or entry.filename in seen
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("unsafe or duplicate shared-kit entry")
            seen.add(entry.filename)
        source.extractall(destination)


def validate_builds(builds, revision, korium_revision):
    records = []
    for theme in THEMES:
        for sdk in SDKS:
            folder = builds / f"{theme}-{sdk}"
            manifest = json.loads((folder / "BUILD.json").read_text())
            if (manifest["revision"] != revision or manifest["theme"] != theme
                    or manifest["sdk"] != sdk or manifest["korium_revision"] != korium_revision):
                raise ValueError("mixed source/theme revisions in RA builds")
            expected = [1] if sdk == "OFFICIALROLLING" else [0, 1]
            if sorted(int(pad) for pad in manifest["elf_sha256"]) != expected:
                raise ValueError("missing RA controller variant")
            for pad in expected:
                elf = folder / f"pademu{pad}.ELF"
                if (not 0 < elf.stat().st_size <= 6291456 or elf.read_bytes()[:4] != b"\x7fELF"
                        or digest(elf) != manifest["elf_sha256"][str(pad)]):
                    raise ValueError("invalid or changed RA build")
            records.append(manifest)
    patches = [(builds / f"Korium-{sdk}/Korium.patch").read_bytes() for sdk in SDKS]
    if not patches[0] or any(patch != patches[0] for patch in patches):
        raise ValueError("Korium builds used different theme patches")
    return records


def package(args):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", args.version):
        raise ValueError("unsafe version")
    for revision in (args.revision, args.korium_revision):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("expected full source SHA")
    shared_manifest = json.loads(args.standard_kit.with_name("INPUT.json").read_text())
    if shared_manifest["sha256"] != digest(args.standard_kit):
        raise ValueError("changed shared kit")
    if not args.preview and shared_manifest["revision"] != args.revision:
        raise ValueError("published shared kit must match RA source revision")
    records = validate_builds(args.builds, args.revision, args.korium_revision)
    pin = json.loads(orbit.PIN.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise ValueError("output directory must be empty")
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        shared = temporary / "shared"
        extract(args.standard_kit, shared)
        app.verify(argparse.Namespace(zip=args.standard_kit,
            source_elf=shared / "APPS/APP_RIPTOPL/RIPTOPL.ELF",
            app_name="APP_RIPTOPL", elf_name="RIPTOPL.ELF", ra=False))
        archive = args.orbit_archive or temporary / pin["asset"]
        if args.orbit_archive is None:
            url = f"https://github.com/{pin['repository']}/releases/download/{pin['tag']}/{pin['asset']}"
            with urllib.request.urlopen(url, timeout=60) as response:
                archive.write_bytes(response.read())
        for theme in THEMES:
            kit = temporary / theme
            shutil.copytree(shared, kit)
            shutil.rmtree(kit / "APPS")
            shutil.rmtree(kit / "ART")
            for psu in kit.glob("*.psu"):
                psu.unlink()
            shutil.copyfile(ROOT / "pc/xeRAbora.url", kit / "xeRAbora.url")
            orbit.stage(archive, kit / "neutrino", pin)
            for sdk in SDKS:
                for pad in ([1] if sdk == "OFFICIALROLLING" else [0, 1]):
                    elf = args.builds / f"{theme}-{sdk}" / f"pademu{pad}.ELF"
                    label = sdk.removeprefix("PS2DEV")
                    name = "APP_RIPTOPL-RA" if sdk == "OFFICIALROLLING" else f"APP_RIPTOPL-RA-{label}" + ("-nopademu" if pad == 0 else "")
                    app.stage(argparse.Namespace(package=kit, source_elf=elf,
                        app_name=name, elf_name="RIPTOPL-RA.ELF",
                        title=f"[APP] RiptOPL RA {theme}", pbt_title=f"[APP] RiptOPL RA {theme}",
                        version=args.version, flavour=f"{sdk} PADEMU{pad} {theme}",
                        channel="RetroAchievements", description="Experimental RetroAchievements loader"))
                    if name != "APP_RIPTOPL-RA":
                        (kit / f"{name}.psu").unlink()
            main = args.builds / f"{theme}-OFFICIALROLLING/pademu1.ELF"
            manifest = dict(revision=args.revision, korium_revision=args.korium_revision,
                theme=theme, version=args.version, orbit=pin, builds=records, preview=args.preview,
                shared_kit_sha256=digest(args.standard_kit))
            (kit / "RA-BUILD.json").write_text(json.dumps(manifest, indent=2) + "\n")
            name = f"RIPTOPL-RetroAchievements-{theme}-{args.version}.zip"
            target = args.output / name
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
                for file in sorted(kit.rglob("*")):
                    if file.is_file():
                        output.write(file, file.relative_to(kit).as_posix())
            app.verify(argparse.Namespace(zip=target, source_elf=main,
                app_name="APP_RIPTOPL-RA", elf_name="RIPTOPL-RA.ELF", ra=True))
            shutil.copyfile(main, args.output / f"RIPTOPL-RA-{theme}.ELF")
            shutil.copyfile(kit / "APP_RIPTOPL-RA.psu", args.output / f"APP_RIPTOPL-RA-{theme}.psu")
        source = args.output / f"RIPTOPL-RetroAchievements-{args.version}-src.zip"
        subprocess.run(["git", "archive", "--format=zip", f"--output={source.resolve()}", args.revision], cwd=ROOT, check=True)
        # Include the actual reviewed theme patch alongside the shared source snapshot.
        with zipfile.ZipFile(source, "a", zipfile.ZIP_DEFLATED) as output:
            output.write(args.builds / "Korium-OFFICIALROLLING/Korium.patch", "RA-Korium-theme.patch")
        release = dict(revision=args.revision, korium_revision=args.korium_revision,
            version=args.version, orbit=pin, themes=list(THEMES), builds=records, preview=args.preview,
            korium_patch_sha256=digest(args.builds / "Korium-OFFICIALROLLING/Korium.patch"),
            assets={file.name: digest(file) for file in sorted(args.output.iterdir())})
        (args.output / "RA-RELEASE.json").write_text(json.dumps(release, indent=2) + "\n")
        (args.output / "SHA256SUMS.txt").write_text("".join(
            f"{digest(file)}  {file.name}\n" for file in sorted(args.output.iterdir()) if file.name != "SHA256SUMS.txt"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("standard-kit", "builds", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--orbit-archive", type=Path)
    parser.add_argument("--preview", action="store_true")
    for name in ("revision", "korium-revision", "version"):
        parser.add_argument("--" + name, required=True)
    package(parser.parse_args())


if __name__ == "__main__":
    main()
