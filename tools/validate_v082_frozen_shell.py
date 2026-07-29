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

LOCK_EXEMPLAR_KEYS = {
    "#bilingual-pane > section.paper-section": "sections",
    "#bilingual-pane .bilingual-unit": "bilingual_units",
    "#bilingual-pane .figure-card:not(.table-card)": "figures",
    "#bilingual-pane .table-card": "tables",
    "#bilingual-pane .reference-item": "references",
    "#quick-pane #overview .qa": "overview_questions_quick",
    "#overview-bilingual-folded .qa": "overview_questions_bilingual",
    "#figure-table-index .figure-index-section": "figure_index_sections",
    "#figure-table-index .figure-ref": "figure_index_buttons",
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(master: Path, shell: Path, lock_path: Path) -> dict[str, Any]:
    raw = shell.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    master_raw = master.read_text("utf-8")
    lock = json.loads(lock_path.read_text("utf-8"))
    errors: list[Any] = []

    parity = shell_lock.analyze(master, shell)
    if not parity.get("passed"):
        errors.append({"fixed_shell_parity": parity.get("errors", [])})

    html = soup.find("html")
    if html is None or html.get("data-v082-template") != "frozen-shell":
        errors.append("missing html[data-v082-template=frozen-shell]")

    exemplar_counts: dict[str, int] = {}
    lock_exemplars = lock.get("component_exemplars") or {}
    for selector, default_expected in EXPECTED_EXEMPLARS.items():
        lock_key = LOCK_EXEMPLAR_KEYS[selector]
        expected = int(lock_exemplars.get(lock_key, default_expected))
        actual = len(soup.select(selector))
        exemplar_counts[selector] = actual
        if actual != expected:
            errors.append(f"component exemplar {selector!r}: expected locked value {expected}, found {actual}")

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

    master_sha = sha256(master)
    shell_sha = sha256(shell)
    source_bytes = master.stat().st_size
    shell_bytes = shell.stat().st_size
    size_ratio = shell_bytes / max(1, source_bytes)
    if size_ratio >= 0.35:
        errors.append(f"frozen shell is still content-heavy: size ratio {size_ratio:.4f} >= 0.35")

    styles_master = shell_lock.core.style_hashes(BeautifulSoup(master_raw, "html.parser"))
    styles_shell = shell_lock.core.style_hashes(soup)
    if styles_master != styles_shell:
        errors.append("style blocks changed during shell extraction")

    locked_values = {
        "normalized_master_sha256": master_sha,
        "normalized_master_bytes": source_bytes,
        "frozen_shell_sha256": shell_sha,
        "frozen_shell_bytes": shell_bytes,
        "fixed_shell_dom_sha256": parity.get("candidate_shell_sha256"),
    }
    lock_mismatches = {
        key: {"expected": lock.get(key), "actual": actual}
        for key, actual in locked_values.items()
        if lock.get(key) != actual
    }
    if lock_mismatches:
        errors.append({"immutable_lock_mismatches": lock_mismatches})

    policy = lock.get("policy") or {}
    if any(policy.get(key) is not False for key in ("ai_may_generate_html", "ai_may_generate_css", "ai_may_generate_interaction_code")):
        errors.append("lock policy must prohibit AI-generated product code")

    return {
        "version": "v082-frozen-shell-gate-2",
        "lock": str(lock_path),
        "lock_version": lock.get("version"),
        "master": str(master),
        "master_sha256": master_sha,
        "master_bytes": source_bytes,
        "shell": str(shell),
        "shell_sha256": shell_sha,
        "shell_bytes": shell_bytes,
        "size_ratio": round(size_ratio, 6),
        "component_exemplars": exemplar_counts,
        "placeholder_count": raw.count("__V082_"),
        "fixed_shell_parity": parity,
        "locked_values": locked_values,
        "policy": policy,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a content-free V0.8.2 CANVAS shell against its immutable version lock")
    parser.add_argument("shell", type=Path)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path("config/v082_frozen_shell_lock.json"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = analyze(args.master, args.shell, args.lock)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
