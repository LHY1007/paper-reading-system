#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def paragraph_count(manifest: dict[str, Any]) -> int:
    return sum(
        1
        for section in manifest.get("sections") or []
        for block in section.get("blocks") or []
        if block.get("type") == "paragraph"
    )


def validate(manifest: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    errors: list[Any] = []
    expected_paragraphs = paragraph_count(manifest)
    expected_figures = sum(1 for item in manifest.get("assets") or [] if item.get("kind") == "figure")
    translations = review.get("translation") or []
    figures = review.get("figures") or []
    tables = review.get("tables") or []

    if review.get("version") != "v082-strong-ai-component-review-1":
        errors.append("unexpected strong-AI review version")
    if review.get("paper_key") != (manifest.get("paper") or {}).get("key"):
        errors.append("review paper key differs from manifest")
    if not review.get("passed"):
        errors.append("strong-AI review did not pass")
    if len(translations) < expected_paragraphs:
        errors.append({
            "translation_reviews": {
                "minimum": expected_paragraphs,
                "actual": len(translations),
            }
        })
    if any(not item.get("passed") for item in translations):
        errors.append("one or more paragraph/title/caption/table-cell translation reviews failed")
    if len(figures) != expected_figures:
        errors.append({
            "figure_reviews": {
                "expected": expected_figures,
                "actual": len(figures),
            }
        })
    if any(not item.get("passed") for item in figures):
        errors.append("one or more multimodal figure reviews failed")
    if any(not item.get("source_image_present") for item in figures):
        errors.append("one or more figure reviews did not receive a source image")
    if any(not item.get("passed") for item in tables):
        errors.append("one or more table transcription reviews failed")
    if tables and any(not item.get("source_image_present") for item in tables):
        errors.append("one or more structured table transcriptions did not receive a source image")
    if not (review.get("overview") or {}).get("passed"):
        errors.append("overview independent review failed")
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
        "version": "v082-strong-ai-review-gate-1",
        "paper_key": (manifest.get("paper") or {}).get("key"),
        "paragraphs": expected_paragraphs,
        "figures": expected_figures,
        "reviewed_table_upgrades": len(tables),
        "terms": len(manifest.get("terms") or []),
        "references": len(manifest.get("references") or []),
        "models": review.get("models"),
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Require one-by-one strong-AI generation and independent review for every variable reader component")
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
