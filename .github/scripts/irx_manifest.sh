#!/bin/sh
# Write rolling/IRX-MANIFEST-<FLAVOUR>.txt -- the SHA256 of every prebuilt IOP module in this
# build container's ps2sdk. Called by each build job in rolling-release.yml; $1 is the flavour.
#
# WHY THE MANIFEST EXISTS: so a silent SDK-side driver swap (the mmceman class of surprise) shows
# up as a diff between two runs, instead of arriving as an unexplained hardware report.
#
# WHY IT NOW CARRIES A HEADER: that early warning is only true for modules we actually embed, and
# three of the ones listed are no longer among them -- the fork builds its own and ignores the
# SDK's copy. Somebody debugging a USB report would otherwise diff usbd_mini.irx's hash across
# runs, find it unchanged, and conclude the driver did not move, when the driver we ship does not
# come from there at all. The header names all three so the file cannot mislead that way.
#
# The four call sites used to be four identical inline sha256sum lines; the note lives here once
# rather than being copy-pasted into each of them and drifting.
set -eu

FLAVOUR="${1:?usage: irx_manifest.sh <FLAVOUR>}"
OUT="rolling/IRX-MANIFEST-${FLAVOUR}.txt"

# Hash first, into scratch. Writing the header up front would leave a header-only manifest behind
# on a container whose SDK has no prebuilt IRX directory at all.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT INT TERM

if ! sha256sum "${PS2SDK:-}"/iop/irx/*.irx > "$TMP" 2>/dev/null; then
  echo "WARN: no SDK prebuilt IRX modules found for ${FLAVOUR}; manifest not written" >&2
  exit 0
fi

mkdir -p rolling
{
  echo "# IRX provenance for the ${FLAVOUR} build: SHA256 of every prebuilt IOP module in this"
  echo "# container's ps2sdk, so an SDK-side driver swap shows up as a diff between runs rather"
  echo "# than as an unexplained hardware report."
  echo "#"
  echo "# TWO OF THE MODULES BELOW ARE NEVER WHAT THE LOADER EMBEDS. The fork builds its own and"
  echo "# ignores the SDK's copy, so their hashes here will NOT explain a change in behaviour --"
  echo "# read the fork's source instead:"
  echo "#"
  echo "#   usbd_mini.irx  -> modules/usb/usbd-ra"
  echo "#                     (ps2sdk iop/usb/usbd @314d87e7, the state before the 2024-09-04 rewrite)"
  echo "#   ps2ips.irx     -> modules/network/ps2ips"
  echo "#                     (ps2sdk master + four fixes marked \"RA fix\")"
  echo "#"
  echo "# A THIRD IS CONDITIONAL, and this container produces both kinds of build:"
  echo "#"
  echo "#   smbman.irx     -> the SDK copy hashed below IS embedded in the four standard loaders,"
  echo "#                     which are built with RETROACHIEVEMENTS=0. The RA loaders built in the"
  echo "#                     same job use modules/network/smbman-ra instead. So this hash is live"
  echo "#                     for the standard builds and irrelevant to the RA ones."
  echo "#"
  echo "# Every other module listed is consumed exactly as this SDK shipped it."
  echo "#"
  echo "# Lines starting with '#' are commentary. GNU sha256sum -c skips them, but BUSYBOX's does"
  echo "# not -- it reports each one as a mismatch, which is what you get in an Alpine container."
  echo "# To verify: grep -v '^#' <this file> | sha256sum -c -"
  echo "#"
  echo "# This file is for DIFFING two runs, which comments do not disturb; -c is the rarer use."
  cat "$TMP"
} > "$OUT"

echo "Wrote ${OUT} ($(grep -vc '^#' "$OUT") modules hashed)"
