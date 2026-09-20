#!/usr/bin/env python3
"""Stage an installable RiptOPL app and its single-folder memory-card PSU.

The committed Example is a reference for artwork and app companions. Its ELF is
an empty placeholder; only a checked build output may enter a release package.
The PSU record layout follows techwritescode's PSUManager core, preserved in
third_party/PSUManager. A commit timestamp is used for reproducible PSU dates
rather than the packager's wall clock. The vendored reader checks both outputs.
"""

import argparse
import datetime as dt
import hashlib
import re
import shutil
import struct
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "Example" / "APP_RIPTOPL-OFFICIALROLLING-VERSION.ZIP"
APP_TEMPLATE = EXAMPLE / "APPS" / "APP_RIPTOPL"
ART_TEMPLATE = EXAMPLE / "ART"
APP_COMPANIONS = (
    "APPINFO.PBT",
    "title.cfg",
    "bgm.ogg",
    "copy.icn",
    "del.icn",
    "icon.sys",
    "list.icn",
)
ART_SUFFIXES = ("BG", "COV", "COV2", "ICO", "LAB", "LGO", "SCR", "SCR2")
BDMA_SUFFIXES = ("usbexfat", "mx4sio", "mmce", "ata", "ilink")
PSU_ENTRY = struct.Struct("<HHI8sII8sI28s448s")
PSU_DIR_MODE = 0x8027
PSU_FILE_MODE = 0x8017
PSU_CLUSTER = 1024
MAX_MC_NAME = 31


def require_name(name: str) -> None:
    if not 1 <= len(name) <= MAX_MC_NAME or not name.isascii() or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError(f"invalid PS2 memory-card name: {name!r}")


def require_value(value: str) -> None:
    if not value or any(c in value for c in ('"', "\r", "\n")):
        raise ValueError(f"invalid metadata value: {value!r}")


def replace_cfg_fields(text: str, values: dict[str, str]) -> str:
    seen = {key: 0 for key in values}
    lines = []
    for line in text.splitlines():
        key, separator, _ = line.partition("=")
        if separator and key in values:
            seen[key] += 1
            line = f"{key}={values[key]}"
        lines.append(line)
    if any(count != 1 for count in seen.values()):
        raise ValueError(f"title.cfg template keys are missing or repeated: {seen}")
    return "\n".join(lines) + "\n"


def replace_pbt_fields(text: str, values: dict[str, str]) -> str:
    seen = {key: 0 for key in values}
    lines = []
    for line in text.splitlines():
        match = re.fullmatch(r'SET "([A-Z_]+)" "[^"]*"', line)
        if match and match.group(1) in values:
            key = match.group(1)
            seen[key] += 1
            line = f'SET "{key}" "{values[key]}"'
        lines.append(line)
    if any(count != 1 for count in seen.values()):
        raise ValueError(f"APPINFO.PBT template keys are missing or repeated: {seen}")
    return "\n".join(lines) + "\n"


def psu_date(timestamp: int) -> bytes:
    date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
    if not 2000 <= date.year <= 2099:
        raise ValueError("PSU timestamp year must be between 2000 and 2099")
    return struct.pack("<BBBBBBH", 0, date.second, date.minute, date.hour, date.day, date.month, date.year)


def psu_entry(mode: int, size: int, date: bytes, name: str) -> bytes:
    if name not in (".", ".."):
        require_name(name)
    name_bytes = name.encode("ascii")
    return PSU_ENTRY.pack(mode, 0, size, date, 0, 0, date, 0, bytes(28), name_bytes.ljust(448, b"\0"))


def build_psu(app_dir: Path, output: Path, timestamp: int) -> None:
    require_name(app_dir.name)
    files = sorted((path for path in app_dir.iterdir() if path.is_file()), key=lambda path: path.name)
    if len(files) != len(APP_COMPANIONS) + 1:
        raise ValueError(f"unexpected direct app files in {app_dir}")
    date = psu_date(timestamp)
    with output.open("wb") as out:
        out.write(psu_entry(PSU_DIR_MODE, len(files) + 2, date, app_dir.name))
        out.write(psu_entry(PSU_DIR_MODE, 0, date, "."))
        out.write(psu_entry(PSU_DIR_MODE, 0, date, ".."))
        for path in files:
            require_name(path.name)
            data = path.read_bytes()
            out.write(psu_entry(PSU_FILE_MODE, len(data), date, path.name))
            out.write(data)
            out.write(bytes((-len(data)) % PSU_CLUSTER))
    if output.stat().st_size >= 8 * 1024 * 1024:
        raise ValueError(f"{output.name} would not fit an 8 MB memory card")


def inspect_psu(data: bytes) -> tuple[str, dict[str, bytes]]:
    if len(data) < 3 * PSU_ENTRY.size:
        raise ValueError("truncated PSU header")
    root, dot, dotdot = (PSU_ENTRY.unpack_from(data, offset) for offset in (0, 512, 1024))
    def get_name(record: tuple) -> str:
        return record[-1].split(b"\0", 1)[0].decode("ascii")
    name = get_name(root)
    require_name(name)
    if root[0] != PSU_DIR_MODE or get_name(dot) != "." or get_name(dotdot) != ".." or root[2] < 2:
        raise ValueError("invalid PSU directory records")
    position = 3 * PSU_ENTRY.size
    files = {}
    for _ in range(root[2] - 2):
        if position + PSU_ENTRY.size > len(data):
            raise ValueError("truncated PSU file record")
        entry = PSU_ENTRY.unpack_from(data, position)
        filename = get_name(entry)
        require_name(filename)
        if entry[0] != PSU_FILE_MODE or filename in files:
            raise ValueError("invalid or duplicate PSU file entry")
        start = position + PSU_ENTRY.size
        end = start + entry[2]
        if end > len(data):
            raise ValueError("truncated PSU file payload")
        files[filename] = data[start:end]
        position = start + ((entry[2] + PSU_CLUSTER - 1) // PSU_CLUSTER) * PSU_CLUSTER
    if position != len(data):
        raise ValueError("unexpected bytes after PSU payload")
    return name, files


def stage(args: argparse.Namespace) -> None:
    for name in (args.app_name, args.elf_name):
        require_name(name)
    for value in (args.title, args.pbt_title, args.version, args.flavour, args.channel, args.description):
        require_value(value)
    elf = Path(args.source_elf)
    if not elf.is_file() or elf.stat().st_size == 0 or elf.read_bytes()[:4] != b"\x7fELF":
        raise ValueError(f"missing, empty, or invalid build ELF: {elf}")
    package = Path(args.package)
    app_dir = package / "APPS" / args.app_name
    art_dir = package / "ART"
    app_dir.mkdir(parents=True, exist_ok=True)
    art_dir.mkdir(parents=True, exist_ok=True)
    for filename in APP_COMPANIONS:
        source = APP_TEMPLATE / filename
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"missing example companion: {source}")
        if filename not in ("APPINFO.PBT", "title.cfg"):
            shutil.copyfile(source, app_dir / filename)
    if (app_dir / "icon.sys").read_bytes()[:4] != b"PS2D":
        raise ValueError("invalid icon.sys in example")
    if (app_dir / "bgm.ogg").read_bytes()[:4] != b"OggS":
        raise ValueError("invalid bgm.ogg in example")
    shutil.copyfile(elf, app_dir / args.elf_name)
    cfg = replace_cfg_fields((APP_TEMPLATE / "title.cfg").read_text(encoding="utf-8"), {
        "title": args.title,
        "boot": args.elf_name,
        "Title": f"{args.title} {args.version} {args.flavour}",
        "Version": f"{args.version} {args.flavour}",
        "Release": args.channel,
        "Description": args.description,
        "Notes": "Companion folders are supplied in the release ZIP",
    })
    (app_dir / "title.cfg").write_bytes(cfg.encode("utf-8"))
    pbt = replace_pbt_fields((APP_TEMPLATE / "APPINFO.PBT").read_text(encoding="utf-8"), {
        "TITLE": args.pbt_title,
        "VERSION": args.version,
        "DESC": args.description,
        "ELF": args.elf_name,
        "SAS": args.app_name,
    })
    (app_dir / "APPINFO.PBT").write_bytes(pbt.encode("utf-8"))
    for suffix in ART_SUFFIXES:
        source = ART_TEMPLATE / f"RIPTOPL.ELF_{suffix}.png"
        if not source.is_file() or source.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"missing or invalid app artwork: {source}")
        shutil.copyfile(source, art_dir / f"{args.elf_name}_{suffix}.png")
    psu = package / f"{args.app_name}.psu"
    build_psu(app_dir, psu, args.timestamp)
    psu_name, psu_files = inspect_psu(psu.read_bytes())
    if psu_name != args.app_name or psu_files != {p.name: p.read_bytes() for p in app_dir.iterdir() if p.is_file()}:
        raise ValueError("staged PSU differs from its direct app folder")
    print(f"Staged {app_dir} ({args.flavour}); {psu.name} ({psu.stat().st_size} bytes)")


def verify(args: argparse.Namespace) -> None:
    archive = Path(args.zip)
    source_elf = Path(args.source_elf).read_bytes()
    if not source_elf.startswith(b"\x7fELF"):
        raise ValueError("selected build is not an ELF")
    with zipfile.ZipFile(archive) as package:
        bad = package.testzip()
        if bad:
            raise ValueError(f"corrupt ZIP entry: {bad}")
        files = [info.filename for info in package.infolist() if not info.is_dir()]
        if len(files) != len(set(files)):
            raise ValueError("duplicate ZIP filenames")
        names = set(files)
        misplaced_apps = sorted(name for name in names if re.match(r"^APP_RIPTOPL[^/]*/", name))
        if misplaced_apps:
            raise ValueError(
                "release app folders must live under APPS/: "
                + ", ".join(misplaced_apps[:8])
            )
        required = {
            f"APPS/{args.app_name}/{args.elf_name}",
            f"{args.app_name}.psu",
            "POPS/POPSTARTER.ELF",
            "POPS/CHEATS.TXT",
            "POPS/IGR_BG.TM2",
            "POPS/IGR_NO.TM2",
            "POPS/IGR_YES.TM2",
            "POPS/POPSTARTER.KELF",
            "POPS/TROJAN_7.BIN",
            "EMBER/ember.elf",
            "EMBER/LICENSE-BETA.txt",
            "EMBER/games/Per-Game-Folder/GAME FILES",
            "neutrino/neutrino.elf",
            "neutrino/config/bsd-udpfsbd.toml",
            "neutrino/config/bsd-udpfs.toml",
            "neutrino/config/system.toml",
            "PS2-Servers.url",
            "android-udpfs-server.url",
            "OrbitPS2-Manager.url",
            "OPL-PS1-AIO-Converter-GUI.url",
            "PS2RD-CHT-Manager.url",
        }
        required.update(f"APPS/{args.app_name}/{name}" for name in APP_COMPANIONS)
        required.update(f"ART/{args.elf_name}_{suffix}.png" for suffix in ART_SUFFIXES)
        required.update(f"POPS/{module}.{suffix}" for suffix in BDMA_SUFFIXES for module in ("usbd.irx", "usbhdfsd.irx"))
        if args.ra:
            required.add("xeRAbora.url")
        required.update(f"POPS/POPSTARTER VERSIONS/{version}/POPSTARTER.ELF" for version in (
            "MAIN", "DEBUG", "USBDELAY", "USBDELAY_DEBUG", "USBDELAY_LONGER_DEBUG"
        ))

        # Every labelled loader choice is an installable app folder, not just a loose ELF.
        # Keep the same metadata companions as the selected APPS/APP_RIPTOPL[/ -RA] folder
        # so users can copy any flavour directly without reconstructing icon/title metadata.
        app_dirs = sorted({
            name.split("/", 2)[1]
            for name in names
            if name.startswith("APPS/")
            and name.count("/") >= 2
            and name.split("/", 2)[1].startswith("APP_RIPTOPL")
        })
        for app_dir in app_dirs:
            prefix = f"APPS/{app_dir}/"
            direct = {
                name[len(prefix):]
                for name in names
                if name.startswith(prefix)
            }
            if any("/" in name for name in direct):
                raise ValueError(f"{app_dir} contains nested paths; app folders must be flat")
            missing_companions = sorted(set(APP_COMPANIONS) - direct)
            if missing_companions:
                raise ValueError(f"{app_dir} missing app metadata: {missing_companions}")
            elf_names = sorted(name for name in direct if name.upper().endswith(".ELF"))
            if len(elf_names) != 1:
                raise ValueError(f"{app_dir} must contain exactly one ELF, found {elf_names}")
            cfg = package.read(prefix + "title.cfg").decode("utf-8")
            pbt = package.read(prefix + "APPINFO.PBT").decode("utf-8")
            elf_name = elf_names[0]
            if f"boot={elf_name}\n" not in cfg or f'SET "ELF" "{elf_name}"' not in pbt:
                raise ValueError(f"{app_dir} metadata does not name its packaged ELF")

        missing = sorted(required - names)
        if missing:
            raise ValueError(f"missing ZIP entries: {missing}")
        for name in required - {"EMBER/games/Per-Game-Folder/GAME FILES"}:
            if not package.getinfo(name).file_size:
                raise ValueError(f"empty required ZIP entry: {name}")
        if "udpfs-server.url" in names:
            raise ValueError("legacy udpfs-server.url remains in the installable ZIP")
        wrong_app = "APP_RIPTOPL" if args.ra else "APP_RIPTOPL-RA"
        if any(name.startswith(f"APPS/{wrong_app}/") for name in names) or f"{wrong_app}.psu" in names:
            raise ValueError("ZIP contains the other edition's installable app")
        wrong_art = "RIPTOPL.ELF" if args.ra else "RIPTOPL-RA.ELF"
        if any(name.startswith(f"ART/{wrong_art}_") for name in names):
            raise ValueError("ZIP contains the other edition's artwork")
        if package.read(f"APPS/{args.app_name}/{args.elf_name}") != source_elf:
            raise ValueError("installed ELF differs from the selected build")
        psu_name, psu_files = inspect_psu(package.read(f"{args.app_name}.psu"))
        app_prefix = f"APPS/{args.app_name}/"
        app_paths = [name for name in names if name.startswith(app_prefix)]
        if any("/" in name[len(app_prefix):] for name in app_paths):
            raise ValueError("installable app contains a subdirectory that cannot enter its PSU")
        app_files = {name[len(app_prefix):]: package.read(name) for name in app_paths}
        if psu_name != args.app_name or psu_files != app_files:
            raise ValueError("PSU content differs from the ZIP app folder")
        cfg = app_files["title.cfg"].decode("utf-8")
        pbt = app_files["APPINFO.PBT"].decode("utf-8")
        if f"boot={args.elf_name}\n" not in cfg or f'SET "ELF" "{args.elf_name}"' not in pbt:
            raise ValueError("app boot metadata does not name the packaged ELF")
    print(f"Verified {archive.name}: full kit, {args.app_name}.psu, {hashlib.sha256(source_elf).hexdigest()[:12]} ELF")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--package", required=True)
    stage_parser.add_argument("--source-elf", required=True)
    stage_parser.add_argument("--app-name", required=True)
    stage_parser.add_argument("--elf-name", required=True)
    stage_parser.add_argument("--title", required=True)
    stage_parser.add_argument("--pbt-title", required=True)
    stage_parser.add_argument("--version", required=True)
    stage_parser.add_argument("--flavour", required=True)
    stage_parser.add_argument("--channel", required=True)
    stage_parser.add_argument("--description", required=True)
    stage_parser.add_argument("--timestamp", required=True, type=int)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--zip", required=True)
    verify_parser.add_argument("--source-elf", required=True)
    verify_parser.add_argument("--app-name", required=True)
    verify_parser.add_argument("--elf-name", required=True)
    verify_parser.add_argument("--ra", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "stage":
            stage(args)
        else:
            verify(args)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        sys.exit(f"release app packaging failed: {exc}")


if __name__ == "__main__":
    main()
