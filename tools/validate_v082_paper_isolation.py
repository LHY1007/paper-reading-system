#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

CANONICAL_DOI = "10.1016/j.cell.2026.05.031"
CANONICAL_SENTINELS = [
    "Cellular architecture and neighborhood-informed virtual spatial tumor profiling from histopathology",
    "This study integrated seven study cohorts to develop, validate, and clinically evaluate the CANVAS framework.",
    "A total of 457 lung tumor specimens were profiled by CODEX",
    "CODEX and matched H&E data: Zenodo 20263843",
]


def parse_json_script(soup: BeautifulSoup, script_id: str) -> Any:
    node = soup.find("script", id=script_id)
    if not node:
        return None
    try:
        return json.loads(node.get_text() or "null")
    except json.JSONDecodeError:
        return "__INVALID_JSON__"


def extract_set(script: str, variable: str) -> list[str] | None:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(variable)}\s*=\s*new Set\((\[[^;]*?\])\)", script, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def validate(html_path: Path, manifest_path: Path) -> dict[str, Any]:
    raw = html_path.read_text("utf-8")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    soup = BeautifulSoup(raw, "html.parser")
    errors: list[str] = []

    paper = manifest["paper"]
    is_canvas_paper = paper.get("doi") == CANONICAL_DOI
    if not is_canvas_paper:
        for sentinel in [CANONICAL_DOI, *CANONICAL_SENTINELS]:
            if sentinel in raw:
                errors.append(f"canonical CANVAS content leaked: {sentinel[:90]}")

    expected_refs = {
        str(ref["id"]): {k: v for k, v in {"text": ref["text"], "url": ref.get("url")}.items() if v}
        for ref in manifest.get("references", [])
    }
    actual_refs = parse_json_script(soup, "referenceData")
    if actual_refs != expected_refs:
        errors.append("referenceData does not match manifest references")

    preview = soup.select_one("#crossRefPreviewStore")
    if not preview:
        errors.append("missing #crossRefPreviewStore content slot")
    else:
        preview_text = " ".join(preview.get_text(" ", strip=True).split())
        if preview_text:
            errors.append(f"crossRefPreviewStore contains stale paper text: {preview_text[:120]}")
        if preview.get("data-paper-key") != paper["key"]:
            errors.append("crossRefPreviewStore data-paper-key mismatch")

    expected_study = sorted(
        a["id"] for a in manifest.get("assets", [])
        if a.get("kind") == "figure" and a.get("study")
    )
    for script_id, variable in [
        ("canvas-reader-v062-script", "supported"),
        ("canvas-v077-script", "STUDY_IDS"),
        ("canvas-v082-script", "STUDY_IDS"),
    ]:
        node = soup.find("script", id=script_id)
        actual = extract_set(node.get_text() if node else "", variable)
        if actual is None:
            errors.append(f"unable to parse {script_id}:{variable}")
        elif sorted(actual) != expected_study:
            errors.append(f"{script_id}:{variable} {sorted(actual)} != {expected_study}")

    body_key = soup.body.get("data-paper-key") if soup.body else None
    if body_key != paper["key"]:
        errors.append("body data-paper-key mismatch")

    html_title = soup.title.get_text(strip=True) if soup.title else ""
    if paper["title_en"] not in html_title:
        errors.append("HTML title does not contain manifest title")
    if paper["title_en"] not in (soup.select_one(".hero h1").get_text(" ", strip=True) if soup.select_one(".hero h1") else ""):
        errors.append("hero title does not match manifest title")

    return {
        "file": html_path.name,
        "manifest": manifest_path.name,
        "paper_key": paper["key"],
        "reference_count": len(expected_refs),
        "study_ids": expected_study,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure no CANVAS paper data leaks into another V0.8.2 reader")
    parser.add_argument("html", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    report = validate(args.html, args.manifest)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"] and not args.diagnostic:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
