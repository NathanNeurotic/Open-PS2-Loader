#!/usr/bin/env python3
"""Pack the rolling release's bug-report loader into RIPTOPL-BUGREPORT-<version>.zip.

build_bugreport.sh stages one unpacked OPLDIAG loader per flavour under rolling/bugreport/. The
official container's build comes first (the one-click RIPTOPL.ELF is that flavour, and Volventura's
working boot-trace loader was built in it); the ps2dev:latest build stands in when it is missing. The
zip holds RIPTOPL-BUGREPORT.ELF and a README on how to use it and what to send. The staging folder is
removed afterwards, so `gh release upload rolling/*` stays file-only.

Every candidate is checked for the layout of a standard ps2sdk link: one loadable segment at
0x00100000, 0x80 bytes into the file. A packed loader (ps2-packer: a small stub high in memory) or
one padded to 0x10000 is refused, because a bug-report loader that starts from fewer launchers than
the normal one is worse than none.

Usage: pack_bugreport.py <assets-dir> --version <download version>
       pack_bugreport.py --check <elf>        (exit 1 when the layout is wrong; build_bugreport.sh)
"""
import argparse
import struct
import sys
import zipfile
from pathlib import Path

FLAVOURS = ("OFFICIALROLLING", "PS2DEVROLLING", "OFFICIALPINNED", "PS2DEVPINNED")
README = Path(__file__).with_name("bugreport_readme.txt")
ISSUES = "https://github.com/NathanNeurotic/Open-PS2-Loader/issues"


def check_layout(elf):
    """Raise ValueError unless elf is an unpacked MIPS ELF32 laid out like a ps2sdk link."""
    if len(elf) < 52 or elf[:4] != b"\x7fELF" or elf[4] != 1 or elf[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF")
    machine, = struct.unpack_from("<H", elf, 18)
    phoff, = struct.unpack_from("<I", elf, 28)
    phentsize, phnum = struct.unpack_from("<HH", elf, 42)
    if machine != 8 or phentsize != 32 or phoff + phnum * 32 > len(elf):
        raise ValueError("not a MIPS executable")
    loads = [h for h in (struct.unpack_from("<8I", elf, phoff + i * 32) for i in range(phnum)) if h[0] == 1]
    if len(loads) != 1 or loads[0][1] != 0x80 or loads[0][2] != 0x00100000:
        raise ValueError("packed or not linked with -zmax-page-size=128: "
                         + ", ".join(f"offset {h[1]:#x} at {h[2]:#010x}" for h in loads))


def readme(version, flavour):
    title = f"RiptOPL bug-report build, {version}"
    text = README.read_text(encoding="utf-8").format(version=version, underline="=" * len(title),
                                                      flavour=flavour, issues=ISSUES)
    return text.replace("\n", "\r\n")


def pack(folder, version):
    """Write folder/RIPTOPL-BUGREPORT-<version>.zip from the best staged loader; None when none is staged."""
    stage = folder / "bugreport"
    candidates = {p.name[len("RIPTOPL-BUGREPORT-"):-len(".ELF")]: p for p in stage.glob("RIPTOPL-BUGREPORT-*.ELF")} if stage.is_dir() else {}
    chosen = next((f for f in FLAVOURS if f in candidates), None)
    if chosen is None:
        return None
    elf = candidates[chosen].read_bytes()
    check_layout(elf)
    archive = folder / f"RIPTOPL-BUGREPORT-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("RIPTOPL-BUGREPORT.ELF", elf)
        bundle.writestr("README.txt", readme(version, chosen))
    return archive, chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, nargs="?")
    parser.add_argument("--version")
    parser.add_argument("--check", type=Path, metavar="ELF")
    args = parser.parse_args()
    if args.check:
        try:
            check_layout(args.check.read_bytes())
        except (OSError, ValueError) as error:
            sys.exit(f"{args.check}: {error}")
        print(f"{args.check}: unpacked ps2sdk layout")
        return
    if args.folder is None or not args.version:
        parser.error("<assets-dir> and --version are required to pack")
    try:
        result = pack(args.folder, args.version)
    except ValueError as error:
        sys.exit(f"ERROR: bug-report loader refused: {error}")
    if result is None:
        print("No bug-report loader staged; the release ships without RIPTOPL-BUGREPORT.zip")
    else:
        print(f"Packed {result[0].name} from the {result[1]} build")


if __name__ == "__main__":
    main()
