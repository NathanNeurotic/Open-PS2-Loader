#!/bin/sh
# Build the "extra" RIPTOPL release builds for the rolling release:
#   * the EXTRA_FEATURES x PADEMU x DUALSENSE variant matrix -> rolling/variants/
#   * the debug configs                          -> rolling/debug/
#   * the RetroAchievements flavour              -> rolling/ra/
#
# Called by each ps2dev build job in rolling-release.yml. $1 is the SDK suffix appended to each
# filename: "-PS2DEVPINNED" for the digest-pinned ps2dev snapshot
# build, "-PS2DEVROLLING" for the ps2dev:latest build -- so the VARIANTS and DEBUG zips carry
# both ps2dev flavours. Official-flavour DS5 loaders are added separately by the release normalizer.
# $2 is the LOCALVERSION
# toolchain brand ("PS2DEVPINNED"/"PS2DEVROLLING") embedded in each ELF's version string: filenames get renamed
# and moved to cards, and the debug/variant builds are exactly the ones that show up in bug
# reports -- the on-screen version must self-identify the toolchain like the main builds do.
#
# Best-effort per build: a single failing config is logged + skipped, never sinking the publish.
# MUST run AFTER the main release ELF is already staged, since each build does `make clean`.
# No version in the filenames -- the version lives in the zip names (rolling-release.yml).
set -eu

SDK_SUFFIX="${1:-}"
BRAND="${2:-}"
BRAND_ARG=""
[ -n "$BRAND" ] && BRAND_ARG="LOCALVERSION=$BRAND"

echo "== Building RIPTOPL variants (suffix='${SDK_SUFFIX}' brand='${BRAND}') =="
mkdir -p rolling/variants
for pad in PADEMU=0 PADEMU=1; do
  for ex in EXTRA_FEATURES=0 EXTRA_FEATURES=1; do
    for ds5 in DUALSENSE=0 DUALSENSE=1; do
      make clean >/dev/null 2>&1 || true
      if make --trace $pad $ex $ds5 NOT_PACKED=1 $BRAND_ARG && [ -f opl.elf ]; then
        ds5_label=$([ "${ds5#DUALSENSE=}" = "1" ] && echo "-ds5" || echo "")
        mv opl.elf "rolling/variants/RIPTOPL-pademu${pad#PADEMU=}-extra${ex#EXTRA_FEATURES=}${ds5_label}${SDK_SUFFIX}.ELF"
      else
        echo "WARN: variant '$pad $ex $ds5'${SDK_SUFFIX} failed to build; skipping it"
      fi
    done
  done
done
# RetroAchievements flavour. Deliberately its OWN short loop rather than a fourth dimension of the
# matrix above: folding it in would take 8 builds per SDK flavour to 16 (32 in total) and roughly
# double the rolling job for a feature most users will not run. Two builds -- PADEMU is the only
# axis a RA user still cares about.
#
# EXTRA_FEATURES is deliberately NOT passed. The flag defaults to 0 and the MAIN release loader is
# built with that default, so leaving it alone is what makes this the shipping loader plus
# achievements -- which is what somebody taking RIPTOPL-RA-*.zip instead of the main archive should
# get. An earlier version pinned EXTRA_FEATURES=1, borrowed from the matrix above on the reasoning
# that an opt-in build may as well carry everything. The linker settled it: GSM_1080P + IGS cost
# ee_core ~6.2 KB of text, RA costs ~6.0 KB of bss, and ram84 (77312 bytes, ee_core/linkfile) fits
# one or the other -- ld refuses with ".bss is not within region ram84" and this loop then logs a
# WARN, skips, and the release publishes with no RA zip while every job stays green. Do not restore
# the flag without first shrinking RA's ee_core footprint by ~6.5 KB.
# Staged in rolling/ra/, NOT rolling/variants/. VARIANTS is a ~120 MB diagnostic grab-bag that
# rolling-release.yml deliberately excludes from the permanent MEGA archive as "not installable
# payload" -- so anything living there is classified as a debug artifact and is not archived. RA is
# meant to be a thing a user chooses and installs, so it gets its own installable package zip
# instead (see "Pack the RIPTOPL RA package zip" in rolling-release.yml).
echo "== Building RIPTOPL RetroAchievements flavour (suffix='${SDK_SUFFIX}') =="
mkdir -p rolling/ra
# PACKED, unlike the variants and debug loops above and below. Those two ship raw opl.elf on
# purpose -- they are diagnostic bundles, and a debug build wants its symbols. The RA zip is not
# one: it is an installable package a user chooses instead of the main archive, so its loader has
# to be the same shape as the main one. NOT_PACKED=1 skips the strip + ps2-packer step, which made
# the RA loader 12.2 MB against the main package's 1.46 MB -- and a standard PS2 memory card is
# 8 MB, so mc?:/ could not hold the RA build at all. So take $(EE_BIN_PACKED) (RIPTOPL.ELF) rather
# than $(EE_BIN) (opl.elf). rolling-release.yml asserts the size of what lands here.
for ra_pad in PADEMU=0 PADEMU=1; do
  # A failed clean is FATAL to this variant, not something to build through. PADEMU changes between
  # the two iterations and the Makefile does not rebuild objects when a flag changes, so leftover
  # objects would silently produce a mixed-configuration loader -- and this one goes into a package
  # people install, where a wrong binary is worse than an absent one. The other two loops in this
  # file keep `|| true`; their payload is diagnostic.
  if ! make clean >/dev/null 2>&1; then
    echo "WARN: could not clean before RA build '$ra_pad'${SDK_SUFFIX}; skipping it" >&2
    continue
  fi
  # RIPTOPL.ELF is also what the job's own main and DS5 builds leave in this directory, so without
  # this the [ -f ] test below could pass on somebody else's loader and ship a NON-RA build inside
  # the RA package. Same reason rolling-release.yml does `rm -f RIPTOPL-*.ELF` before each DS5
  # build; that glob does not match this name.
  rm -f RIPTOPL.ELF
  if make --trace RETROACHIEVEMENTS=1 $ra_pad $BRAND_ARG && [ -f RIPTOPL.ELF ]; then
    mv RIPTOPL.ELF "rolling/ra/RIPTOPL-ra-pademu${ra_pad#PADEMU=}${SDK_SUFFIX}.ELF"
  else
    echo "WARN: RA build '$ra_pad'${SDK_SUFFIX} failed to build; skipping it"
  fi
done
echo "RA builds present:"; ls -la rolling/ra || true

echo "Variants present:"; ls -la rolling/variants || true

echo "== Building RIPTOPL debug builds (suffix='${SDK_SUFFIX}') =="
mkdir -p rolling/debug
for dbg in iopcore_debug ingame_debug eesio_debug iopcore_ppctty_debug ingame_ppctty_debug DTL_T10000=1; do
  make clean >/dev/null 2>&1 || true
  if make --trace $dbg $BRAND_ARG && [ -f opl.elf ]; then
    mv opl.elf "rolling/debug/RIPTOPL-${dbg%=1}${SDK_SUFFIX}.ELF"
  else
    echo "WARN: debug '$dbg'${SDK_SUFFIX} failed to build; skipping it"
  fi
done
echo "Debug present:"; ls -la rolling/debug || true
