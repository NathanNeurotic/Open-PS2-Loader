"""Decode synthetic PS1 VMCs with the production parser, including damaged cards."""
from pathlib import Path
import struct
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/saveicon.h"
static unsigned char card[131072];
static int limit;
static int rd(void *ctx, unsigned int off, void *buf, int size) {
    (void)ctx;
    if (off > (unsigned)limit || (unsigned)size > (unsigned)limit-off) return -1;
    memcpy(buf, card+off, size); return size;
}
int main(int argc, char **argv) {
    saveicon_model_t model;
    FILE *file = fopen(argv[1], "rb");
    if (!file) return 2;
    int size = fread(card, 1, sizeof(card), file); fclose(file);
    limit = argc > 2 ? atoi(argv[2]) : size;
    if (!saveIconFromPs1CardImage(rd, NULL, size, argc > 3 ? argv[3] : NULL, &model)) {
        if (model.texels || model.ps1Frames) return 3;
        puts("NONE"); return 0;
    }
    printf("%d %04x %04x %04x %04x", model.ps1Frames, model.texels[0], model.texels[1],
           model.texels[2], model.texels[3]);
    for (int f=1; f<model.ps1Frames; f++) printf(" %04x", model.texels[f*256]);
    puts(""); saveIconFreeModel(&model);
    if (model.texels || model.ps1Frames) return 4;
    return 0;
}
'''


def checksum(card, frame):
    off = frame * 128
    value = 0
    for byte in card[off:off + 127]:
        value ^= byte
    card[off + 127] = value


def image(frames=1):
    card = bytearray(131072)
    card[:2] = b'MC'
    checksum(card, 0)
    struct.pack_into('<IIH', card, 128, 0x51, 8192, 0xffff)
    card[138:150] = b'BASLUS-12345A'
    checksum(card, 1)
    off = 8192
    card[off:off + 4] = bytes([ord('S'), ord('C'), 0x10 + frames, 1])
    struct.pack_into('<16H', card, off + 96, 0, 0x001f, 0x8000, 0x7c00, *([0] * 12))
    for frame in range(frames):
        card[off + 128 + frame * 128:off + 256 + frame * 128] = bytes([0x10, 0x32] + [frame + 1] * 126)
    return card


with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    source, exe, vmc = temp / 'test.c', temp / 'test', temp / 'card.vmc'
    source.write_text(harness, encoding='utf-8')
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-DSAVEICON_HOST_TEST',
                    '-I', str(root), str(source), str(root / 'src/saveicon.c'), '-o', str(exe)], check=True)

    def run(card, limit=None, serial=None):
        vmc.write_bytes(card)
        args = [str(exe), str(vmc)]
        if limit is not None or serial is not None:
            args.append(str(len(card) if limit is None else limit))
        if serial is not None:
            args.append(serial)
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()

    for frames in (1, 2, 3):
        assert run(image(frames)) == f'{frames} 0000 801f 8000 fc00' + ' 0000' * (frames - 1)
    for length in (0, 127, 2047, 8192, 131071):
        assert run(image()[:length]) == 'NONE'
    for limit in (0, 2047, 8192, 8703):
        assert run(image(), limit) == 'NONE'
    for offset, value, fix in ((0, 0, False), (127, 0, False), (128, 0xa1, True),
                               (128, 0x52, True), (255, 0, False), (8192, 0, False),
                               (8194, 0x10, False), (8194, 0x14, False), (133, 0, True)):
        card = image()
        card[offset] = value
        if fix:
            checksum(card, 1)
        assert run(card) == 'NONE', offset
    # A corrupt/cyclic chain must not cause an unbounded traversal.
    card = image()
    struct.pack_into('<H', card, 136, 0)
    checksum(card, 1)
    assert run(card) == 'NONE'
    card = image()
    struct.pack_into('<H', card, 136, 15)
    checksum(card, 1)
    assert run(card) == 'NONE'
    # Fragmented PS1 saves are valid: only the header/icon in their first block is read.
    card = image(3)
    struct.pack_into('<IH', card, 132, 16384, 4)
    checksum(card, 1)
    struct.pack_into('<IIH', card, 5 * 128, 0x53, 0, 0xffff)
    checksum(card, 5)
    assert run(card).startswith('3 ')

print('PS1 save icons: frames, palette, transparency, short reads, deleted saves and chains passed')
