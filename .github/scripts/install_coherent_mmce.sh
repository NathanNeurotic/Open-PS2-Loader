#!/bin/sh
# Install a MENU-coherent mmceman into the container's $(PS2SDK)/iop/irx, replacing the
# SDK-provided prebuilt, for the ps2dev/ps2dev:latest build. mmcedrv/mmceigr (the IN-GAME
# modules) are deliberately LEFT AS THE CONTAINER'S STOCK PREBUILTS.
#
# WHY (menu / mmceman): the ps2dev:latest container gets its mmce trio via ps2sdk-ports, pinned to
# ps2-mmce v2.1.1 (979dd77e, 2026-03-07) -- which PREDATES the 2026-06-14 "Changes to mmceman for
# ps2sdk sio2man updates" fix (cccc366). The same container's sio2man is the post-May-2026 refactor,
# so the pinned v2.1.1 mmceman's sio2man hook is DESYNCED from the runtime sio2man: short SIO2
# exchanges (dir enumeration) happen to work, sustained transfers (cover-art PNG reads) freeze the
# menu. Rebuilding mmceman from MMCE_PIN (includes cccc366) fixed this -- hardware-confirmed.
#
# WHY NOT mmcedrv/mmceigr (in-game): mmcedrv drives SIO2 directly (its import table has NO sio2man
# dependency -- verified by binary import-table parse), and its SOURCE is UNCHANGED between the
# v2.1.1 pin and MMCE_PIN (`git diff v2.1.1..db3e93f0 -- mmcedrv` is empty). Our repo-Makefile
# rebuild on the new toolchain produced a DIFFERENT binary (10009 vs 11337 bytes) that FAILED
# in-game on hardware (issue #56/#68 reports, 2026-07-05: OPL-core MMCE games broken on the
# "latest" flavour but fine on the "woplsdk" flavour, whose only relevant delta is stock-vs-rebuilt
# mmcedrv). The stock ports-built binary is field-proven in-game (wOPL ships the byte-identical
# file). Same source, proven binary: keep stock.
#
# The OPL Makefile's MMCE_ASSETS_DIR points at $(PS2SDK)/iop/irx, so every subsequent make (ELF,
# cdvdman/mcemu USE_MMCE modules, variants, debug) picks this mix up with no further changes.
# Idempotent: safe to run once per job before building.
#
# Pin is an immutable SHA (the "latest" tag is force-moved upstream). Bump deliberately.
set -eu

MMCE_PIN="${MMCE_PIN:-db3e93f0fdbcf882f88da110cbd9b7db188ec17a}" # ps2-mmce 'latest' @ 2026-06-15 (has cccc366 sio2man fix)
MMCE_REPO="https://github.com/ps2-mmce/mmceman"

: "${PS2SDK:?PS2SDK must be set (run inside the ps2dev toolchain container)}"
DEST="$PS2SDK/iop/irx"

WORK="$(mktemp -d)"
# Clean up on normal exit AND on the signals a CI cancel/timeout sends -- some ash/dash builds don't
# run the EXIT trap on signal termination, so name them explicitly (harmless where EXIT already covers it).
trap 'rm -rf "$WORK"' EXIT TERM INT HUP
echo "== Building menu-coherent mmceman from ps2-mmce @ ${MMCE_PIN} =="
git clone --quiet "$MMCE_REPO" "$WORK/mmceman"
git -C "$WORK/mmceman" checkout --quiet "$MMCE_PIN"

# Older-SDK make quirk: the per-module obj dir isn't auto-created by every Makefile.iopglobal
# vintage -- pre-create it so the first compile step doesn't fail on a missing directory.
mkdir -p "$WORK/mmceman/mmceman/obj"

make -C "$WORK/mmceman/mmceman"

src="$WORK/mmceman/mmceman/irx/mmceman.irx"
if [ ! -f "$src" ]; then
    echo "ERROR: mmceman.irx was not produced by the ps2-mmce build" >&2
    exit 1
fi
cp -f "$src" "$DEST/mmceman.irx"
echo "  installed mmceman.irx ($(wc -c < "$src") bytes) -> $DEST/"
for m in mmcedrv mmceigr; do
    if [ ! -f "$DEST/$m.irx" ]; then
        echo "ERROR: stock $m.irx missing from the SDK prebuilts" >&2
        exit 1
    fi
    echo "  keeping STOCK $m.irx ($(wc -c < "$DEST/$m.irx") bytes) in $DEST/ (in-game, field-proven)"
done
echo "== Menu-coherent mmceman installed; in-game mmcedrv/mmceigr remain the SDK stock prebuilts =="
