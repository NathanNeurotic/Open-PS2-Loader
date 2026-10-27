#!/bin/sh
# Write rolling/IRX-MANIFEST-<FLAVOUR>.txt -- the SHA256 of every prebuilt IOP module in this
# build container's ps2sdk. Called by each build job in rolling-release.yml; $1 is the flavour.
#
# WHY THE MANIFEST EXISTS: so a silent SDK-side driver swap (the mmceman class of surprise) shows
# up as a diff between two runs, instead of arriving as an unexplained hardware report.
#
# WHY IT NOW CARRIES A HEADER: that early warning is only true for modules we actually embed, and
# several of the ones listed are no longer among them -- the fork builds its own and ignores the
# SDK's copy. Somebody debugging a USB report would otherwise diff usbd_mini.irx's hash across
# runs, find it unchanged, and conclude the driver did not move, when the driver we ship does not
# come from there at all. The header names every one so the file cannot mislead that way, and the
# locally built HDD drivers are hashed at the end so their changes show up in the diff too.
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
  echo "# THESE MODULES BELOW ARE NEVER WHAT THE LOADER EMBEDS. The fork builds its own and ignores"
  echo "# the SDK's copy, so their hashes here will NOT explain a change in behaviour -- read the"
  echo "# fork's source instead (every fork-built module is hashed at the end of this file):"
  echo "#"
  echo "#   ata_bd.irx             -> modules/hdd/atad"
  echo "#                             (ps2sdk iop/dev9/atad + retryable init, BDM guard for APA disks)"
  echo "#   ps2hdd-osd.irx         -> modules/hdd/apa"
  echo "#                             (ps2sdk apa-osd + the APA partition-table write fence; docs/APA-SAFETY.md)"
  echo "#   bdm.irx                -> modules/bdm"
  echo "#                             (ps2sdk iop/fs/bdm + libbdm: cache, partition-bound and GPT fixes)"
  echo "#   iLinkman.irx           -> modules/ilink/iLinkman"
  echo "#   IEEE1394_bd(_mini).irx -> modules/ilink/IEEE1394_bd"
  echo "#                             (ps2sdk iop/iLink: bus-reset, login and SBP-2 completion fixes)"
  echo "#   usbd_mini.irx          -> modules/usb/usbd-ra"
  echo "#                             (ps2sdk iop/usb/usbd @314d87e7: FreeUsbd, from before the 2024-09-04 rewrite)"
  echo "#   ps2ips.irx             -> modules/network/ps2ips"
  echo "#                             (ps2sdk master + five fixes, four of them marked \"RA fix\")"
  echo "#   smbman.irx             -> modules/network/smbman-ra, in every flavour, RA or not"
  echo "#                             (ps2sdk master + the held-file fallback and the WRITE_ANDX Count fix)"
  echo "#"
  echo "# TWO ARE OUR REBUILDS, NOT THE SDK'S. In the release jobs install_safe_bdmfs.py and"
  echo "# install_coherent_mmce.sh rebuild bdmfs_fatfs.irx and mmceman.irx from patched source and copy"
  echo "# them over the SDK's files before this script runs, so those two hashes are of our builds."
  echo "#"
  echo "# docs/PS2SDK-NOTES.md lists the ps2sdk defects behind each replacement."
  echo "#"
  echo "# Every other module listed is consumed exactly as this SDK shipped it."
  echo "#"
  echo "# Lines starting with '#' are commentary. GNU sha256sum -c skips them, but BUSYBOX's does"
  echo "# not -- it reports each one as a mismatch, which is what you get in an Alpine container."
  echo "# To verify: grep -v '^#' <this file> | sha256sum -c -"
  echo "#"
  echo "# This file is for DIFFING two runs, which comments do not disturb; -c is the rarer use."
  cat "$TMP"
  echo "#"
  echo "# Fork-built modules this build embeds instead of the SDK's (IEEE1394_bd.irx in DEBUG builds,"
  echo "# IEEE1394_bd_mini.irx otherwise):"
  for module in modules/hdd/atad/ata_bd.irx modules/hdd/apa/ps2hdd-osd.irx modules/bdm/bdm.irx \
    modules/ilink/iLinkman/iLinkman.irx modules/ilink/IEEE1394_bd/IEEE1394_bd.irx \
    modules/ilink/IEEE1394_bd/IEEE1394_bd_mini.irx modules/usb/usbd-ra/usbd_mini.irx \
    modules/network/ps2ips/ps2ips.irx modules/network/smbman-ra/smbman.irx; do
    if [ -f "$module" ]; then
      sha256sum "$module"
    else
      echo "# (not built at manifest time: $module)"
    fi
  done
} > "$OUT"

echo "Wrote ${OUT} ($(grep -vc '^#' "$OUT") modules hashed)"
