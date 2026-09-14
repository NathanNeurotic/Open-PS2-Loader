#!/usr/bin/env python3
"""Read each ISO's SYSTEM.CNF the same way OPL does, and report the startup name.

OPL identifies a game by the BOOT2 line in SYSTEM.CNF (supportbase.c:335), not by
the filename, so this is the string every _COV/_BG/_SCR file has to be named after.
"""
import os, re, struct, sys

SEC = 2048

def read(f, lba, n):
    f.seek(lba * SEC)
    return f.read(n)

def walk_root(f):
    pvd = read(f, 16, SEC)
    if pvd[1:6] != b"CD001":
        return None
    rec = pvd[156:156 + 34]
    lba, size = struct.unpack("<I", rec[2:6])[0], struct.unpack("<I", rec[10:14])[0]
    data = read(f, lba, size)
    i = 0
    while i < len(data):
        ln = data[i]
        if ln == 0:
            i = (i // SEC + 1) * SEC
            continue
        r = data[i:i + ln]
        nlen = r[32]
        name = r[33:33 + nlen]
        yield name, struct.unpack("<I", r[2:6])[0], struct.unpack("<I", r[10:14])[0]
        i += ln

def startup(path):
    with open(path, "rb") as f:
        try:
            entries = list(walk_root(f))
        except Exception as e:
            return None, f"unreadable ({e})"
        if not entries:
            return None, "no ISO9660 volume descriptor"
        for name, lba, size in entries:
            if name.upper().startswith(b"SYSTEM.CNF"):
                cnf = read(f, lba, min(size, SEC)).decode("latin-1")
                m = re.search(r"BOOT2\s*=\s*cdrom0:\\?([^;\s]+)", cnf, re.I)
                if m:
                    return m.group(1).strip(), None
                return None, "SYSTEM.CNF has no BOOT2"
        return None, "no SYSTEM.CNF in root"

def artdir(root):
    """Where the art is. `art-out/` is the staging directory the pipeline writes;
    `ART/` is the device layout OPL creates for itself (supportbase.c:822) and is
    what an SMB share, a USB stick or a staged _deploy/ actually holds. The same
    library wants checking on both sides of the copy, so accept either."""
    for name in ("art-out", "ART"):
        d = os.path.join(root, name)
        if os.path.isdir(d):
            return d
    return None


def discs(d, prefix=""):
    out = []
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if os.path.isfile(p) and fn.lower().endswith((".iso", ".bin")):
            out.append((prefix + fn, fn, p))
    return out


def isos(root):
    """Every disc under root, as (label, filename, path).

    A staging directory holds them flat; a device -- a USB stick, an SMB share --
    holds them under CD/ and DVD/. The root is checked first and wins outright,
    rather than the two being added together: a directory that is both a staging
    area and a copy of the device tree would otherwise report every disc twice,
    and one stub per disc would become two."""
    flat = discs(root)
    if flat:
        return flat

    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if name.upper() in ("CD", "DVD") and os.path.isdir(d):
            out += discs(d, name + "/")
    return out


root = sys.argv[1]
adir = artdir(root)
if adir is None:
    sys.exit(f"no art directory under {root} -- expected art-out/ (staging) or ART/ (device)")
art = {f.rsplit("_", 1)[0] for f in os.listdir(adir) if f.endswith("_COV.png")}
print(f"art from {os.path.relpath(adir, root)}/\n")

found, missing, broken = [], [], []
for label, fn, p in isos(root):
    s, err = startup(p)
    if err:
        broken.append((label, err))
    elif s in art:
        found.append((fn, s))
    else:
        missing.append((label, s))

print(f"{len(found)} ISOs with matching art")
for fn, s in found:
    print(f"   ok    {s:<14} {fn}")
print(f"\n{len(missing)} ISOs with NO art at that serial")
for fn, s in missing:
    print(f"   ART?  {s:<14} {fn}")
print(f"\n{len(broken)} unreadable")
for fn, e in broken:
    print(f"   bad   {fn}  -- {e}")

used = {s for _, s in found}
orphan = sorted(art - used)
print(f"\n{len(orphan)} art serials with no ISO here: {', '.join(orphan) if orphan else '(none)'}")
