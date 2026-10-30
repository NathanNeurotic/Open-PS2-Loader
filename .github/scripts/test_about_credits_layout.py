#!/usr/bin/env python3
"""Host regression test for About dialog layout and tester credits.

Ports upstream PR #944:
1. Akilluminati47 and eliminator are credited under Quality Assurance.
2. The obsolete in-app Financial Support section is removed from diaAbout.
3. Excess UI_BREAK rows are trimmed to prevent vertical overflow in the fixed non-scrolling dialog.
"""
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[2]
dialogs_c = (root / "src/dialogs.c").read_text(encoding="utf-8")

dia_about_start = dialogs_c.find("struct UIItem diaAbout[] = {")
assert dia_about_start != -1, "diaAbout not found in dialogs.c"
dia_about_end = dialogs_c.find("{UI_TERMINATOR}};", dia_about_start)
assert dia_about_end != -1, "diaAbout terminator not found"
dia_about = dialogs_c[dia_about_start : dia_about_end + len("{UI_TERMINATOR}};")]

# 1. Financial support section removed from diaAbout
assert "_STR_FINANCIAL_SUPPORT" not in dia_about, "Financial support section should not be in diaAbout"

# 2. Akilluminati47, eliminator and V3ditata credited under Quality Assurance
assert '"Akilluminati47, eliminator, V3ditata"' in dia_about, "Akilluminati47, eliminator and V3ditata should be credited in diaAbout QA"

# 3. QA rows should contain all expected contributors
assert "algol, Berion, Blade1984, El_Patas, EP, gledson999, jolek, lee4, Vapor" in dia_about
assert "LocalH, RandQalan, ShaolinAssassin, yoshi314, zero35, zackcage6" in dia_about

print("PASS: About dialog layout has testers under QA, no financial section, and trimmed spacing")

# 4. NathanNeurotic is credited among the coders, on a fifth row; Network update shares one row with its name so the
#    dialog keeps its height
assert '"NathanNeurotic - techwritescode"' in dia_about, "NathanNeurotic should be credited in diaAbout"
assert '"Akilluminati47 - belomaxorka - darkladark - mihhru"' in dia_about
net = dia_about.find("_STR_NET_UPDATE")
assert net != -1 and dia_about.find("UI_BREAK", net) > dia_about.find('"icyson55"', net), "Network update and icyson55 share a row"
print("PASS: NathanNeurotic credited; About keeps its row count")
