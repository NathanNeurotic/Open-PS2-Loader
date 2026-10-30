#!/usr/bin/env python3
"""ORBIT Neutrino Watch: compare ORBIT's latest stable release with the RA edition's pinned runtime.

The RA kit's Neutrino comes from danielnuld/ps2-launcher, pinned by tag and archive SHA-256 in
third_party/orbit-neutrino/release.json. The packer refuses any other archive, so a new ORBIT release
never reaches a kit on its own: someone has to review it and move the pin. This script decides
whether that review is due and writes the issue body that asks for it. It never edits the pin.

Inputs are files, so the decision is testable offline:
  --release      JSON of GET /repos/danielnuld/ps2-launcher/releases/latest
  --pin          third_party/orbit-neutrino/release.json
  --tag-commit   commit the latest tag points at (optional, for the suggested pin)
  --asset-sha256 SHA-256 of the downloaded asset, used when GitHub reports no digest
  --out          directory for "status" and "issue.md"

status is one of:
  current     the pinned tag is still the latest and its archive digest matches the pin
  changed     a newer release, or the same tag with a different or missing archive
  unverified  the pinned tag is latest but GitHub reports no digest; download the asset and rerun
              with --asset-sha256
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]

# Where each repository hard-codes the snapshot limit that release.json's snapshot_bytes_max records.
LIMIT_SITES = (
    ("src/sources/supportbase.cpp", "RA_ORBIT_SNAPSHOT_MAX"),
    ("src/system.c", "GetWatchBytes() >"),
)


def orbit_assets(release):
    return [a for a in release.get("assets", [])
            if a.get("name", "").startswith("ORBIT-") and a.get("name", "").endswith(".zip")]


def digest_of(asset):
    value = asset.get("digest") or ""
    return value[len("sha256:"):].lower() if value.startswith("sha256:") else ""


def decide(release, pin, asset_sha256=""):
    """Return (status, reason, asset) for the latest release against the pin."""
    assets = orbit_assets(release)
    asset = next((a for a in assets if a["name"] == pin["asset"]), assets[0] if assets else None)
    if release.get("tag_name") != pin["tag"]:
        return "changed", "ORBIT published a newer release than the pinned one.", asset
    if asset is None or asset["name"] != pin["asset"]:
        return "changed", "The pinned release no longer carries " + pin["asset"] + ".", asset
    digest = asset_sha256.lower() or digest_of(asset)
    if not digest:
        return "unverified", "GitHub reports no digest for " + pin["asset"] + ".", asset
    if digest != pin["sha256"].lower():
        return ("changed", "The pinned tag's archive was replaced: its SHA-256 no longer matches the pin. "
                "Treat this as a new release and review it before anything else.", asset)
    return "current", "The pinned runtime is still ORBIT's latest release.", asset


def limit_sites(root):
    lines = []
    for path, needle in LIMIT_SITES:
        source = root / path
        if source.is_file() and needle in source.read_text(encoding="utf-8", errors="replace"):
            lines.append("- `" + path + "` (`" + needle + "`), which must equal `snapshot_bytes_max`")
    return lines


def issue_body(release, pin, reason, asset, tag_commit="", asset_sha256="", root=ROOT):
    digest = asset_sha256.lower() or (digest_of(asset) if asset else "")
    suggested = dict(pin)
    suggested.update({"tag": release.get("tag_name", "?"),
                      "source_commit": tag_commit or "<commit the tag points at>",
                      "asset": asset["name"] if asset else "<ORBIT-*.zip>",
                      "sha256": digest or "<sha256 of the archive>"})
    out = [
        "An upstream ORBIT release differs from our pinned RA-only Neutrino runtime.",
        "",
        reason,
        "",
        "| | Pinned | Latest |",
        "|---|---|---|",
        "| Tag | `" + pin["tag"] + "` | `" + release.get("tag_name", "?") + "` |",
        "| Archive | `" + pin["asset"] + "` | `" + (asset["name"] if asset else "none") + "` |",
        "| SHA-256 | `" + pin["sha256"] + "` | `" + (digest or "not reported") + "` |",
        "",
        "Release: " + release.get("html_url", "https://github.com/" + pin["repository"] + "/releases"),
        "",
        "Before moving the pin, review the new runtime's:",
        "- archive digest against the checksums in the release notes",
        "- loader handoff (`-ra=` argument, `ORBIT-RA.txt` marker, `raagent.irx`)",
        "- one-packet snapshot limit (currently " + str(pin.get("snapshot_bytes_max")) + " bytes) and pointer-chain "
        "support (currently " + str(pin.get("pointer_chains")).lower() + ")",
        "- network module ordering, IGR, and the i.LINK driver replacement",
        "- isolation: the ordinary kits keep the upstream Neutrino bundle; only the RA kit takes ORBIT",
        "",
        "Then update these together, in one PR:",
        "- `third_party/orbit-neutrino/release.json` and its README",
    ]
    out += limit_sites(root)
    out += [
        "- the ORBIT packaging and RA tests",
        "",
        "Suggested `release.json` (re-check `snapshot_bytes_max` and `pointer_chains` against the new source; "
        "they are carried over from the current pin):",
        "",
        "```json",
        json.dumps(suggested, indent=2),
        "```",
        "",
        "This issue is kept up to date by `.github/workflows/orbit-neutrino-watch.yml` and closed by it once "
        "the pin matches ORBIT's latest release again. The watch never edits the pin.",
    ]
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--pin", default=ROOT / "third_party/orbit-neutrino/release.json", type=Path)
    parser.add_argument("--tag-commit", default="")
    parser.add_argument("--asset-sha256", default="")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    release = json.loads(args.release.read_text(encoding="utf-8"))
    pin = json.loads(args.pin.read_text(encoding="utf-8"))
    if release.get("draft") or release.get("prerelease") or not release.get("tag_name"):
        print("::warning::The latest-release answer is not a published stable release; nothing to compare.")
        status, reason, asset = "unknown", "", None
    else:
        status, reason, asset = decide(release, pin, args.asset_sha256)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "status").write_text(status, encoding="utf-8")
    if asset is not None:
        (args.out / "asset").write_text(asset["name"], encoding="utf-8")
    if status == "changed":
        (args.out / "issue.md").write_text(
            issue_body(release, pin, reason, asset, args.tag_commit, args.asset_sha256), encoding="utf-8")
    print("pinned " + pin["tag"] + ", latest " + str(release.get("tag_name")) + ": " + status
          + (" (" + reason + ")" if reason else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
