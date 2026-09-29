"""Source-level guard for UDPFS THM discovery.

UDPFS is a network filesystem whose server can become reachable after its menu support is initialized.
Theme discovery must therefore wait for the server, run before view-specific early returns, and avoid
re-registering the same remote themes on every refresh.
"""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
src = (root / "src/udpfssupport.c").read_text(encoding="utf-8").replace("\r\n", "\n")
failures = []


def function_body(signature):
    start = src.find(signature)
    if start < 0:
        failures.append(f"missing {signature}")
        return ""
    brace = src.find("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    failures.append(f"unterminated {signature}")
    return ""


if "static int udpfsThemesScanned = 0;" not in src:
    failures.append("missing one-session UDPFS theme-scan latch")

init = function_body("void udpfsInit(item_list_t *itemList)")
if init:
    for needle in ("thmReinit(udpfsBase);", "udpfsThemesScanned = 0;"):
        if needle not in init:
            failures.append(f"udpfsInit missing {needle}")
    if "if (udpfsBase != NULL)" not in init:
        failures.append("udpfsInit must only remove stale UDPFS theme registrations on re-init")

needs = function_body("static int udpfsNeedsUpdate(item_list_t *itemList)")
if needs:
    expected = (
        "!udpfsThemesScanned && udpfsIomanModLoaded && udpfsServerAnswers()",
        'snprintf(themePath, sizeof(themePath), "%sTHM", udpfsPrefix);',
        'thmAddElements(themePath, "/", 1);',
        "udpfsThemesScanned = 1;",
    )
    for needle in expected:
        if needle not in needs:
            failures.append(f"udpfsNeedsUpdate missing {needle}")

    discover = needs.find("!udpfsThemesScanned && udpfsIomanModLoaded && udpfsServerAnswers()")
    dirty = needs.find("libViewConsumeDirty(itemList->mode)")
    ps1 = needs.find("libListViewActive(itemList) == LIB_VIEW_PS1")
    if discover >= 0 and dirty >= 0 and discover > dirty:
        failures.append("theme discovery must run before the dirty-view early return")
    if discover >= 0 and ps1 >= 0 and discover > ps1:
        failures.append("theme discovery must run before the PS1-view early return")

if failures:
    print("UDPFS theme discovery checks FAILED:")
    for failure in failures:
        print(" - " + failure)
    sys.exit(1)

print("UDPFS theme discovery: server-gated THM registration and re-init cleanup verified")
