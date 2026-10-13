"""RA: check game support runs on UDPFS games instead of refusing.

With ranet.c's mstack: link (test_ra_mstack_link.py) the support check reaches the PC while a
UDPFS chain owns the NIC, so menuCheckSelectedGameSupport no longer refuses UDPFS_MODE: UDPFS
Files games take the generic branch (hash through udpfs:/, watch list saved to udpfs:/RA/), like
UDPFS IMG games on BDM pages already did. The old refusal label stays in the language file
(append-only rule).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
menusys = (ROOT / "src/menusys.c").read_text(encoding="utf-8")
udpfs = (ROOT / "src/udpfssupport.c").read_text(encoding="utf-8")
base = (ROOT / "lng_tmpl/_base.yml").read_text(encoding="utf-8")

start = menusys.index("void menuCheckSelectedGameSupport(")
end = menusys.index("\n}\n", start) + 3
check = menusys[start:end]

assert "UDPFS_MODE" not in check, "UDPFS_MODE still refused by the support check"
assert "_STR_RA_NA_UDPFS" not in check, "the UDPFS refusal notice is still shown"
generic = check.index("support->itemGet != NULL && support->itemGetPrefix != NULL")
assert "sbHashGameDeferred(prefix, g->name, g->extension, g->startup, g->format)" in check[generic:]

# The generic branch is reachable for UDPFS: its item table provides both callbacks.
assert "&udpfsGetGame," in udpfs and "&udpfsGetPrefix," in udpfs
assert "- label: RA_NA_UDPFS" in base

print("PASS: the RA support check hashes UDPFS games through the generic branch")

# A watch list that reached memory but could not be saved (read-only share) must not be shown as
# plain success: the launch reads the file. raAskPC puts the notice's second line in info2.
ranet = (ROOT / "src/ranet.c").read_text(encoding="utf-8")
ask = ranet[ranet.index("int raAskPC("):]
ask = ask[:ask.index("\n}\n")]
save = ask[ask.index("if (saved == 0)"):]
assert "_STR_RA_WL_NOT_SAVED" in save[:save.index("}")], "an unsaved watch list is reported as success"
assert "- label: RA_WL_NOT_SAVED" in base
assert base.rstrip().endswith('"') and base.index("- label: RA_WL_NOT_SAVED") > base.index("- label: CAD_PAIR_UDPFS")
assert base.index("- label: RA_UDPFS_LOAD_FIRST") > base.index("- label: RA_WL_NOT_SAVED")
assert base.index("- label: CAD_UDPFS_IMG") > base.index("- label: RA_WL_NOT_SAVED")
print("PASS: an unsaved watch list is reported")
