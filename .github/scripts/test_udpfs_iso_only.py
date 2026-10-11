"""Check UDPFS skips USBExtreme enumeration without changing other device scanners."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
support = (ROOT / "src/supportbase.c").read_text(encoding="utf-8")
header = (ROOT / "include/supportbase.h").read_text(encoding="utf-8")
udpfs = (ROOT / "src/udpfssupport.c").read_text(encoding="utf-8")
other_devices = {
    name: (ROOT / ("src/" + name + "support.c")).read_text(encoding="utf-8")
    for name in ("bdm", "mmce", "eth")
}

def check(condition, explanation):
    if not condition:
        raise AssertionError(explanation)

# The common scanner accepts fsize=NULL for an ISO-only read.
check("if (atRoot && fsize != NULL)" in support, "Common scanner must gate ul.cfg by fsize")
check(bool(re.search(r"if\s*\(fsize\s*!=\s*NULL\)\s*\*fsize\s*=\s*newfsize", support)),
      "Common scanner must not dereference a NULL fsize")
check("fsize=NULL for ISO-only" in header, "Opt-out must be documented")
check("return fsize == NULL ? -1 : *gamecount;" in support,
      "ISO-only total read failures must retain cached games and request retry")

# Neutrino-backed UDPFS should never probe or publish USBExtreme split games.
check(bool(re.search(r"sbReadList\(&udpfsGames,\s*udpfsPrefix,\s*folderGetSub\(itemList->mode\),\s*NULL,\s*&udpfsGameCount\)", udpfs)),
      "UDPFS must request ISO-only enumeration")
check("sbIsSameSize(udpfsPrefix" not in udpfs, "UDPFS must not stat ul.cfg during refresh")
check("udpfsULSizePrev" not in udpfs, "Remove obsolete UDPFS UL-size state")
check("if (!udpfsIsoScanned)" in udpfs and "udpfsIsoScanned = answeredBefore;" in udpfs,
      "Preserve initial scan and unreachable-server refresh behavior")
for name in ("udpfsInit", "udpfsUpdateGameList", "udpfsDeleteGame", "udpfsRenameGame"):
    body = re.search(r"(?:static )?(?:void|int) " + name + r"\([^\n]*\)\s*\{(.*?)(?=\n\})", udpfs, re.S)
    check(body is not None and "udpfsIsoScanned = 0;" in body.group(1),
          name + " must rearm ISO scanning")
check("game->format == GAME_FORMAT_USBLD" in udpfs,
      "Keep the defensive UL launch guard for stale rows")

# Other devices retain their original five-argument scanner and UL-size tracking.
check("int sbReadList(base_game_info_t **list" in support,
      "Shared scanner signature must remain unchanged")
for device, body in other_devices.items():
    check(bool(re.search(r"sbReadList\([^;]*&(?:\w+->)?\w*ULSizePrev", body)),
          f"{device} must retain UL-format discovery")

print("PASS: UDPFS ISO-only scan and other-device UL isolation")
