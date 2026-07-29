#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def paragraphs(manifest: dict[str, Any], title_terms: tuple[str, ...], limit: int = 8) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for section in manifest.get("sections", []):
        title = str(section.get("title_en", "")).lower()
        if title_terms and not any(term in title for term in title_terms):
            continue
        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue
            selected.append({
                "section": section.get("title_en"),
                "source_pages": block.get("source_pages"),
                "text": "".join(x.get("text", "") for x in block.get("english", [])),
            })
            if len(selected) >= limit:
                return selected
    return selected


def build(raw: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    assets = []
    for asset in raw.get("assets", []):
        assets.append({
            "id": asset.get("id"),
            "source_page": asset.get("source_page"),
            "source_title": asset.get("title_en"),
            "source_caption": asset.get("caption_en"),
            "detected_panels": [x.get("label") for x in (asset.get("study") or {}).get("panels", [])],
            "required_output": {
                "kind": "figure or table according to the source",
                "title_en": "complete source number and descriptive title",
                "title_zh": "scientific Chinese translation",
                "intro": "1-2 sentences explaining the role of this asset in the paper",
                "caption_zh": "complete caption translation",
                "study": "whole-figure reading guide, all panels or logical blocks, and figure-level conclusion"
            }
        })
    return {
        "task_version": "v082-reader-content-task-1",
        "paper_key": raw.get("paper", {}).get("key"),
        "title": raw.get("paper", {}).get("title_en"),
        "instruction": "Produce reader-ready scientific content only. Do not emit HTML, CSS, layout, buttons or JavaScript. Do not copy parser diagnostics into reader-facing fields.",
        "blueprint_version": blueprint.get("version"),
        "modules": blueprint.get("modules"),
        "source_evidence": {
            "front_matter": paragraphs(raw, tuple(), 6),
            "abstract_or_summary": paragraphs(raw, ("abstract", "summary"), 10),
            "results": paragraphs(raw, ("results",), 30),
            "discussion_and_limits": paragraphs(raw, ("discussion", "limitation"), 20),
            "methods": paragraphs(raw, ("method",), 20),
            "assets": assets,
            "reference_count": len(raw.get("references", []))
        },
        "required_outputs": [
            "complete paper header metadata",
            "six-question Chinese overview, arrow workflow and overall conclusion",
            "clean bilingual section map",
            "paragraph-by-paragraph Chinese translation",
            "reader-facing figure/table cards and panel explanations",
            "contextual term glossary",
            "complete numbered references"
        ],
        "completion_rule": "The resulting manifest must pass validate_v082_reader_content_quality.py before rendering."
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create explicit reader-content generation tasks from raw PDF evidence")
    parser.add_argument("raw_manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--blueprint", type=Path, default=Path("config/v082_reader_content_blueprint.json"))
    args = parser.parse_args()
    raw = json.loads(args.raw_manifest.read_text("utf-8"))
    blueprint = json.loads(args.blueprint.read_text("utf-8"))
    task = build(raw, blueprint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"paper": task["title"], "output": str(args.output), "assets": len(task["source_evidence"]["assets"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
