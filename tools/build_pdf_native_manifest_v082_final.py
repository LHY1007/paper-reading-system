#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_unpacked as base

PAGE_HEIGHTS: dict[int, float] = {}
FORMULA_TEXTS: set[str] = set()
METRICS = {
    "formula_blocks_detected": 0,
    "cross_column_body_merges": 0,
    "cross_column_caption_merges": 0,
}
ORIGINAL_CLASSIFY = base.classify
ORIGINAL_SHOULD_MERGE = base.should_merge
ORIGINAL_PAGE_READING_ORDER = base.page_reading_order
MATH_FONT_RE = re.compile(r"(?:math|symbol|stix|mt extra|cmsy|cmmi|cmex|euclid)", re.I)
MATH_OPERATOR_RE = re.compile(r"(?:=|≈|≃|≠|≤|≥|<|>|±|×|÷|∑|∫|√|→|←|↔|∝|∞|\^|_[A-Za-z0-9{])")
PANEL_ONLY_RE = re.compile(r"^(?:\(?[A-Za-z0-9]{1,2}\)?[.:]?|\d+(?:\.\d+)?%?)$")


def reset_metrics() -> None:
    FORMULA_TEXTS.clear()
    METRICS.update({
        "formula_blocks_detected": 0,
        "cross_column_body_merges": 0,
        "cross_column_caption_merges": 0,
    })


def is_formula_block(block: base.Block) -> bool:
    text = base.norm(block.text)
    if not text or len(text) > 420 or PANEL_ONLY_RE.fullmatch(text):
        return False
    if base.CAPTION_RE.match(text) or base.DOI_RE.search(text) or base.URL_RE.search(text):
        return False
    low = text.lower().strip(" :")
    if low in base.SECTION_EXACT or base.REFERENCE_HEADING_RE.fullmatch(low):
        return False
    math_font_chars = sum(len(span.text) for span in block.spans if MATH_FONT_RE.search(span.font))
    superscript_chars = sum(len(span.text) for span in block.spans if span.superscript)
    operators = len(MATH_OPERATOR_RE.findall(text))
    alnum = sum(ch.isalnum() for ch in text)
    math_symbols = sum(ch in "=≈≃≠≤≥<>±×÷∑∫√→←↔∝∞^_{}[]()" for ch in text)
    has_operand = bool(re.search(r"[A-Za-zΑ-Ωα-ω0-9]", text))
    if not has_operand:
        return False
    if operators >= 1 and alnum >= 2:
        return True
    if math_font_chars >= max(2, int(len(text) * 0.18)) and math_symbols >= 1:
        return True
    if superscript_chars >= 2 and math_symbols >= 1 and len(text) <= 220:
        return True
    return False


def strict_classify(block: base.Block, body_size: float, in_references: bool) -> str:
    kind = ORIGINAL_CLASSIFY(block, body_size, in_references)
    if not in_references and kind == "other" and is_formula_block(block):
        normalized = base.norm(block.text)
        if normalized not in FORMULA_TEXTS:
            FORMULA_TEXTS.add(normalized)
            METRICS["formula_blocks_detected"] += 1
        setattr(block, "is_formula", True)
        return "body"
    if kind == "body" and is_formula_block(block):
        normalized = base.norm(block.text)
        if normalized not in FORMULA_TEXTS:
            FORMULA_TEXTS.add(normalized)
            METRICS["formula_blocks_detected"] += 1
        setattr(block, "is_formula", True)
    return kind


def strict_should_merge(previous: base.Event, current: base.Event) -> bool:
    if getattr(previous.block, "is_formula", False) or getattr(current.block, "is_formula", False):
        return False
    if ORIGINAL_SHOULD_MERGE(previous, current):
        return True
    if previous.kind != "body" or current.kind != "body" or previous.section_id != current.section_id:
        return False
    if previous.page != current.page:
        return False
    if previous.block.column != "left" or current.block.column != "right":
        return False
    height = PAGE_HEIGHTS.get(previous.page, 792.0)
    near_left_bottom = previous.block.bbox[3] >= height * 0.62
    near_right_top = current.block.bbox[1] <= height * 0.38
    previous_open = bool(previous.text.endswith("-") or not base.TERMINAL_RE.search(previous.text))
    continuation_start = bool(re.match(r"^(?:[a-zα-ω]|\([a-z0-9]+\)|[,;:])", current.text.strip()))
    if near_left_bottom and near_right_top and previous_open and (continuation_start or previous.text.endswith("-")):
        METRICS["cross_column_body_merges"] += 1
        return True
    return False


def merge_caption_blocks(caption: base.Block, continuation: base.Block) -> None:
    left = caption.text.rstrip()
    right = continuation.text.lstrip()
    caption.text = base.norm(left[:-1] + right) if left.endswith("-") and re.match(r"^[a-z]", right) else base.norm(left + " " + right)
    caption.lines.extend(continuation.lines)
    caption.spans.extend(continuation.spans)
    caption.bbox = (
        min(caption.bbox[0], continuation.bbox[0]),
        min(caption.bbox[1], continuation.bbox[1]),
        max(caption.bbox[2], continuation.bbox[2]),
        max(caption.bbox[3], continuation.bbox[3]),
    )
    sizes = [span.size for span in caption.spans if 4 <= span.size <= 30]
    caption.median_size = statistics.median(sizes) if sizes else caption.median_size
    caption.max_size = max(sizes) if sizes else caption.max_size
    caption.source_sha256 = base.digest(caption.text)


def strict_page_reading_order(blocks: list[base.Block], rect: fitz.Rect) -> list[base.Block]:
    ordered = ORIGINAL_PAGE_READING_ORDER(blocks, rect)
    base.assign_columns(ordered, rect.width)
    removed: set[int] = set()
    for caption in ordered:
        if id(caption) in removed or caption.column != "left" or not base.CAPTION_RE.match(base.norm(caption.text)):
            continue
        if caption.bbox[3] < rect.height * 0.52:
            continue
        candidates = [
            block for block in ordered
            if id(block) not in removed
            and block is not caption
            and block.column == "right"
            and block.bbox[1] <= rect.height * 0.46
            and not base.CAPTION_RE.match(base.norm(block.text))
            and abs(block.median_size - caption.median_size) <= 0.8
            and len(base.norm(block.text)) >= 18
        ]
        if not candidates:
            continue
        continuation = min(candidates, key=lambda block: (block.bbox[1], block.bbox[0]))
        starts_like_continuation = bool(
            re.match(r"^(?:\([A-Za-z0-9]+\)|[a-zα-ω]|Abbreviations?\b|Data are\b|Scale bars?\b)", base.norm(continuation.text))
        )
        caption_is_open = not bool(re.search(r"[.!?][\"'’”\)\]]?$", base.norm(caption.text)))
        if not (starts_like_continuation or caption_is_open):
            continue
        merge_caption_blocks(caption, continuation)
        removed.add(id(continuation))
        METRICS["cross_column_caption_merges"] += 1
    return [block for block in ordered if id(block) not in removed]


def normalized_manifest_text(manifest: dict[str, Any]) -> str:
    fragments = []
    for section in manifest.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") == "paragraph":
                fragments.extend(block.get("source_fragments", []))
    return base.norm(" ".join(fragments))


def augment_audit(
    audit: dict[str, Any],
    manifest: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    manifest_text = normalized_manifest_text(manifest)
    missing_formulas = [text for text in sorted(FORMULA_TEXTS) if base.norm(text) not in manifest_text]
    paragraphs = sum(
        block.get("type") == "paragraph"
        for section in manifest.get("sections", [])
        for block in section.get("blocks", [])
    )
    source_chars = sum(
        len("".join(item.get("text", "") for item in block.get("english", [])))
        for section in manifest.get("sections", [])
        for block in section.get("blocks", [])
        if block.get("type") == "paragraph"
    )
    references = len(manifest.get("references", []))
    assets = len(manifest.get("assets", []))
    expected_references = int(source.get("expected_reference_count", 0) or 0)
    expected_assets = int(source.get("expected_main_figures", 0) or 0)
    errors = []
    pages = int(manifest.get("paper", {}).get("pages", 0) or 0)
    if missing_formulas:
        errors.append({"missing_formula_blocks": missing_formulas[:20]})
    if paragraphs < max(20, pages * 2):
        errors.append(f"too few natural paragraphs: {paragraphs} for {pages} pages")
    if source_chars < pages * 1200:
        errors.append(f"source text coverage too low: {source_chars} characters for {pages} pages")
    if expected_references and references < expected_references:
        errors.append(f"reference coverage incomplete: {references} < {expected_references}")
    if expected_assets and assets < expected_assets:
        errors.append(f"main figure coverage incomplete: {assets} < {expected_assets}")
    audit.update({
        "strict_layout_parser": "v082-final-2",
        "formula_blocks_detected": METRICS["formula_blocks_detected"],
        "formula_blocks_missing": len(missing_formulas),
        "formula_samples": sorted(FORMULA_TEXTS)[:20],
        "cross_column_body_merges": METRICS["cross_column_body_merges"],
        "cross_column_caption_merges": METRICS["cross_column_caption_merges"],
        "source_chars": source_chars,
        "expected_reference_count": expected_references,
        "expected_main_figures": expected_assets,
        "strict_errors": errors,
        "passed": bool(audit.get("passed")) and not errors,
    })
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a strict full PDF-native V0.8.2 CANVAS content manifest")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()

    reset_metrics()
    registry = json.loads(args.registry.read_text("utf-8"))
    source = next(item for item in registry["papers"] if item["key"] == args.key)
    with fitz.open(args.pdf) as document:
        PAGE_HEIGHTS.clear()
        PAGE_HEIGHTS.update({index + 1: float(page.rect.height) for index, page in enumerate(document)})

    base.classify = strict_classify
    base.should_merge = strict_should_merge
    base.page_reading_order = strict_page_reading_order

    temporary_audit = None
    if args.audit:
        temporary_audit = args.audit.with_suffix(args.audit.suffix + ".base")
    manifest = base.build_manifest(args.pdf, source, temporary_audit)
    audit = json.loads(temporary_audit.read_text("utf-8")) if temporary_audit and temporary_audit.exists() else {}
    if temporary_audit and temporary_audit.exists():
        temporary_audit.unlink()
    audit = augment_audit(audit, manifest, source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "key": args.key,
        "sections": len(manifest.get("sections", [])),
        "paragraphs": audit.get("paragraphs"),
        "assets": len(manifest.get("assets", [])),
        "references": len(manifest.get("references", [])),
        "formula_blocks": METRICS["formula_blocks_detected"],
        "cross_column_caption_merges": METRICS["cross_column_caption_merges"],
        "passed": audit.get("passed"),
        "errors": audit.get("strict_errors", []),
    }, ensure_ascii=False, indent=2))
    if not audit.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
