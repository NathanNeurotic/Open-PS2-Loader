"""Compact release notes shared by publication and normalization."""
import argparse
import json
import pathlib
import re
import subprocess
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parents[2]


def description(name):
    fixed = {
        "RIPTOPL.ELF": "Standard loader update; replace your existing ELF.",
        "RIPTOPL-RA.ELF": "RetroAchievements loader update (requires xeRAbora v0.1.0-alpha.15).",
        "APP_RIPTOPL.psu": "Standard app for memory-card import; app files only.",
        "APP_RIPTOPL-RA.psu": "RetroAchievements app for memory-card import; app files only.",
    }
    if name in fixed:
        return fixed[name]
    if name.endswith("-src.zip"):
        return "Source code snapshot."
    for prefix, text in (
        ("RIPTOPL-RetroAchievements-", "Full RetroAchievements kit: loader, artwork, PSU and shared cores; requires xeRAbora v0.1.0-alpha.15."),
        ("RIPTOPL-RA-", "RetroAchievements package."),
        ("RIPTOPL-VARIANTS-", "Alternative loaders with extra features, controller emulation and DualSense support."),
        ("RIPTOPL-DEBUG-", "Debug loaders for troubleshooting."),
        ("RIPTOPL-LANGS-", "Extra interface languages and fonts."),
        ("RIPTOPL-", "Full install: loader, artwork, PSU, POPStarter, Ember, Neutrino and companion-tool links."),
    ):
        if name.startswith(prefix) and name.endswith(".zip"):
            return text
    return "Additional release file."


def staged_asset(name):
    # Match normalization's cleanup; don't advertise temporary build uploads.
    return not (
        (name.endswith(".ELF") and name not in ("RIPTOPL.ELF", "RIPTOPL-RA.ELF"))
        or "MANIFEST" in name
        or name in ("SHA256SUMS.txt", "DETAILED_CHANGELOG")
    )


def credits(readme):
    section = re.search(r"^## External Tools & Services\n(.*?)(?=^## |\Z)", readme, re.M | re.S)
    if not section:
        raise ValueError("README is missing External Tools & Services credits")
    # Only linked name and author; setup instructions stay in the guides.
    lines = [line.split(" — ", 1)[0] for line in section[1].splitlines() if line.startswith("- ")]
    if not lines:
        raise ValueError("README contains no external-tool credits")
    for i, line in enumerate(lines):
        if "github.com/Gageformer/Ember)" in line:
            lines[i] += " · [official releases](https://github.com/Gageformer/Ember/releases)"
    return "\n".join(lines)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def changelog(revision, base):
    # Resolve explicitly; never substitute HEAD when normalizing an older release.
    sha = git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}")
    # Skip merge bookkeeping, including Korium's repeated sync merges; show the
    # implementation commits reachable from this build in both channels.
    history = git("log", "--no-merges", "-10", "--format=%H%x00%s", sha, "--")
    entries = []
    for record in history.splitlines():
        commit, title = record.split("\x00", 1)
        title = re.sub(r"([\\`*_[\]<>])", r"\\\1", title)
        entries.append(f"- {title} ([{commit[:8]}]({base}/commit/{commit}))")
    if not entries:
        raise ValueError("Release commit has no changelog entries")
    return sha, "\n".join(entries)


def render(assets, tag, revision, repository, server, version, neutrino, readme):
    base = f"{server.rstrip('/')}/{repository}"
    sha, changes = changelog(revision, base)
    edition = "Rolling (Korium)" if tag == "rolling-korium" else "Rolling" if tag == "rolling" else tag
    label = "Development build. " if tag.startswith("rolling") else ""
    if tag == "rolling-korium":
        label += "Korium Komblete built-in theme. "
    header = f"**RiptOPL {edition}** — {label}[{sha[:8]}]({base}/commit/{sha})"
    if version:
        header += f" · `{version}`"
    downloads = []

    def order(name):
        if description(name).startswith("Full install:"):
            return (0, name)
        preferred = ("RIPTOPL.ELF", "RIPTOPL-RA.ELF", "APP_RIPTOPL.psu", "APP_RIPTOPL-RA.psu")
        return (1 + preferred.index(name), name) if name in preferred else (6, name)

    for name in sorted(set(assets), key=order):
        url = f"{base}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"
        downloads.append(f"- [{name}]({url}) — {description(name)}")
    if not downloads:
        raise ValueError("Cannot publish notes without attached downloads")
    # Neutrino Watch consumes this exact phrase, including the following space.
    marker = f"<!-- Neutrino Included build: {neutrino} -->\n\n" if neutrino else ""
    return (
        header + "\n\n"
        + "<details>\n<summary>Changelog</summary>\n\nLatest 10 commits included in this build:\n\n" + changes
        + f"\n\n[Full changelog]({base}/commits/{sha})\n\n</details>\n\n"
        + "<details>\n<summary>Downloads</summary>\n\n" + "\n".join(downloads)
        + "\n\n[Installation and guides](https://nathanneurotic.github.io/Open-PS2-Loader/)\n\n</details>"
        + "\n\n<details>\n<summary>Credits</summary>\n\n" + credits(readme)
        + "\n\n</details>\n\n" + marker
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--assets-dir", type=pathlib.Path)
    source.add_argument("--release-json", type=pathlib.Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--server", default="https://github.com")
    parser.add_argument("--version", default="")
    parser.add_argument("--neutrino-version", default="")
    args = parser.parse_args()
    version, neutrino = args.version, args.neutrino_version
    if args.release_json:
        release = json.loads(args.release_json.read_text(encoding="utf-8-sig"))
        assets = [asset["name"] for asset in release["assets"]]
        body = release.get("body") or ""
        match = re.search(r"Included build: ([^\s]+)", body)
        neutrino = neutrino or (match[1] if match else "")
        match = re.search(r"`(v[^`\n]+)`", body)
        version = version or (match[1] if match else "")
    else:
        assets = [p.name for p in args.assets_dir.iterdir() if p.is_file() and staged_asset(p.name)]
        if not neutrino:
            parser.error("--neutrino-version is required for a new build")
    print(render(assets, args.tag, args.revision, args.repository, args.server,
                 version, neutrino, (ROOT / "README.md").read_text(encoding="utf-8")), end="")


if __name__ == "__main__":
    main()
