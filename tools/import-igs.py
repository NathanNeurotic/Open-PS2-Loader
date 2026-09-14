#!/usr/bin/env python3
"""Turn OPL's in-game screenshots into the _SCR art the info page reads.

    tools/import-igs.py <folder-of-bmps> [out-dir]      # default _deploy/ART

IGS is already in OPL -- ee_core/src/igs_api.c, GPL, from maximus32 and
doctorxyz -- and this build now compiles it in. Press D-pad Up in a game (with
GSM enabled for that title) and it downloads the framebuffer and writes

    mc1:/<GAMEID>_GS(nnn).bmp

Nothing in OPL ever reads those back. They are BMPs, on the memory card, under a
name the theme engine does not look for. This closes that gap: BMP to PNG,
resized, renamed to <SERIAL>_SCR.png and <SERIAL>_SCR2.png, which is what info15
and info22 expect.

The first two shots per game become SCR and SCR2; the rest are ignored, because
the page only has two slots. Shots are taken in capture order.

Untested against a real capture -- nothing here has produced one yet. The BMP
reader handles the 16, 24 and 32 bit forms IGS emits depending on the game's
framebuffer format, and refuses anything else loudly rather than writing
garbage.
"""
import os
import re
import struct
import sys
import zlib

TARGET_W, TARGET_H = 250, 188      # 4:3, comfortably above the 130x98 draw size


def read_bmp(path):
    d = open(path, "rb").read()
    if d[:2] != b"BM":
        raise ValueError("not a BMP")
    offset = struct.unpack_from("<I", d, 10)[0]
    hdr = struct.unpack_from("<I", d, 14)[0]
    if hdr < 40:
        raise ValueError(f"unsupported DIB header size {hdr}")
    w, h = struct.unpack_from("<ii", d, 18)
    planes, bpp = struct.unpack_from("<HH", d, 26)
    comp = struct.unpack_from("<I", d, 30)[0]
    if comp not in (0, 3):
        raise ValueError(f"compressed BMP (compression={comp}) not supported")
    if bpp not in (16, 24, 32):
        raise ValueError(f"{bpp}bpp not supported")
    bottom_up = h > 0
    h = abs(h)
    stride = ((w * bpp + 31) // 32) * 4
    rows = []
    for y in range(h):
        src = offset + (h - 1 - y) * stride if bottom_up else offset + y * stride
        line = d[src:src + stride]
        out = bytearray(w * 4)
        for x in range(w):
            if bpp == 32:
                b, g, r = line[x*4], line[x*4+1], line[x*4+2]
            elif bpp == 24:
                b, g, r = line[x*3], line[x*3+1], line[x*3+2]
            else:
                v = struct.unpack_from("<H", line, x*2)[0]
                # PS2 framebuffers are 5551; expand each channel to 8 bits.
                r = ((v & 0x1F) * 255) // 31
                g = (((v >> 5) & 0x1F) * 255) // 31
                b = (((v >> 10) & 0x1F) * 255) // 31
            out[x*4:x*4+4] = bytes((r, g, b, 255))
        rows.append(out)
    return w, h, rows


def box_scale(sw, sh, rows, dw, dh):
    out = []
    for dy in range(dh):
        y0, y1 = dy * sh // dh, max(dy * sh // dh + 1, (dy + 1) * sh // dh)
        row = bytearray(dw * 4)
        for dx in range(dw):
            x0, x1 = dx * sw // dw, max(dx * sw // dw + 1, (dx + 1) * sw // dw)
            r = g = b = n = 0
            for y in range(y0, y1):
                src = rows[y]
                for x in range(x0, x1):
                    r += src[x*4]; g += src[x*4+1]; b += src[x*4+2]; n += 1
            row[dx*4:dx*4+4] = bytes((r//n, g//n, b//n, 255))
        out.append(row)
    return out


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


src = sys.argv[1] if len(sys.argv) > 1 else "."
out = sys.argv[2] if len(sys.argv) > 2 else "_deploy/ART"
os.makedirs(out, exist_ok=True)

# <GAMEID>_GS(nnn).bmp -- GAMEID is the startup name, which is the serial the
# theme's art already uses, so no mapping table is needed.
pat = re.compile(r"^(?P<serial>[A-Z]{4}_\d{3}\.\d{2})_GS\((?P<n>\d+)\)\.bmp$", re.I)
found = {}
for fn in sorted(os.listdir(src)):
    m = pat.match(fn)
    if m:
        found.setdefault(m.group("serial").upper(), []).append((int(m.group("n")), fn))

if not found:
    raise SystemExit(f"no <SERIAL>_GS(n).bmp files in {src}")

made = skipped = 0
for serial, shots in sorted(found.items()):
    shots.sort()
    for slot, (_, fn) in zip(("SCR", "SCR2"), shots):
        try:
            w, h, rows = read_bmp(os.path.join(src, fn))
        except ValueError as e:
            print(f"  SKIP {fn}: {e}")
            skipped += 1
            continue
        small = box_scale(w, h, rows, TARGET_W, TARGET_H)
        write_png(os.path.join(out, f"{serial}_{slot}.png"), TARGET_W, TARGET_H, small)
        print(f"  {fn:<28} {w}x{h} -> {serial}_{slot}.png")
        made += 1
    if len(shots) > 2:
        print(f"  ({len(shots) - 2} further shot(s) for {serial} ignored -- the page has two slots)")

print(f"\n{made} written to {out}" + (f", {skipped} skipped" if skipped else ""))
