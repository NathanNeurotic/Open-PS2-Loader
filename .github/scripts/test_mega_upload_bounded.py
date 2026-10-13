"""The MEGA archive upload can never hold a release hostage.

The rolling release is published BEFORE the MEGA step, but "Normalize Release Assets" and the
RetroAchievements release only start when the whole Rolling Release run succeeds. On 2026-10-13 the
MEGA upload (normally 7 s) hung for 40+ minutes with no timeout, so both rolling releases sat with
their raw 21-file asset set and rolling-ra fell behind. The step is bounded and optional.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
workflow = (ROOT / ".github/workflows/rolling-release.yml").read_text(encoding="utf-8")
start = workflow.index("      - name: Upload archive and regular ELFs in all 4 flavours to MEGA")
end = workflow.index("\n      - name:", start + 10) if "\n      - name:" in workflow[start + 10:] else len(workflow)
step = workflow[start:workflow.index("\n\n", start)]

minutes = re.search(r"^        timeout-minutes: (\d+)$", step, re.M)
assert minutes and 1 <= int(minutes.group(1)) <= 15, "the MEGA upload needs a short timeout"
assert re.search(r"^        continue-on-error: true$", step, re.M), "a MEGA failure must not fail the release run"
print("PASS: MEGA upload is bounded and optional")
