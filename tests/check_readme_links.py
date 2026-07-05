#!/usr/bin/env python3
"""Validate local Markdown links and heading anchors."""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def slugify(text: str) -> str:
    text = re.sub(r"\s+#*$", "", text.strip().lower())
    chars: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char.isspace() or char == "-":
            chars.append("-")
        elif category[0] in {"P", "S", "C"}:
            continue
        else:
            chars.append(char)
    return "".join(chars).strip("-")


def anchors_for(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = slugify(match.group(2))
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def iter_markdown_files() -> list[Path]:
    ignored = {".git", ".claude", ".venv", "__pycache__"}
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.md"):
        if ignored.intersection(path.relative_to(REPO_ROOT).parts):
            continue
        files.append(path)
    return files


def split_target(target: str) -> tuple[str, str]:
    if "#" not in target:
        return target, ""
    path_part, anchor = target.split("#", 1)
    return path_part, anchor


def is_external(target: str) -> bool:
    return re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) is not None


def main() -> None:
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}

    for markdown in iter_markdown_files():
        text = markdown.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            raw_target = match.group(1).strip()
            if not raw_target or is_external(raw_target):
                continue

            raw_target = raw_target.split()[0]
            path_part, anchor = split_target(raw_target)
            if path_part:
                target_path = (markdown.parent / unquote(path_part)).resolve()
            else:
                target_path = markdown

            try:
                target_path.relative_to(REPO_ROOT)
            except ValueError:
                errors.append(f"{markdown}: link escapes repository: {raw_target}")
                continue

            if not target_path.exists():
                errors.append(f"{markdown}: missing link target: {raw_target}")
                continue

            if anchor:
                if target_path.suffix.lower() != ".md":
                    errors.append(f"{markdown}: anchor on non-Markdown target: {raw_target}")
                    continue
                if target_path not in anchor_cache:
                    anchor_cache[target_path] = anchors_for(target_path)
                normalized_anchor = unquote(anchor).lower()
                if normalized_anchor not in anchor_cache[target_path]:
                    errors.append(f"{markdown}: missing anchor {anchor!r} in {target_path}")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        sys.exit(1)

    print("Markdown links OK")


if __name__ == "__main__":
    main()
