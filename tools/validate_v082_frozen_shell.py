#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

import validate_v082_canvas_shell_lock as shell_lock


EXPECTED_EXEMPLARS = {
    "#bilingual-pane > section.paper-section": 1,
    "#bilingual-pane .bilingual-unit": 1,
    "#bilingual-pane .figure-card:not(.table-card)": 1,
    "#bilingual-pane .table-card": 1,
    "#bilingual-pane .reference-item": 1,
    "#quick-pane #overview .qa": 1,
    "#overview-bilingual-folded .qa": 1,
    "#figure-table-index .figure-index-section": 1,
    "#figure-table-index .figure-ref": 1,
}

REQUIRED_PLACEHOLDERS = {
    "__V082_PAPER_TITLE__",
    "__V082_PAPER_TITLE_ZH__",
    "__V082_PAPER_AUTHORS__",
    "__V082_OVERVIEW_QUESTION__",
    "__V082_OVERVIEW_ANSWER__",
    "__V082_SECTION__",
    "__V082_ENGLISH_PARAGRAPH__",
    "__V082_CHINESE_PARAGRAPH__",
    "__V082_FIGURE__",
    "__V082_TABLE__",
    "__V082_REFERENCE__",
}


def analyze(master: Path, shell: Path) -> dict[str, Any]:
    raw = shell.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    master_raw = master.read_text("utf-8")
    errors: list[str] = []

    parity = shell_lock.analyze(master, shell)
    if not parity.get("passed"):
        errors.append({"fixed_shell_parity": parity.get("errors", [])})

    html = soup.find("html")
    if html is None or html.get("data-v082-template") != "frozen-shell":
        errors.append("missing html[data-v082-template=frozen-shell]")

    exemplar_counts: dict[str, int] = {}
    for selector, expected in EXPECTED_EXEMPLARS.items():
        actual = len(soup.select(selector))
        exemplar_counts[selector] = actual
        if actual != expected:
            errors.append(f"component exemplar {selector!r}: expected {expected}, found {actual}")

    missing_placeholders = sorted(token for token in REQUIRED_PLACEHOLDERS if token not in raw)
    if missing_placeholders:
        errors.append({"missing_placeholders": missing_placeholders})

    if "data:image/" in raw:
        errors.append("embedded paper image data remains in frozen shell")

    source_specific_tokens = [
        "10.1016/j.cell.2026.05.031",
        "Cellular architecture and neighborhood-informed virtual spatial tumor profiling",
        "Yuchen Li",
        "Ruijiang Li",
    ]
    residues = [token for token in source_specific_tokens if token.lower() in raw.lower()]
    if residues:
        errors.append({"CANVAS_content_residues": residues})

    source_bytes = master.stat().st_size
    shell_bytes = shell.stat().st_size
    size_ratio = shell_bytes / max(1, source_bytes)
    if size_ratio >= 0.35:
        errors.append(f"frozen shell is still content-heavy: size ratio {size_ratio:.4f} >= 0.35")

    styles_master = shell_lock.core.style_hashes(BeautifulSoup(master_raw, "html.parser"))
    styles_shell = shell_lock.core.style_hashes(soup)
    if styles_master != styles_shell:
        errors.append("style blocks changed during shell extraction")

    return {
        "version": "v082-frozen-shell-gate-1",
        "master": str(master),
        "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "master_bytes": source_bytes,
        "shell": str(shell),
        "shell_sha256": hashlib.sha256(shell.read_bytes()).hexdigest(),
        "shell_bytes": shell_bytes,
        "size_ratio": round(size_ratio, 6),
        "component_exemplars": exemplar_counts,
        "placeholder_count": raw.count("__V082_"),
        "fixed_shell_parity": parity,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate that a generated template is a content-free, immutable V0.8.2 CANVAS shell")
    parser.add_argument("shell", type=Path)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = analyze(args.master, args.shell)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
