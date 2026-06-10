#!/usr/bin/env python3
"""Validate SKILL.md against the Agent Skills spec (agentskills.io/specification).

Checks: frontmatter parses; `name` is valid and matches the directory; description
length; recommended body length; and that every relative link target exists.

    python tests/test_skill_format.py        # run from repo root
"""
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    oks: list[str] = []
    fails: list[str] = []

    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        print("[XX] no YAML frontmatter")
        return 1
    meta = yaml.safe_load(m.group(1))

    name = meta.get("name", "")
    (oks if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
     else fails).append(f"name valid: {name!r}")
    (oks if name == ROOT.name else fails).append(
        f"name matches directory ({ROOT.name})")
    desc = meta.get("description", "")
    (oks if 1 <= len(desc) <= 1024 else fails).append(
        f"description length {len(desc)} (<=1024)")

    for ln in sorted({l for l in re.findall(r"\]\((?!https?:)([^)]+)\)", text)}):
        target = (ROOT / ln.split("#")[0]).resolve()
        (oks if target.exists() else fails).append(f"link: {ln}")

    body_lines = text.split("\n---\n", 1)[-1].count("\n")
    (oks if body_lines <= 500 else fails).append(
        f"body {body_lines} lines (rec <=500)")

    print(f"PASS: {len(oks)}")
    for o in oks:
        print("  [OK]", o)
    if fails:
        print(f"FAIL: {len(fails)}")
        for f in fails:
            print("  [XX]", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
