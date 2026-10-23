#!/usr/bin/env python3
"""Exercise the Makefile's version calculation on real full and shallow Git histories."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/rolling-release.yml").read_text(encoding="utf-8")
jobs = dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|\Z)", workflow, re.M | re.S))
for name in ("build-rolling-pinned", "build-rolling-ps2dev-latest",
             "build-rolling-officialsdk", "build-rolling-official-pinned"):
    checkout = re.search(r"uses: actions/checkout@[^\n]+\n(.*?)(?=\n      -|\Z)", jobs[name], re.S).group(1)
    assert re.search(r"^          fetch-depth: 0$", checkout, re.M), name
    assert "--unshallow || true" not in jobs[name], name
pr_workflow = (ROOT / ".github/workflows/flavours.yml").read_text(encoding="utf-8")
pr_build = pr_workflow.split("\n  build-flavour:\n", 1)[1]
pr_checkout = re.search(r"uses: actions/checkout@[^\n]+\n(.*?)(?=\n      -|\Z)", pr_build, re.S).group(1)
assert re.search(r"^          fetch-depth: 0$", pr_checkout, re.M)

# Evaluate the production version block, without importing the PS2SDK build rules.
version_inputs = "\n".join(re.findall(r"^(?:VERSION|SUBVERSION|PATCHLEVEL|EXTRAVERSION) = .*", makefile, re.M))
version_logic = makefile[makefile.index("CODE_ANCHOR ="):makefile.index("FRONTEND_OBJS =")]
version_target = re.search(r"^oplversion:\n\t[^\n]+", makefile, re.M).group()
fixture_makefile = version_inputs + "\n" + version_logic + "\n" + version_target + "\n"
env = dict(os.environ)
for name in ("REVISION", "RELEASE_CHANNEL", "LOCALVERSION", "MAKEFLAGS", "MFLAGS"):
    env.pop(name, None)
env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)


def run(cwd, *args):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True, stderr=subprocess.PIPE).strip()


def git(cwd, *args):
    return run(cwd, "git", "-c", "core.fsmonitor=false", *args)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    full, shallow = tmp / "full", tmp / "shallow"
    full.mkdir()
    git(full, "init", "-q")
    git(full, "config", "user.name", "Version regression")
    git(full, "config", "user.email", "version-test@example.invalid")
    git(full, "config", "commit.gpgsign", "false")
    (full / "Makefile").write_text(fixture_makefile, encoding="utf-8")
    git(full, "add", "Makefile")
    git(full, "commit", "-qm", "Initial source")
    (full / "src.c").write_text("int version_fixture;\n", encoding="utf-8")
    git(full, "add", "src.c")
    git(full, "commit", "-qm", "Source change")
    code_hash = git(full, "rev-parse", "--short=7", "HEAD")
    (full / ".github").mkdir()
    (full / ".github/ci.yml").write_text("fixture\n", encoding="utf-8")
    git(full, "add", ".github/ci.yml")
    git(full, "commit", "-qm", "CI-only change")
    expected = "v1.2.0-Beta-5-" + code_hash
    assert run(full, "make", "--no-print-directory", "oplversion") == expected

    git(tmp, "clone", "-q", "--depth=1", full.as_uri(), str(shallow))
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    bad = run(shallow, "make", "--no-print-directory", "LOCALVERSION=PS2DEVPINNED", "oplversion")
    assert bad.startswith("v1.2.0-Beta-3-") and code_hash not in bad, bad

    git(shallow, "fetch", "-q", "--unshallow")
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "false"
    for flavour in ("PS2DEVPINNED", "OFFICIALPINNED", "PS2DEVROLLING", "OFFICIALROLLING"):
        actual = run(shallow, "make", "--no-print-directory", "LOCALVERSION=" + flavour, "oplversion")
        assert actual == expected + "-" + flavour, (flavour, actual)
    channel = run(shallow, "make", "--no-print-directory", "REVISION=42", "RELEASE_CHANNEL=Korium", "oplversion")
    assert channel == "v1.2.0-Beta-42-Korium-" + code_hash, channel
    git(full, "tag", "v9.8.7")
    tagged = run(full, "make", "--no-print-directory", "LOCALVERSION=OFFICIALROLLING", "oplversion")
    assert tagged == "v9.8.7-OFFICIALROLLING", tagged

print("Release versions: shallow Beta-3 reproduced; full history restores the revision and source hash for all four SDKs; channel overrides and tags preserved")
