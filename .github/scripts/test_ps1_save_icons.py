"""Decode synthetic PS1 VMCs with the production parser, including damaged cards."""
from pathlib import Path
import struct
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]


def function(path, signature):
    source = (root / path).read_text(encoding='utf-8')
    start = source.index(signature)
    # These definitions close at column zero; inner blocks are indented.
    end = source.index('\n}\n', start) + 3
    return source[start:end]


paths = r'''
#include <assert.h>
#define CUE_NAME_LAUNCH_MAX 180
#define EMBER_GAMES_FOLDER "games"
static const char *cueEmberFolder(void) { return "EMBER"; }
@CUE_SEP@
@CUE_GAMES@
@CUE_NAME@
@DIRECTORY@
#define APA_IDMAX 32
typedef struct { int view; } item_list_t;
typedef struct { char name[64]; int ember; } base_game_info_t;
static base_game_info_t hddEmptyVcd, hddVcdGames[2] = {{"Same title", 1}, {"Same title", 1}};
static int hddVcdGameCount = 2;
static char parts[2][APA_IDMAX+1] = {"__common", "__.POPS2"};
static char (*hddVcdParts)[APA_IDMAX+1] = parts;
static char gOPLPart[40] = "hdd0:__common", *gHDDPrefix = "pfs0:/OPL/";
static int hddGetSourceId(item_list_t *list, int id) { return id - (list->view == 2 ? 5 : 0); }
static base_game_info_t *hddActiveVcd(int id) { return id < 0 || id > 1 ? &hddEmptyVcd : &hddVcdGames[id]; }
static int cueIsCueEntry(const base_game_info_t *game) { return game->ember; }
static char udpfsPrefix[40] = "udpfs:/";
@UDPFS@
@HDD@
static void checkPaths(void) {
    char dir[SAVEICON_PATH_SIZE], part[SAVEICON_PATH_SIZE], small[8], longName[160];
    item_list_t ps1 = {1}, mixed = {2};
    assert(saveIconPs1Directory("mass3:/", "Game", 0, dir, sizeof(dir)) && !strcmp(dir, "mass3:/POPS/Game"));
    assert(saveIconPs1Directory("mmce1:/", "Game", 1, dir, sizeof(dir)) && !strcmp(dir, "mmce1:/EMBER/games/Game"));
    assert(saveIconPs1Directory("smb:/share\\", "Game", 1, dir, sizeof(dir)) && !strcmp(dir, "smb:/share\\EMBER\\games\\Game"));
    assert(udpfsGetPs1SaveDir(&ps1, 9, "Game", 1, dir, sizeof(dir), part, sizeof(part)) && !part[0] && !strcmp(dir, "udpfs:/EMBER/games/Game"));
    assert(!udpfsGetPs1SaveDir(&ps1, 9, "Game", 0, dir, sizeof(dir), part, sizeof(part)));
    assert(!udpfsGetPs1SaveDir(&ps1, 9, "../Game", 1, dir, sizeof(dir), part, sizeof(part)));
    memset(longName, 'A', sizeof(longName)-1); longName[sizeof(longName)-1]=0;
    assert(saveIconPs1Directory("smb:/a-long-share-prefix\\", longName, 1, dir, sizeof(dir)));
    assert(!saveIconPs1Directory("mass0:/", "Game", 0, small, sizeof(small)));
    assert(!saveIconPs1Directory("mass0:/", "../Game", 0, dir, sizeof(dir)));
    assert(hddGetPs1SaveDir(&ps1, 0, "Same title", 1, dir, sizeof(dir), part, sizeof(part)) && !part[0] && !strcmp(dir, "pfs0:/EMBER/games/Same title"));
    assert(hddGetPs1SaveDir(&ps1, 1, "Same title", 1, dir, sizeof(dir), part, sizeof(part)) && !strcmp(part, "hdd0:__.POPS2"));
    assert(hddGetPs1SaveDir(&mixed, 6, "Same title", 1, dir, sizeof(dir), part, sizeof(part)) && !strcmp(part, "hdd0:__.POPS2"));
    assert(!hddGetPs1SaveDir(&ps1, 2, "Same title", 1, dir, sizeof(dir), part, sizeof(part)));
    assert(!hddGetPs1SaveDir(&ps1, 0, "Stale title", 1, dir, sizeof(dir), part, sizeof(part)));
    strcpy(hddVcdGames[1].name, "Unique title");
    assert(hddGetPs1SaveDir(&ps1, 2, "Unique title", 1, dir, sizeof(dir), part, sizeof(part)) && !strcmp(part, "hdd0:__.POPS2"));
    assert(hddGetPs1SaveDir(&ps1, 0, "Unique title", 1, dir, sizeof(dir), part, sizeof(part)) && !strcmp(part, "hdd0:__.POPS2"));
    assert(!hddGetPs1SaveDir(&ps1, 2, "Unique title", 0, dir, sizeof(dir), part, sizeof(part)));
    hddVcdParts=NULL;
    assert(!hddGetPs1SaveDir(&ps1, 2, "Unique title", 1, dir, sizeof(dir), part, sizeof(part)));
    hddVcdParts=parts;
    hddVcdGames[0].ember=0;
    assert(hddGetPs1SaveDir(&ps1, 0, "Same title", 0, dir, sizeof(dir), part, sizeof(part)) && !part[0] && !strcmp(dir, "pfs0:/POPS/Same title"));
    gHDDPrefix=NULL;
    assert(hddGetPs1SaveDir(&ps1, 0, "Same title", 0, dir, sizeof(dir), part, sizeof(part)) && !strcmp(part, "hdd0:__common"));
}
'''
for placeholder, path, signature in (
        ('@CUE_SEP@', 'src/cuesupport.c', 'static char cueSep('),
        ('@CUE_GAMES@', 'src/cuesupport.c', 'void cueBuildGamesDir('),
        ('@CUE_NAME@', 'src/cuesupport.c', 'int cueNameLaunchable('),
        ('@DIRECTORY@', 'src/saveicon.c', 'int saveIconPs1Directory('),
        ('@UDPFS@', 'src/udpfssupport.c', 'static int udpfsGetPs1SaveDir('),
        ('@HDD@', 'src/hddsupport.c', 'static int hddGetPs1SaveDir(')):
    paths = paths.replace(placeholder, function(path, signature))

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/saveicon.h"
@PATHS@
static unsigned char card[131072];
static int limit;
static int rd(void *ctx, unsigned int off, void *buf, int size) {
    (void)ctx;
    if (off > (unsigned)limit || (unsigned)size > (unsigned)limit-off) return -1;
    memcpy(buf, card+off, size); return size;
}
int main(int argc, char **argv) {
    checkPaths();
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
harness = harness.replace('@PATHS@', paths)


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
    card[138:151] = b'BASLUS-12345A'
    assert len(card) == 131072
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
