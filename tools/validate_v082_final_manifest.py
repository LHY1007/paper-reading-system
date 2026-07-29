#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from validate_v082_reader_content_quality import validate as validate_reader_content

CJK_RE = re.compile(r"[\u3400-\u9fff]")
HTML_TAG_RE = re.compile(r"<\/?(?:p|div|span|script|style|html|body)\b", re.I)
PARSER_VERSION_RE = re.compile(r"^v082-final-(?:[2-9]|[1-9]\d+)$")


def plain(items: list[dict]) -> str:
    return "".join(str(item.get("text", "")) for item in items)


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def validate(manifest: dict, schema: dict, audit: dict | None) -> dict:
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(manifest)]
    paragraphs = [
        block
        for section in manifest.get("sections", [])
        for block in section.get("blocks", [])
        if block.get("type") == "paragraph"
    ]
    assets = manifest.get("assets", [])
    references = manifest.get("references", [])
    pages = int(manifest.get("paper", {}).get("pages", 0) or 0)
    source_chars = sum(len(plain(block.get("english", []))) for block in paragraphs)
    translated_chars = sum(len(plain(block.get("chinese", []))) for block in paragraphs)
    cjk_chars = sum(len(CJK_RE.findall(plain(block.get("chinese", [])))) for block in paragraphs)
    cjk_ratio = cjk_chars / max(1, translated_chars)

    if len(paragraphs) < max(20, pages * 2):
        errors.append(f"too few paragraph blocks: {len(paragraphs)} for {pages} pages")
    if source_chars < pages * 1200:
        errors.append(f"source text coverage too low: {source_chars} characters for {pages} pages")
    if not assets:
        errors.append("no figure/table assets")
    if cjk_ratio < 0.18:
        errors.append(f"Chinese translation ratio too low: {cjk_ratio:.3f}")

    empty_paragraphs = []
    source_mismatches = []
    untranslated_long_blocks = []
    html_leaks = []
    for block in paragraphs:
        block_id = block.get("id", "unknown")
        english = normalized(plain(block.get("english", [])))
        chinese = normalized(plain(block.get("chinese", [])))
        fragments = normalized(" ".join(block.get("source_fragments", [])))
        if not english or not chinese or not fragments:
            empty_paragraphs.append(block_id)
        if english != fragments:
            source_mismatches.append(block_id)
        if len(english) >= 120 and english == chinese:
            untranslated_long_blocks.append(block_id)
        if HTML_TAG_RE.search(english) or HTML_TAG_RE.search(chinese):
            html_leaks.append(block_id)
    if empty_paragraphs:
        errors.append({"empty_paragraphs": empty_paragraphs[:30]})
    if source_mismatches:
        errors.append({"source_fragment_mismatches": source_mismatches[:30]})
    if untranslated_long_blocks:
        errors.append({"untranslated_long_blocks": untranslated_long_blocks[:30]})
    if html_leaks:
        errors.append({"html_markup_leaks": html_leaks[:30]})

    if any(not asset.get("image_src", "").startswith("data:image/") for asset in assets if asset.get("kind") == "figure"):
        errors.append("figure asset without embedded source image")
    if len({asset.get("id") for asset in assets}) != len(assets):
        errors.append("duplicate asset IDs")
    asset_refs = [
        block.get("asset_id")
        for section in manifest.get("sections", [])
        for block in section.get("blocks", [])
        if block.get("type") == "asset"
    ]
    if len(asset_refs) != len(set(asset_refs)):
        errors.append("duplicate asset card placement")
    if set(asset_refs) != {asset.get("id") for asset in assets}:
        errors.append("asset inventory and section placement differ")

    reference_ids = [str(item.get("id", "")) for item in references]
    expected_reference_ids = [str(index) for index in range(1, len(references) + 1)]
    if reference_ids != expected_reference_ids:
        errors.append("reference IDs are not a continuous 1-based sequence")
    if len(reference_ids) != len(set(reference_ids)):
        errors.append("duplicate reference IDs")

    caption_zh_chars = sum(len(CJK_RE.findall(str(asset.get("caption_zh", "")))) for asset in assets)
    caption_total_chars = sum(len(str(asset.get("caption_zh", ""))) for asset in assets)
    caption_cjk_ratio = caption_zh_chars / max(1, caption_total_chars)
    if assets and caption_cjk_ratio < 0.12:
        errors.append(f"Chinese caption coverage too low: {caption_cjk_ratio:.3f}")

    if audit is None:
        errors.append("missing independent PDF-native audit")
    else:
        parser_version = str(audit.get("strict_layout_parser", ""))
        if not PARSER_VERSION_RE.fullmatch(parser_version):
            errors.append(f"strict layout parser audit missing or obsolete: {parser_version or 'none'}")
        if not audit.get("passed"):
            errors.append("PDF-native extraction audit failed")
        if int(audit.get("paragraphs", -1)) != len(paragraphs):
            errors.append(f"audit/manifest paragraph mismatch: {audit.get('paragraphs')} != {len(paragraphs)}")
        if int(audit.get("assets", -1)) != len(assets):
            errors.append(f"audit/manifest asset mismatch: {audit.get('assets')} != {len(assets)}")
        if int(audit.get("formula_blocks_missing", -1)) != 0:
            errors.append(f"standalone formula retention failed: {audit.get('formula_blocks_missing')}")
        expected_refs = int(audit.get("expected_reference_count", 0) or 0)
        if expected_refs and len(references) != expected_refs:
            errors.append(f"reference count mismatch: {len(references)} != {expected_refs}")
        audited_source_chars = int(audit.get("source_chars", -1))
        if audited_source_chars != source_chars:
            errors.append(f"audit/manifest source character mismatch: {audited_source_chars} != {source_chars}")
        if audit.get("strict_errors"):
            errors.append({"strict_extraction_errors": audit.get("strict_errors")})

    reader_quality = validate_reader_content(manifest)
    if not reader_quality.get("passed"):
        errors.append({
            "reader_content_gate": "failed",
            "error_count": reader_quality.get("error_count"),
            "sample_errors": reader_quality.get("errors", [])[:100],
        })

    return {
        "paper_key": manifest.get("paper", {}).get("key"),
        "pages": pages,
        "sections": len(manifest.get("sections", [])),
        "paragraphs": len(paragraphs),
        "assets": len(assets),
        "references": len(references),
        "source_chars": source_chars,
        "translated_chars": translated_chars,
        "cjk_ratio": round(cjk_ratio, 4),
        "caption_cjk_ratio": round(caption_cjk_ratio, 4),
        "formula_blocks_detected": audit.get("formula_blocks_detected") if audit else None,
        "cross_column_body_merges": audit.get("cross_column_body_merges") if audit else None,
        "cross_column_caption_merges": audit.get("cross_column_caption_merges") if audit else None,
        "reader_content_quality": reader_quality,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Strict content validation for final V0.8.2 manifests")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text("utf-8"))
    schema = json.loads(args.schema.read_text("utf-8"))
    audit = json.loads(args.audit.read_text("utf-8")) if args.audit else None
    report = validate(manifest, schema, audit)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
