#!/bin/sh
# Install a COHERENT MMCE driver trio (mmceman/mmcedrv/mmceigr) into the container's
# $(PS2SDK)/iop/irx, replacing the SDK-provided prebuilts, for the ps2dev/ps2dev:latest build.
#
# WHY: the ps2dev:latest container gets its mmceman/mmcedrv/mmceigr via ps2sdk-ports, pinned to
# ps2-mmce v2.1.1 (979dd77e, 2026-03-07) -- which PREDATES the 2026-06-14 "Changes to mmceman for
# ps2sdk sio2man updates" fix (cccc366). The same container's sio2man is the post-May-2026 refactor,
# so the pinned v2.1.1 driver's sio2man hook is DESYNCED from the runtime sio2man. That mismatch
# hangs MMCE both in the menu (cover-art reads freeze after the list populates) and in-game (freeze
# after the PS2 logo): short SIO2 exchanges (dir enumeration) happen to work, sustained transfers
# (a PNG read, ISO streaming) hit the broken arbitration. The pinned ps2max/dev build is unaffected
# (its SDK ships a July-2025 mmceman coherent with its July-2025 sio2man), so this is latest-only.
#
# FIX: build the trio from ps2-mmce @ MMCE_PIN (the "latest" tag db3e93f0, which INCLUDES the
# sio2man-compat fix) against THIS container's SDK, so the hook matches the container's sio2man,
# then drop the IRX into $(PS2SDK)/iop/irx. The OPL Makefile's MMCE_ASSETS_DIR already points there,
# so every subsequent make (ELF, cdvdman/mcemu USE_MMCE modules, variants, debug) embeds the
# coherent driver with no further changes. Idempotent: safe to run once per job before building.
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
echo "== Building coherent MMCE driver from ps2-mmce @ ${MMCE_PIN} =="
git clone --quiet "$MMCE_REPO" "$WORK/mmceman"
git -C "$WORK/mmceman" checkout --quiet "$MMCE_PIN"

# Older-SDK make quirk: the per-module obj dir isn't auto-created by every Makefile.iopglobal
# vintage -- pre-create them so the first compile step doesn't fail on a missing directory.
mkdir -p "$WORK/mmceman/mmceman/obj" "$WORK/mmceman/mmcedrv/obj" "$WORK/mmceman/mmceigr/obj"

make -C "$WORK/mmceman"

installed=0
for m in mmceman mmcedrv mmceigr; do
    src="$WORK/mmceman/$m/irx/$m.irx"
    if [ ! -f "$src" ]; then
        echo "ERROR: $m.irx was not produced by the ps2-mmce build" >&2
        exit 1
    fi
    cp -f "$src" "$DEST/$m.irx"
    echo "  installed $m.irx ($(wc -c < "$src") bytes) -> $DEST/"
    installed=$((installed + 1))
done
[ "$installed" -eq 3 ] || { echo "ERROR: expected 3 MMCE IRX, installed $installed" >&2; exit 1; }
echo "== Coherent MMCE driver installed over the SDK prebuilts =="
