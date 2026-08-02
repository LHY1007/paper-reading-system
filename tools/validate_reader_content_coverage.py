#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup

FEATURE_TOKENS = {
    "mode_panes": "mode-pane",
    "bilingual_units": "bilingual-unit",
    "right_viewer": "viewer",
    "figure_index": "figure-index",
    "settings": "settings",
    "reference_popover": "reference-pop",
    "left_resizer": "leftResizeHandle",
    "right_resizer": "rightResizeHandle",
    "study_mode": "study",
    "annotation": "annotation",
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:[-’'][A-Za-z]+)*|\d+(?:\.\d+)?|[\u4e00-\u9fff]", text or ""))


def page_count(soup: BeautifulSoup) -> int | None:
    for node in soup.select(".metadata span, .paper-info, .hero"):
        match = re.search(r"PDF\s*(\d+)\s*页", node.get_text(" ", strip=True), re.I)
        if match:
            return int(match.group(1))
    return None


def collect_nodes(soup: BeautifulSoup, selectors: Iterable[str]) -> list:
    found = []
    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            key = id(node)
            if key not in seen:
                found.append(node)
                seen.add(key)
    return found


def is_explicitly_truncated(text: str) -> bool:
    """Use rejection-oriented signals only; avoid flagging normal citation endings."""
    if re.search(r"[A-Za-z]{2,}-$", text):
        return True
    if re.search(r"\bFigures?\s+\d+[A-Z]?$", text):
        return True
    if re.search(r"\b(?:and|or|of|the|a|an|to|for|with|from|in|on|by|as|at|that|which|while)$", text, re.I) and len(text) > 180:
        return True
    return False


def analyze(path: Path, baseline: Path | None = None, expected_body_blocks: int | None = None) -> dict:
    raw = path.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    units = collect_nodes(soup, [".para-card", ".bilingual-unit"])
    en_nodes = collect_nodes(soup, [".para-card .lang.en", ".bilingual-unit .source-block"])
    zh_nodes = collect_nodes(soup, [".para-card .lang.zh", ".bilingual-unit .translation-block"])
    appendix_nodes = collect_nodes(soup, [".appendix-text", "#appendix .source-fragments", "#appendix pre"])
    en_texts = [norm(n.get_text(" ", strip=True)) for n in en_nodes]
    zh_texts = [norm(n.get_text(" ", strip=True)) for n in zh_nodes]
    appendix_text = norm(" ".join(n.get_text(" ", strip=True) for n in appendix_nodes))
    core_en_words = sum(word_count(x) for x in en_texts)
    core_zh_chars = sum(len(re.findall(r"[\u4e00-\u9fff]", x)) for x in zh_texts)
    appendix_words = word_count(appendix_text)
    coverage = core_en_words / appendix_words if appendix_words else None
    pdf_block_coverage = len(units) / expected_body_blocks if expected_body_blocks else None
    pages = page_count(soup)

    malformed_nested_p = len(soup.select("p p"))
    duplicated_overview = len(soup.select(".overview-card .overview-card"))
    numeric_citation_corruption = len(re.findall(r",\s*<sup[^>]*class=[\"'][^\"']*citation[^\"']*[\"'][^>]*>\s*0{2,}\s*</sup>", raw, re.I))

    truncated = []
    reference_contamination = []
    table_fragments = []
    for i, text in enumerate(en_texts, 1):
        if is_explicitly_truncated(text):
            truncated.append(i)
        if re.match(r"^\d+\.\s+[A-Z]", text) and ("doi.org" in text or re.search(r"\b(?:Nature|Cell|Science|Commun\.|Springer|MICCAI)\b", text)):
            reference_contamination.append(i)
        if len(text) < 260 and len(re.findall(r"\bCD\d+\b|\bPD-L1\b|\bPD-1\b|\bKi-?67\b", text)) >= 3 and text.count(".") < 2:
            table_fragments.append(i)

    toc_fragments = []
    for anchor in soup.select(".toc a"):
        label = norm(anchor.get_text(" ", strip=True))
        match = re.match(r"^\d+\s*·\s*(.*?)\s+PDF\s+p\.\d+", label, re.I)
        if not match:
            continue
        fragment = match.group(1).strip()
        if not fragment or re.match(r"^[a-z]", fragment) or re.match(r"^\d+\s+", fragment) or len(re.sub(r"[^A-Za-z]", "", fragment)) < 3:
            toc_fragments.append(label)

    feature_presence = {name: token in raw for name, token in FEATURE_TOKENS.items()}
    baseline_required = {}
    missing_from_baseline = []
    if baseline:
        baseline_raw = baseline.read_text("utf-8")
        baseline_required = {name: token in baseline_raw for name, token in FEATURE_TOKENS.items()}
        missing_from_baseline = [name for name, required in baseline_required.items() if required and not feature_presence[name]]

    content_errors = []
    expected_min_units = max(18, int((pages or 15) * 1.1))
    if len(units) < expected_min_units:
        content_errors.append(f"too few bilingual units: {len(units)} < {expected_min_units}")
    if expected_body_blocks and pdf_block_coverage is not None and pdf_block_coverage < 0.45:
        content_errors.append(f"PDF-native body-block coverage too low: {pdf_block_coverage:.3f} < 0.45 ({len(units)}/{expected_body_blocks})")
    if appendix_words >= 1500 and coverage is not None and coverage < 0.45:
        content_errors.append(f"core English coverage too low: {coverage:.3f} < 0.45")
    if len(en_nodes) != len(zh_nodes):
        content_errors.append(f"English/Chinese block mismatch: {len(en_nodes)} != {len(zh_nodes)}")
    if malformed_nested_p:
        content_errors.append(f"malformed nested paragraphs: {malformed_nested_p}")
    if duplicated_overview:
        content_errors.append(f"duplicated overview-card nesting: {duplicated_overview}")
    if truncated:
        content_errors.append(f"explicitly truncated or page-split core paragraphs: {truncated}")
    if reference_contamination:
        content_errors.append(f"reference entries inserted into core reading: {reference_contamination}")
    if table_fragments:
        content_errors.append(f"table fragments inserted as prose: {table_fragments}")
    if toc_fragments:
        content_errors.append(f"garbled TOC labels: {toc_fragments[:8]}")
    if numeric_citation_corruption:
        content_errors.append(f"numeric values misclassified as citations: {numeric_citation_corruption}")

    structural_errors = []
    if baseline and missing_from_baseline:
        structural_errors.append("missing baseline features: " + ", ".join(missing_from_baseline))
    if not soup.select(".asset-card, .figure-card, .table-card"):
        structural_errors.append("no figure/table cards")
    if not soup.select("sup.citation, .citation"):
        structural_errors.append("no clickable citations")

    content_score = max(0, 100 - 10 * len(content_errors))
    structural_score = max(0, 100 - 10 * len(structural_errors))
    passed = not content_errors and not structural_errors
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "pages": pages,
        "bilingual_units": len(units),
        "english_blocks": len(en_nodes),
        "chinese_blocks": len(zh_nodes),
        "core_english_words": core_en_words,
        "core_chinese_chars": core_zh_chars,
        "appendix_words": appendix_words,
        "core_to_appendix_coverage": coverage,
        "expected_pdf_body_blocks": expected_body_blocks,
        "bilingual_to_pdf_body_block_ratio": pdf_block_coverage,
        "malformed_nested_p": malformed_nested_p,
        "duplicated_overview_cards": duplicated_overview,
        "truncated_units": truncated,
        "reference_contamination_units": reference_contamination,
        "table_fragment_units": table_fragments,
        "garbled_toc_labels": toc_fragments,
        "numeric_citation_corruption": numeric_citation_corruption,
        "features": feature_presence,
        "baseline_required_features": baseline_required,
        "missing_from_baseline": missing_from_baseline,
        "content_score": content_score,
        "structural_score": structural_score,
        "content_errors": content_errors,
        "structural_errors": structural_errors,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent reader-content coverage and baseline-parity validator")
    parser.add_argument("html", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--expected-body-blocks", type=int)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--diagnostic", action="store_true", help="write/report failures without a non-zero exit")
    args = parser.parse_args()
    report = analyze(args.html, args.baseline, args.expected_body_blocks)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"] and not args.diagnostic:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
