#!/usr/bin/env python3
"""Report RiptOPL translation coverage without mistaking English fallback for translation.

Usage: python3 tools/audit_translations.py [--strict] [--json]
Reads the same Makefile language names, base labels, upstream community files (if
downloaded) and fork overlays used by the release compiler. No files are changed.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = re.compile(r"%(?:\d+\$)?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|j|z|t|L)?[diouxXfFeEgGaAcspn]")
# Literal %% is not a conversion placeholder.


def format_tokens(value: str) -> list[str]:
    return SPEC.findall(value.replace("%%", ""))


def languages() -> list[str]:
    """Read every continuation line in Makefile's TRANSLATIONS assignment."""
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^TRANSLATIONS[ \t]*=", line) is None:
            continue
        value = line.split("=", 1)[1].strip()
        while value.endswith("\\"):
            if i + 1 >= len(lines):
                raise ValueError("Unterminated TRANSLATIONS line continuation")
            value = value[:-1].rstrip() + " " + lines[i + 1].strip()
            i += 1
        names = value.split()
        if not names or len(names) != len(set(names)) or any("\\" in x for x in names):
            raise ValueError("Malformed or duplicate Makefile TRANSLATIONS entries")
        return names
    raise ValueError("Makefile TRANSLATIONS list not found")

def read_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = document.get("translations", {})
    if not isinstance(entries, dict):
        raise ValueError(f"{path}: translations is not a map")
    return {key: value for key, value in entries.items() if isinstance(value, str)}


def audit() -> dict:
    base = yaml.safe_load((ROOT / "lng_tmpl/_base.yml").read_text(encoding="utf-8"))
    entries = base["gui_strings"]
    labels = [entry["label"] for entry in entries]
    if len(labels) != len(set(labels)):
        raise ValueError("Duplicate translation IDs in lng_tmpl/_base.yml")
    english = {entry["label"]: entry["string"] for entry in entries}
    by_language = {}
    errors = []
    for name in languages():
        overlay_path = ROOT / "lng_fork" / (name + ".yml")
        overlay = read_map(overlay_path)
        upstream = read_map(ROOT / "lng_src" / (name + ".yml"))
        # Mirrors lang_compiler.py: a valid upstream translation wins; overlay
        # fills only strings that upstream marks untranslated/missing.
        merged = dict(overlay)
        merged.update(upstream)
        unknown = sorted(set(overlay) - set(english))
        for key in unknown:
            errors.append(f"{name}: overlay has unknown label {key}")
        for key, value in overlay.items():
            if key in english and format_tokens(value) != format_tokens(english[key]):
                errors.append(
                    f"{name}/{key}: printf tokens {format_tokens(value)} differ from "
                    f"English {format_tokens(english[key])}"
                )
        translated = {key for key in labels if key in merged and merged[key] != english[key]}
        fallback = [key for key in labels if key not in merged or merged[key] == english[key]]
        by_language[name] = {
            "upstream_available": (ROOT / "lng_src" / (name + ".yml")).exists(),
            "overlay_entries": len(overlay),
            "translated_entries": len(translated),
            "english_fallback_entries": len(fallback),
            "recent_fallback_labels": [key for key in labels[-60:] if key in fallback],
            "missing_overlay": not overlay_path.exists(),
        }
    return {
        "total_strings": len(labels),
        "built_languages": len(by_language),
        "recent_window": min(len(labels), 60),
        "upstream_present": (ROOT / "lng_src").is_dir(),
        "languages": by_language,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="fail on unsafe format changes and unknown keys")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"{report['built_languages']} languages / {report['total_strings']} strings; "
            f"upstream translations present: {report['upstream_present']}"
        )
        for language, counts in report["languages"].items():
            print(
                f"{language:17} overlay={counts['overlay_entries']:3} "
                f"translated={counts['translated_entries']:3} "
                f"English fallback={counts['english_fallback_entries']:3} "
                f"recent fallback={len(counts['recent_fallback_labels']):2}/{report['recent_window']}"
            )
        for err in report["errors"]:
            print("ERROR:", err)
    return 1 if args.strict and report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
