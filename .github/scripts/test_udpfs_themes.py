"""Source-level guard for UDPFS THM discovery and the first scan of a remembered PS1 page.

UDPFS is a network filesystem whose server can become reachable after its menu support is initialized.
Theme discovery must therefore wait for the server, run before view-specific early returns, and avoid
re-registering the same remote themes on every refresh. A scan that started before the server answered
must keep the page polling (its "empty" result proves nothing), and a page whose L3 position was restored
at boot must still do its first scan -- the PS1 early return in NeedsUpdate sits before the "never
scanned" check (TwistedZeon, 09-29: remembered PS1 page blank until L3, and no THM themes).
"""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
src = (root / "src/udpfssupport.c").read_text(encoding="utf-8").replace("\r\n", "\n")
libview = (root / "src/libview.c").read_text(encoding="utf-8").replace("\r\n", "\n")
failures = []


def function_body(source, signature):
    start = source.find(signature)
    if start < 0:
        failures.append(f"missing {signature}")
        return ""
    brace = source.find("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    failures.append(f"unterminated {signature}")
    return ""


if "static int udpfsThemesScanned = 0;" not in src:
    failures.append("missing one-session UDPFS theme-scan latch")

init = function_body(src, "void udpfsInit(item_list_t *itemList)")
if init:
    for needle in ("thmReinit(udpfsBase);", "udpfsThemesScanned = 0;"):
        if needle not in init:
            failures.append(f"udpfsInit missing {needle}")
    if "if (udpfsBase != NULL)" not in init:
        failures.append("udpfsInit must only remove stale UDPFS theme registrations on re-init")

discover = function_body(src, "static void udpfsDiscoverThemes(void)")
if discover:
    expected = (
        "!udpfsThemesScanned && udpfsIomanModLoaded && udpfsServerAnswers()",
        'snprintf(themePath, sizeof(themePath), "%sTHM", udpfsPrefix);',
        'thmAddElements(themePath, "/", 1);',
        "udpfsThemesScanned = 1;",
    )
    for needle in expected:
        if needle not in discover:
            failures.append(f"udpfsDiscoverThemes missing {needle}")

needs = function_body(src, "static int udpfsNeedsUpdate(item_list_t *itemList)")
if needs:
    call = needs.find("udpfsDiscoverThemes();")
    if call < 0:
        failures.append("udpfsNeedsUpdate does not try theme discovery")
    for label, needle in (("dirty-view", "libViewConsumeDirty(itemList->mode)"),
                          ("folder-dirty", "folderConsumeDirty(itemList->mode)"),
                          ("server-wait", "if (udpfsWaitingForServer)"),
                          ("PS1-view", "libListViewActive(itemList) == LIB_VIEW_PS1")):
        pos = needs.find(needle)
        if call >= 0 and pos >= 0 and call > pos:
            failures.append(f"theme discovery must run before the {label} early return")

update = function_body(src, "static int udpfsUpdateGameList(item_list_t *itemList)")
if update:
    asked = update.find("answeredBefore = udpfsServerAnswers();")
    scan = update.find("cueFillGameList(")
    if asked < 0:
        failures.append("udpfsUpdateGameList must ask the server BEFORE scanning")
    elif scan >= 0 and asked > scan:
        failures.append("the pre-scan server check must come before the Ember scan")
    if "if (answeredBefore)\n        udpfsDiscoverThemes();" not in update:
        failures.append("a scan that reaches the server must also register its themes")
    if "udpfsSetWaitingForServer(!answeredBefore || (!reached && !udpfsServerAnswers()));" not in update:
        failures.append("a scan that started before the server answered must keep polling")

load = function_body(libview, "void libViewLoadFromConfig(config_set_t *configLast)")
if load:
    if "libViewDecodeRing(value, retainedView, restored);" not in load:
        failures.append("libViewLoadFromConfig must record which modes had a view restored")
    if "if (restored[mode] || mixedViewInitialized[mode])\n            libDirty[mode] = 1;" not in load:
        failures.append("a page restored onto a remembered view must be marked for its first scan")

if failures:
    print("UDPFS theme discovery checks FAILED:")
    for failure in failures:
        print(" - " + failure)
    sys.exit(1)

print("UDPFS: server-gated THM registration, pre-scan polling decision and restored-view first scan verified")
