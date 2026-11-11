#!/usr/bin/env python3
"""Rebuild the memory-card browser icon of RiptOPL's settings folder (#314).

    python3 tools/make_save_icon.py            write misc/list.icn and misc/icon.sys
    python3 tools/make_save_icon.py --check    exit 1 if the committed files differ from a rebuild
    python3 tools/make_save_icon.py --preview out.png   also render the icon as the browser would

The model is a thin card: the RiptOPL logo (docs/assets/riptopl.png) on the front and, mirrored so it
reads the right way round, on the back, with the glow blue on the edges. The browser spins the icon,
so both faces carry the logo. One .icn is written; the ELF stamps it as list.icn, copy.icn and
del.icn (src/util.c). icon.sys keeps its background and lights and gets the title
"RiptOPL / Open PS2 Loader".

Needs Pillow (pip install pillow). The outputs are committed, so a normal build never runs this.
"""
import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "docs/assets/riptopl.png"
ICN = ROOT / "misc/list.icn"
ICON_SYS = ROOT / "misc/icon.sys"

TEX = 128              # PS2 icon textures are always 128x128 RGB555
FACE_ROWS = 48         # texture rows the logo occupies (aspect of the card face)
EDGE_ROW = 124         # a solid glow-blue band used by the four edges
BG = (4, 8, 22)        # near-black blue behind the logo
EDGE = (32, 96, 232)   # the logo's glow blue
ONE = 4096             # icon fixed point: 4096 = 1.0 for positions, normals and UVs
HALF_W = 2.6           # card half-width in icon units (the stock icons span about +-2.5)
CENTER_Y = -2.5        # y grows downwards; the browser floor is y = 0
HALF_D = 0.12          # half thickness
TITLE = ("ＲｉｐｔＯＰＬ", "Ｏｐｅｎ　ＰＳ２　Ｌｏａｄｅｒ")


def rgb555(r, g, b):
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def texture():
    from PIL import Image

    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.crop(logo.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox())
    tex = Image.new("RGB", (TEX, TEX), BG)
    # Fit the logo into the face rows, keeping its aspect, centred.
    scale = min(TEX / logo.width, FACE_ROWS / logo.height)
    w, h = max(1, round(logo.width * scale)), max(1, round(logo.height * scale))
    small = logo.resize((w, h), Image.LANCZOS)
    tex.paste(small, ((TEX - w) // 2, (FACE_ROWS - h) // 2), small)
    for y in range(EDGE_ROW - 4, TEX):
        for x in range(TEX):
            tex.putpixel((x, y), EDGE)
    return [rgb555(*tex.getpixel((x, y))) for y in range(TEX) for x in range(TEX)]


def rle(pixels):
    """The .icn texture compression: a repeat run is (count, value); a literal run is
    (0x10000 - count, values...). Runs never exceed 0x7fff."""
    out, i, n = [], 0, len(pixels)
    while i < n:
        j = i
        while j + 1 < n and pixels[j + 1] == pixels[i] and j + 1 - i < 0x7FFF:
            j += 1
        if j > i:
            out += [j - i + 1, pixels[i]]
            i = j + 1
            continue
        j = i
        while j + 1 < n and pixels[j + 1] != pixels[j] and j + 1 - i < 0x7FFF:
            j += 1
        if j + 1 < n and j > i:
            j -= 1  # leave the first pixel of the next repeat run to that run
        out += [0x10000 - (j - i + 1)] + pixels[i:j + 1]
        i = j + 1
    data = struct.pack("<%dH" % len(out), *out)
    return struct.pack("<I", len(data)) + data


def card():
    """Triangles of the card: (position, normal, uv) per vertex, three vertices per triangle."""
    hh = HALF_W * FACE_ROWS / TEX            # the face keeps the texture's face aspect
    x0, x1, y0, y1, z0, z1 = -HALF_W, HALF_W, CENTER_Y - hh, CENTER_Y + hh, -HALF_D, HALF_D
    v_top, v_bot, v_edge = 0.0, FACE_ROWS / TEX, (EDGE_ROW + 2) / TEX

    def quad(a, b, c, d, n, uvs):
        # Wind each triangle so cross(v1 - v0, v2 - v0) points along the outward normal n, as the
        # stock icons do: the browser culls by winding, and the opposite order (RiptOPL #314, Beta-4216
        # to 4235) hid the face toward the camera and showed the far face through it, mirrored.
        p = [a, b, c, d]
        return [(p[k], n, uvs[k]) for k in (0, 2, 1, 0, 3, 2)]

    edge = [(0.5, v_edge)] * 4
    tris = []
    # Front faces -z (the browser's camera side); u follows +x.
    tris += quad((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (0, 0, -1),
                 [(0, v_top), (1, v_top), (1, v_bot), (0, v_bot)])
    # Back faces +z; u runs the other way so the logo is not mirrored when the card turns.
    tris += quad((x1, y0, z1), (x0, y0, z1), (x0, y1, z1), (x1, y1, z1), (0, 0, 1),
                 [(0, v_top), (1, v_top), (1, v_bot), (0, v_bot)])
    tris += quad((x0, y0, z1), (x1, y0, z1), (x1, y0, z0), (x0, y0, z0), (0, -1, 0), edge)  # top
    tris += quad((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1), (0, 1, 0), edge)   # bottom
    tris += quad((x0, y0, z1), (x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (-1, 0, 0), edge)  # left
    tris += quad((x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0), (1, 0, 0), edge)   # right
    return tris


def fx(v):
    return int(round(v * ONE))


def icn_bytes():
    tris = card()
    out = struct.pack("<IIIfI", 0x010000, 1, 0x0E, 1.0, len(tris))  # 1 shape, RLE texture
    for pos, nrm, uv in tris:
        out += struct.pack("<4h", fx(pos[0]), fx(pos[1]), fx(pos[2]), 1024)
        out += struct.pack("<4h", fx(nrm[0]), fx(nrm[1]), fx(nrm[2]), 1024)
        out += struct.pack("<2h", min(fx(uv[0]), ONE), min(fx(uv[1]), ONE))
        out += bytes((127, 127, 127, 128))
    # One still frame: animation header, then shape 0 with a single key (time 0, value 1.0).
    out += struct.pack("<IIfII", 1, 1, 0.0, 0, 1) + struct.pack("<IIff", 0, 1, 0.0, 1.0)
    return out + rle(texture())


def icon_sys_bytes():
    data = bytearray(ICON_SYS.read_bytes())
    if len(data) != 964 or data[:4] != b"PS2D":
        sys.exit("misc/icon.sys is not a 964-byte PS2D file")
    title = (TITLE[0] + TITLE[1]).encode("shift_jis")
    if len(title) > 68:
        sys.exit("title too long")
    data[6:8] = struct.pack("<H", len(TITLE[0].encode("shift_jis")))  # line break, in bytes
    data[0xC0:0xC0 + 68] = title.ljust(68, b"\0")
    return bytes(data)


def preview(icn, path):
    """Software render of the card, front view and a three-quarter view, for review only."""
    import math
    from PIL import Image, ImageDraw

    nv = struct.unpack_from("<I", icn, 16)[0]
    verts = []
    for i in range(nv):
        x, y, z, _ = struct.unpack_from("<4h", icn, 20 + i * 24)
        u, v = struct.unpack_from("<2h", icn, 20 + i * 24 + 16)
        verts.append((x / ONE, y / ONE, z / ONE, u / ONE, v / ONE))
    off = 20 + nv * 24 + 36
    size = struct.unpack_from("<I", icn, off)[0]
    words = struct.unpack_from("<%dH" % (size // 2), icn, off + 4)
    px, k = [], 0
    while k < len(words):
        c = words[k]
        if c & 0x8000:
            px += words[k + 1:k + 1 + (0x10000 - c)]
            k += 1 + 0x10000 - c
        else:
            px += [words[k + 1]] * c
            k += 2
    tex = [((p & 31) << 3, ((p >> 5) & 31) << 3, ((p >> 10) & 31) << 3) for p in px]
    W, H, S = 384, 256, 64
    out = Image.new("RGB", (W * 2, H), (40, 60, 110))
    for view, yaw in enumerate((0.0, 0.6)):
        img = Image.new("RGB", (W, H), (40, 60, 110))
        zbuf = [[1e9] * W for _ in range(H)]
        c, s = math.cos(yaw), math.sin(yaw)
        pts = [(x * c - z * s, y, x * s + z * c, u, v) for x, y, z, u, v in verts]
        for t in range(0, nv, 3):
            tri = [(W / 2 + p[0] * S, H / 2 + (p[1] - CENTER_Y) * S, p[2], p[3], p[4]) for p in pts[t:t + 3]]
            (ax, ay, az, au, av), (bx, by, bz, bu, bv), (cx, cy, cz, cu, cv) = tri
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            for yy in range(max(0, int(min(ay, by, cy))), min(H, int(max(ay, by, cy)) + 1)):
                for xx in range(max(0, int(min(ax, bx, cx))), min(W, int(max(ax, bx, cx)) + 1)):
                    l1 = ((by - cy) * (xx - cx) + (cx - bx) * (yy - cy)) / den
                    l2 = ((cy - ay) * (xx - cx) + (ax - cx) * (yy - cy)) / den
                    l3 = 1 - l1 - l2
                    if min(l1, l2, l3) < 0:
                        continue
                    zz = l1 * az + l2 * bz + l3 * cz
                    if zz >= zbuf[yy][xx]:
                        continue
                    zbuf[yy][xx] = zz
                    uu = min(TEX - 1, int((l1 * au + l2 * bu + l3 * cu) * TEX))
                    vv = min(TEX - 1, int((l1 * av + l2 * bv + l3 * cv) * TEX))
                    img.putpixel((xx, yy), tex[vv * TEX + uu])
        out.paste(img, (view * W, 0))
    ImageDraw.Draw(out)
    out.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--preview")
    args = ap.parse_args()
    icn, isys = icn_bytes(), icon_sys_bytes()
    if args.preview:
        preview(icn, args.preview)
    if args.check:
        same = ICN.read_bytes() == icn and ICON_SYS.read_bytes() == isys
        print("up to date" if same else "misc/list.icn or misc/icon.sys differs from a rebuild")
        return 0 if same else 1
    ICN.write_bytes(icn)
    ICON_SYS.write_bytes(isys)
    print("misc/list.icn %d bytes, misc/icon.sys %d bytes" % (len(icn), len(isys)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
