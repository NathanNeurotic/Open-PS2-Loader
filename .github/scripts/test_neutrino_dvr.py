#!/usr/bin/env python3
"""Source contract for the reserved DESR DVR Neutrino handoff.

This is a host-side guard. It does not assert that RiptOPL can enumerate DVR games,
nor substitute for an actual PSX DESR hardware test.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
s = (ROOT / "src/system.c").read_text(encoding="utf-8")
d = (ROOT / "docs/NEUTRINO.md").read_text(encoding="utf-8")

def require(needle: str, source: str = s) -> None:
    assert needle in source, f"missing DVR contract: {needle}"

require('if (!strcmp(driver, "dvr"))')
require('return "dvr";')
require('open("rom0:PSXVER", O_RDONLY)')
require('neutrinoArgHasActiveFlag(gNeutrinoArgs, "-qb")')
require('neutrinoArgHasActiveFlag(extraArgs, "-qb")')
require('neutrinoArgHasActiveFlag(gNeutrinoArgs, "-bsdfs=")')
require('!strcmp(deviceName, "dvr")')
require('!strcmp(deviceName, "udpfs") || !strcmp(deviceName, "dvr")')
require('bsd-dvr', d)
require('not yet a game source', d)
print("PASS: reserved DESR DVR Neutrino backend preflight; discovery is not yet integrated")
