#!/bin/sh
# Build the bug-report loader for the rolling release: the field-diagnostics build (OPLDIAG=1: start-up
# steps on screen, boot-stage colours, RIPTOPL-FREEZE.TXT / RIPTOPL-CRASH.TXT) left UNPACKED, so it keeps
# the layout of a standard ps2sdk link (one loadable segment 0x80 bytes into the file). Volventura's
# SCPH-30005R starts that layout from uLaunchELF on MMCE0 where every ps2-packer build gave a black
# screen (2026-11-01), so a diagnostic build that is packed could not report the one failure it is for.
#
# $1 is the flavour brand ("OFFICIALROLLING", "PS2DEVROLLING"): it goes into LOCALVERSION so the build
# self-identifies on screen and in its reports, and into the staged name
# rolling/bugreport/RIPTOPL-BUGREPORT-<flavour>.ELF. publish-rolling packs one of them (official first)
# into RIPTOPL-BUGREPORT-<version>.zip with its README (pack_bugreport.py).
#
# Best-effort, like the DS5 loaders: a failure here is logged and the flavour ships no bug-report
# loader rather than sinking its main build. MUST run AFTER the main ELF is staged (make clean).
set -eu

BRAND="${1:?flavour brand required}"
mkdir -p rolling/bugreport
echo "== Building the RIPTOPL bug-report loader (OPLDIAG=1 NOT_PACKED=1, brand='${BRAND}') =="
# clean depends on download_lwNBD (a network fetch). If it fails, the previous flavour's objects may
# still be there and the OPLDIAG build could link them, so the flavour ships no loader instead.
if ! make clean >/dev/null 2>&1; then
  echo "WARN: make clean failed before the ${BRAND} bug-report build; not building it" >&2
  exit 0
fi
rm -f opl.elf
if make --trace OPLDIAG=1 NOT_PACKED=1 "LOCALVERSION=${BRAND}-BUGREPORT" all && [ -f opl.elf ]; then
  if python3 ./.github/scripts/pack_bugreport.py --check opl.elf; then
    mv opl.elf "rolling/bugreport/RIPTOPL-BUGREPORT-${BRAND}.ELF"
    echo "Staged rolling/bugreport/RIPTOPL-BUGREPORT-${BRAND}.ELF"
  else
    echo "WARN: the ${BRAND} bug-report loader does not have the unpacked ps2sdk layout; not staging it" >&2
    rm -f opl.elf
  fi
else
  echo "WARN: the ${BRAND} bug-report loader failed to build; this flavour ships without one" >&2
fi
ls -la rolling/bugreport || true
