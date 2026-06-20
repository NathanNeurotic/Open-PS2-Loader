#!/bin/sh
# Build the "extra" RIPTOPL release builds for the rolling release:
#   * the EXTRA_FEATURES x PADEMU variant matrix -> rolling/variants/
#   * the debug configs                          -> rolling/debug/
#
# Called by BOTH SDK build jobs in rolling-release.yml. $1 is the SDK suffix appended to each
# filename: "" for the ps2dev:latest "standard" build, "-OLDSDK" for the pinned build -- so the
# VARIANTS and DEBUG zips always carry both SDK flavours of every build.
#
# Best-effort per build: a single failing config is logged + skipped, never sinking the publish.
# MUST run AFTER the main release ELF is already staged, since each build does `make clean`.
# No version in the filenames -- the version lives in the zip names (rolling-release.yml).
set -eu

SDK_SUFFIX="${1:-}"

echo "== Building RIPTOPL variants (suffix='${SDK_SUFFIX}') =="
mkdir -p rolling/variants
for pad in PADEMU=0 PADEMU=1; do
  for ex in EXTRA_FEATURES=0 EXTRA_FEATURES=1; do
    make clean >/dev/null 2>&1 || true
    if make --trace $pad $ex NOT_PACKED=1 && [ -f opl.elf ]; then
      mv opl.elf "rolling/variants/RIPTOPL-pademu${pad#PADEMU=}-extra${ex#EXTRA_FEATURES=}${SDK_SUFFIX}.ELF"
    else
      echo "WARN: variant '$pad $ex'${SDK_SUFFIX} failed to build; skipping it"
    fi
  done
done
echo "Variants present:"; ls -la rolling/variants || true

echo "== Building RIPTOPL debug builds (suffix='${SDK_SUFFIX}') =="
mkdir -p rolling/debug
for dbg in iopcore_debug ingame_debug eesio_debug iopcore_ppctty_debug ingame_ppctty_debug DTL_T10000=1; do
  make clean >/dev/null 2>&1 || true
  if make --trace $dbg && [ -f opl.elf ]; then
    mv opl.elf "rolling/debug/RIPTOPL-${dbg%=1}${SDK_SUFFIX}.ELF"
  else
    echo "WARN: debug '$dbg'${SDK_SUFFIX} failed to build; skipping it"
  fi
done
echo "Debug present:"; ls -la rolling/debug || true
