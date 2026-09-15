#!/bin/sh
# Print the version used in release DOWNLOAD FILE NAMES: the build version without its trailing
# commit hash, e.g. v1.2.0-Beta-2910-6c5f4b1 -> v1.2.0-Beta-2910.
#
# The names are what a new user reads on the release page, so they carry only the version. The full
# version, commit included, is still in the release notes header and inside the loader (About), and
# the permanent MEGA archive keeps its own unique run/commit name. A version with no trailing 7-hex
# hash (a tagged release, or the "rolling" fallback) is printed unchanged.
#
# Usage: sh .github/scripts/asset_version.sh "<OPL_VERSION>"
printf '%s\n' "${1:-rolling}" | sed -E 's/-[0-9a-f]{7}$//'
