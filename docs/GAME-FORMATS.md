# Game image formats

Choose a format for the **device, network protocol and loader core** you will use.
A format that PS2-Servers can read on your PC is not necessarily a format that
OPL or Neutrino can decode on the PS2. Seeing a title in a list does not prove
that its selected launch path supports the image.

## PS2 formats at a glance

| Format | Direct use in RiptOPL | With PS2-Servers |
| --- | --- | --- |
| ISO (`.iso`) | Standard PS2 disc image; use the supported device/core combination. | Served as ISO; simplest baseline when diagnosing a launch failure. |
| ZSO (`.zso`) | LZ4-compressed ISO, decoded by the built-in OPL core on backends with ZSO support. Neutrino does not decode ZSO. | UDPFS can decode it on the PC and expose a virtual `.iso`. HTTP passes the compressed file through, which RiptOPL's HTTP client refuses. |
| CSO (`.cso`) | No native CSO playback. | Desktop/Core UDPFS and HTTP can decode supported CSO images into ISO data on the PC. Edge supports CSO over UDPFS. |
| CHD (`.chd`) | No native CHD playback. Copying CHD to USB, MMCE or an SMB share does not add a decoder. | Desktop/Core UDPFS and HTTP can decode supported CHD images with native `libchdr`. Edge does not support CHD. |
| USBExtreme / UL (`ul.cfg` and split game parts) | Legacy split installation supported by relevant OPL paths; this is an installation layout, not compression. Neutrino does not load UL directly. | Do not assume compressed-image virtualization converts UL installations. |
| HDL / APA installed games | Games installed into internal-HDD partitions; not ordinary files in `DVD/`. Core and installation constraints still apply. | A raw disk/UDPBD export is a block-device path, not automatic CHD/CSO decoding. |

These entries describe format handling, not a guarantee that every game, image
variant or console setup works. The source image must be a supported PS2 disc
image; a PS1 CHD does not become a PS2 game because the container is readable.

## Direct ZSO playback

Use the built-in OPL core for direct ZSO playback on supported USB, MX4SIO,
iLink, MMCE, SMB and internal-HDD paths. Ordinary file-based installations use
the same `CD/` or `DVD/` placement and naming rules as ISO. APA installations
require an appropriate installer rather than copying a file into a folder.

When Neutrino is selected for a direct ZSO image, RiptOPL falls back to OPL on
paths with a built-in core. UDPFS/UDPBD have no such fallback, so a compressed
image reaching Neutrino directly is refused. A **server-decoded virtual ISO**
over UDPFS avoids this restriction: Neutrino receives ISO data, not ZSO bytes.

See the [ZSO guide](https://nathanneurotic.github.io/Open-PS2-Loader/zso.html)
for conversion commands, and the [Neutrino reference](NEUTRINO.md) for core limits.
Keep the original image until the converted file has been verified.

## CHD, CSO and ZSO over UDPFS

PS2-Servers Desktop/Core can expose supported compressed images as virtual
`.iso` files. The PC decompresses requested data while the PS2 reads an ISO
through UDPFS. This does not install a CHD or CSO decoder on the console and
does not require a permanently extracted ISO beside the compressed image.

1. Use a current complete [PS2-Servers release](https://github.com/NathanNeurotic/PS2-Servers/releases).
2. Add the supported images to the server's configured game folders, using its
   CD/DVD library layout.
3. Check the launcher's **Compression support** panel. Desktop/Core CSO uses
   Python's standard library; UDPFS ZSO needs `lz4`; CHD needs native `libchdr`.
   Packaged releases bundle the optional dependencies. Source installations
   must provide them separately.
4. Start UDPFS, configure RiptOPL's UDPFS source, refresh the game list and select
   the virtual ISO. UDPFS game launches use Neutrino; install its required files.

If the required decoder is unavailable, Desktop/Core UDPFS leaves that format
unadvertised. Check the server edition, Compression support panel and server
log before changing console compatibility modes. Edge has its own CSO/ZSO
decoder and no CHD support.

The PC must remain running and reachable throughout play. Decompression costs
PC CPU time, and storage speed, network latency and game access patterns affect
results. Compression reduces stored size; it does not guarantee faster loading.

## HTTP, SMB and UDPBD differences

**HTTP:** PS2-Servers decodes supported CHD/CSO images on the server. RiptOPL
can consume the resulting ISO representation when the server supplies a valid
catalog entry and the required byte-range responses. Missing `libchdr` causes
HTTP to skip CHD. ZSO is passed through unchanged by PS2-Servers; RiptOPL lists
but refuses direct ZSO HTTP entries. Use ISO or UDPFS server decoding for ZSO.
See the [HTTP reference](HTTP.md) for catalog, range and launch constraints.

**SMB:** do not assume the UDPFS/HTTP conversion applies to an ordinary SMB
share. Use ISO or native OPL ZSO as appropriate for the selected core. Sharing
the folder alone does not make CHD or CSO playable.

**UDPBD:** exports block-device contents. Select a supported disk/filesystem
layout for Neutrino; it is not the same service as UDPFS virtual ISO streaming.

## PS1 images use separate cores

POPSTARTER uses `.VCD` images. Ember uses game folders and CUE-based disc
selection, with optional `discs.txt` for multiple discs. PS2 image compression
support does not change those requirements. Follow the [PS1 guide](VCD.md)
for preparation, device restrictions and core-specific setup.

## Troubleshooting and evidence

- **CHD/CSO is missing:** confirm you are using a supported PS2-Servers service
  and edition, the image is in the configured library and the decoder is available.
- **ZSO lists but will not launch:** check the core and protocol. Direct Neutrino
  and RiptOPL HTTP do not decode ZSO; UDPFS virtual ISO decoding is a separate path.
- **A virtual ISO starts but stalls:** retain the server log and compare the same
  game as a plain ISO on the same transport before blaming compression.
- **A renamed file fails:** changing `.chd` or `.cso` to `.iso` does not convert
  its contents. Let the server decode it or perform a real conversion on the PC.

This guide documents the current reader and transport contracts. It does not
establish new physical-console acceptance for a game or compressed-image variant.
For server-specific dependencies and edition differences, see PS2-Servers'
[compression documentation](https://github.com/NathanNeurotic/PS2-Servers/blob/main/docs/optional-compression-dependencies.md)
and [edition guide](https://github.com/NathanNeurotic/PS2-Servers/blob/main/docs/EDITIONS.md).
