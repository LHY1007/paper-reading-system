#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


TABLE_PROVENANCE = "ai-verified-structured-table-transcription-v1"
TEXTUAL_CELL = re.compile(r"[A-Za-z]")
NUMERIC_CELL = re.compile(r"^[\d\s.,±%()/<>=−–—+\-]+$")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def paragraph_count(manifest: dict[str, Any]) -> int:
    return sum(
        1
        for section in manifest.get("sections") or []
        for block in section.get("blocks") or []
        if block.get("type") == "paragraph"
    )


def ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id") or "") for item in items]


def is_reviewed_table_upgrade(asset: dict[str, Any]) -> bool:
    return (
        asset.get("kind") == "table"
        and TABLE_PROVENANCE in str(asset.get("source_render") or "")
    )


def expected_paragraph_review_ids(manifest: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for section in manifest.get("sections") or []:
        section_id = str(section.get("id") or "")
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            output.append(f"paragraph/{section_id}/{block.get('id')}")
    return output


def expected_caption_review_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        f"asset-caption/{asset.get('id')}"
        for asset in manifest.get("assets") or []
        if str(asset.get("caption_en") or "").strip()
    ]


def english_cell(value: Any) -> str:
    text = str(value or "").strip()
    return text.split("（", 1)[0].strip()


def cell_requires_translation(value: Any) -> bool:
    text = english_cell(value)
    return bool(text and TEXTUAL_CELL.search(text) and not NUMERIC_CELL.fullmatch(text))


def expected_table_cell_review_ids(manifest: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for asset in manifest.get("assets") or []:
        if not is_reviewed_table_upgrade(asset):
            continue
        asset_id = str(asset.get("id") or "")
        table = asset.get("table") or {}
        for index, value in enumerate(table.get("headers") or []):
            if cell_requires_translation(value):
                output.append(f"table/{asset_id}/h/{index}")
        for row_index, row in enumerate(table.get("rows") or []):
            for column_index, value in enumerate(row):
                if cell_requires_translation(value):
                    output.append(f"table/{asset_id}/r/{row_index}/{column_index}")
    return output


def missing_or_duplicate(actual: list[str], expected: list[str]) -> dict[str, Any] | None:
    counts = Counter(actual)
    missing = [item for item in expected if counts[item] == 0]
    duplicate = sorted(item for item, count in counts.items() if count > 1)
    if not missing and not duplicate:
        return None
    return {"missing": missing, "duplicate": duplicate}


def model_is_gpt54(value: Any) -> bool:
    return str(value or "").strip().lower().endswith("gpt-5.4")


def validate(manifest: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    errors: list[Any] = []
    expected_paragraphs = paragraph_count(manifest)
    assets = manifest.get("assets") or []
    expected_figure_ids = [
        str(item.get("id")) for item in assets if item.get("kind") == "figure"
    ]
    expected_table_upgrade_ids = [
        str(item.get("id")) for item in assets if is_reviewed_table_upgrade(item)
    ]
    expected_source_image_ids = [
        str(item.get("id"))
        for item in assets
        if item.get("kind") == "figure" or is_reviewed_table_upgrade(item)
    ]

    translations = review.get("translation") or []
    figures = review.get("figures") or []
    tables = review.get("tables") or []
    translation_ids = ids(translations)
    reviewed_figure_ids = ids(figures)
    reviewed_table_ids = ids(tables)

    paragraph_ids = expected_paragraph_review_ids(manifest)
    caption_ids = expected_caption_review_ids(manifest)
    table_cell_ids = expected_table_cell_review_ids(manifest)
    required_translation_ids = paragraph_ids + caption_ids + table_cell_ids

    if review.get("version") != "v082-strong-ai-component-review-1":
        errors.append("unexpected strong-AI review version")
    if review.get("paper_key") != (manifest.get("paper") or {}).get("key"):
        errors.append("review paper key differs from manifest")
    if not review.get("passed"):
        errors.append("strong-AI review did not pass")
    if not review.get("independent_reviewer_acceptance_passed"):
        errors.append("independent reviewer acceptance did not pass")

    models = review.get("models") or {}
    for role in ("primary", "reviewer", "vision"):
        if not model_is_gpt54(models.get(role)):
            errors.append({"model": role, "expected": "gpt-5.4", "actual": models.get(role)})

    if len(translations) < expected_paragraphs:
        errors.append({
            "translation_reviews": {
                "minimum_paragraph_reviews": expected_paragraphs,
                "actual_all_translation_reviews": len(translations),
            }
        })
    coverage = missing_or_duplicate(translation_ids, required_translation_ids)
    if coverage:
        errors.append({"translation_review_id_coverage": coverage})
    if any(not item.get("passed") for item in translations):
        errors.append("one or more paragraph/title/caption/table-cell translation reviews failed")
    if any(item.get("independent_reviewer_accepted") is not True for item in translations):
        errors.append("one or more translations lack explicit independent reviewer acceptance")

    if reviewed_figure_ids != expected_source_image_ids:
        errors.append({
            "source_image_review_ids": {
                "expected": expected_source_image_ids,
                "actual": reviewed_figure_ids,
            }
        })
    if reviewed_table_ids != expected_table_upgrade_ids:
        errors.append({
            "table_review_ids": {
                "expected": expected_table_upgrade_ids,
                "actual": reviewed_table_ids,
            }
        })
    if len(reviewed_figure_ids) != len(set(reviewed_figure_ids)):
        errors.append("duplicate source-image review IDs")
    if len(reviewed_table_ids) != len(set(reviewed_table_ids)):
        errors.append("duplicate table transcription review IDs")
    if any(not item.get("passed") for item in figures):
        errors.append("one or more multimodal source-image reviews failed")
    if any(item.get("independent_reviewer_accepted") is not True for item in figures):
        errors.append("one or more figure reviews lack explicit independent reviewer acceptance")
    if any(not item.get("source_image_present") for item in figures):
        errors.append("one or more source-image reviews did not receive the image")
    if any(not item.get("passed") for item in tables):
        errors.append("one or more table transcription reviews failed")
    if any(item.get("independent_reviewer_accepted") is not True for item in tables):
        errors.append("one or more table reviews lack explicit independent reviewer acceptance")
    if tables and any(not item.get("source_image_present") for item in tables):
        errors.append("one or more structured table transcriptions did not receive a source image")

    overview = review.get("overview") or {}
    if not overview.get("passed"):
        errors.append("overview independent review failed")
    if overview.get("independent_reviewer_accepted") is not True:
        errors.append("overview lacks explicit independent reviewer acceptance")
    if not (review.get("terms") or {}).get("passed"):
        errors.append("term extraction review failed")
    if int((review.get("terms") or {}).get("accepted_count") or 0) != len(manifest.get("terms") or []):
        errors.append("reviewed term count differs from manifest")
    references = review.get("references") or {}
    if not references.get("passed"):
        errors.append("reference-link resolution gate failed")
    if int(references.get("total") or 0) != len(manifest.get("references") or []):
        errors.append("reference review count differs from manifest")

    return {
        "version": "v082-strong-ai-review-gate-5",
        "paper_key": (manifest.get("paper") or {}).get("key"),
        "paragraphs": expected_paragraphs,
        "required_paragraph_review_ids": len(paragraph_ids),
        "required_caption_review_ids": len(caption_ids),
        "required_table_cell_review_ids": len(table_cell_ids),
        "actual_translation_review_ids": len(translation_ids),
        "figure_ids": expected_figure_ids,
        "table_upgrade_ids": expected_table_upgrade_ids,
        "expected_source_image_ids": expected_source_image_ids,
        "reviewed_source_image_ids": reviewed_figure_ids,
        "reviewed_table_ids": reviewed_table_ids,
        "terms": len(manifest.get("terms") or []),
        "references": len(manifest.get("references") or []),
        "models": models,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Require one-by-one GPT-5.4 generation and explicit independent review for every variable reader component"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(load(args.manifest), load(args.review))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
