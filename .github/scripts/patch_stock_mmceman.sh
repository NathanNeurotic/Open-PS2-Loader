#!/bin/sh
# Install a LEAK-FIXED mmceman into $(PS2SDK)/iop/irx for the PRE-sio2man-refactor containers
# (WOPLSDK = ghcr ps2homebrew digest pin, PS2MAXSDK = ps2max/dev pin). mmcedrv/mmceigr (the
# IN-GAME modules) are deliberately LEFT AS THE CONTAINER'S STOCK PREBUILTS (field-proven; see
# install_coherent_mmce.sh for the full mmcedrv rationale).
#
# WHY: mmce_fs_close/dclose in every stock mmceman leak their slot from the 16-entry FS handle
# pool on ANY failed close (SIO2 timeout / bad reply / card error) -- only a clean close frees it.
# mmceman is a session singleton, so on a contended card those failures accumulate and after ~16
# the pool is permanently drained: every mmceN: open()/opendir() fails until reboot (RiptOPL #120
# class: blank game lists, dead saves). The fix was applied to the PS2DEVLATESTSDK flavour on
# 2026-07-10 (install_coherent_mmce.sh) but the WOPLSDK/PS2MAXSDK flavours kept shipping the leaky
# stock driver -- maintainer directive 2026-07-20 (#245 investigation): NO flavour ships the leak.
#
# WHY NOT install_coherent_mmce.sh here: that script rebuilds from MMCE_PIN db3e93f0, which
# includes the cccc366 "sio2man updates" changes targeting the POST-May-2026 sio2man refactor in
# ps2dev:latest. These containers ship the PRE-refactor sio2man, so db3e93f0's hook would be
# desynced the OTHER way (the exact class of bug install_coherent_mmce.sh exists to fix). Instead:
# rebuild from the last PRE-refactor generation, ps2-mmce v2.1.1 (979dd77e, 2026-03-07 -- the same
# generation the WOPLSDK container's ports pin ships), with ONLY the fd-leak patch on top. The
# patch content is byte-identical in effect to the db3e93f0 one; only the diff context differs
# (v2.1.1's mmce_fs.c predates the close-packet padding + fs_rename additions).
#
# PROVENANCE DELTA (documented per the WOPLSDK job's discriminator purpose): mmceman on these
# flavours is now "v2.1.1 + fd-leak fix" instead of the container's untouched stock. For WOPLSDK
# the stock IS ports-built v2.1.1, so the delta is exactly the leak fix. For PS2MAXSDK the stock
# may be an earlier ports generation; v2.1.1 is the closest pre-refactor source and the manifest
# (IRX-MANIFEST-*.txt) records the shipped hash either way.
#
# Pin is an immutable SHA (tags can move). Bump deliberately. Fail LOUD everywhere -- silently
# shipping the leak again is the failure mode to avoid.
set -eu

MMCE_STOCK_PIN="${MMCE_STOCK_PIN:-979dd77e61f44cb9dfdfe76d255d829fa833ed92}" # ps2-mmce v2.1.1 (2026-03-07, pre-sio2man-refactor)
MMCE_REPO="https://github.com/ps2-mmce/mmceman"

: "${PS2SDK:?PS2SDK must be set (run inside a ps2dev toolchain container)}"
DEST="$PS2SDK/iop/irx"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FS_LEAK_PATCH="$SCRIPT_DIR/../patches/mmceman-fs-close-fd-leak-v211.patch"
if [ ! -f "$FS_LEAK_PATCH" ]; then
    echo "ERROR: expected mmceman fd-leak patch (v2.1.1 context) not found at $FS_LEAK_PATCH" >&2
    exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT TERM INT HUP
echo "== Building leak-fixed stock-generation mmceman from ps2-mmce @ ${MMCE_STOCK_PIN} =="
git clone --quiet "$MMCE_REPO" "$WORK/mmceman"
git -C "$WORK/mmceman" checkout --quiet "$MMCE_STOCK_PIN"

echo "== Applying mmceman fd-leak fix (mmce_fs_close/dclose slot free-on-failure, v2.1.1 context) =="
git -C "$WORK/mmceman" apply --verbose "$FS_LEAK_PATCH"

# Older-SDK make quirk: pre-create the per-module obj dir (see install_coherent_mmce.sh).
mkdir -p "$WORK/mmceman/mmceman/obj"

make -C "$WORK/mmceman/mmceman"

src="$WORK/mmceman/mmceman/irx/mmceman.irx"
if [ ! -f "$src" ]; then
    echo "ERROR: mmceman.irx was not produced by the ps2-mmce build" >&2
    exit 1
fi
cp -f "$src" "$DEST/mmceman.irx"
echo "  installed leak-fixed mmceman.irx ($(wc -c < "$src") bytes) -> $DEST/"
for m in mmcedrv mmceigr; do
    if [ ! -f "$DEST/$m.irx" ]; then
        echo "ERROR: stock $m.irx missing from the SDK prebuilts" >&2
        exit 1
    fi
    echo "  keeping STOCK $m.irx ($(wc -c < "$DEST/$m.irx") bytes) in $DEST/ (in-game, field-proven)"
done
echo "== Leak-fixed mmceman installed; in-game mmcedrv/mmceigr remain the SDK stock prebuilts =="
