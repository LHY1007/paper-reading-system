#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def paragraph_record(section: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": block.get("id"),
        "section_id": section.get("id"),
        "section_title": section.get("title_en"),
        "source_pages": block.get("source_pages"),
        "text": norm("".join(item.get("text", "") for item in block.get("english", []))),
        "source_fragments": [norm(item) for item in block.get("source_fragments", []) if norm(item)],
    }


def all_sections(raw: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for section in raw.get("sections", []):
        blocks = [
            paragraph_record(section, block)
            for block in section.get("blocks", [])
            if block.get("type") == "paragraph"
        ]
        assets = [
            block.get("asset_id")
            for block in section.get("blocks", [])
            if block.get("type") == "asset" and block.get("asset_id")
        ]
        result.append(
            {
                "id": section.get("id"),
                "title_en": section.get("title_en"),
                "source_paragraphs": blocks,
                "asset_ids": assets,
            }
        )
    return result


def select_paragraphs(
    sections: list[dict[str, Any]], title_terms: tuple[str, ...], limit: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for section in sections:
        title = norm(section.get("title_en")).lower()
        if title_terms and not any(term in title for term in title_terms):
            continue
        for block in section.get("source_paragraphs", []):
            selected.append(block)
            if len(selected) >= limit:
                return selected
    return selected


def validate_plan(raw: dict[str, Any], plan: dict[str, Any], paper_key: str) -> list[str]:
    errors: list[str] = []
    paper = plan.get("paper") or {}
    raw_paper = raw.get("paper") or {}
    plan_key = norm(paper.get("key"))
    if plan_key and plan_key != paper_key:
        errors.append(f"plan paper key mismatch: {plan_key} != {paper_key}")
    raw_doi = norm(raw_paper.get("doi")).lower()
    plan_doi = norm(paper.get("doi")).lower()
    if raw_doi and plan_doi and raw_doi != plan_doi:
        errors.append(f"plan DOI mismatch: {plan_doi} != {raw_doi}")
    raw_title = norm(raw_paper.get("title_en")).lower()
    plan_title = norm(paper.get("title_en")).lower()
    if raw_title and plan_title and raw_title != plan_title:
        errors.append("plan title does not exactly match the source paper title")
    if not plan.get("overview"):
        errors.append("plan overview is missing")
    if not plan.get("body_section_map"):
        errors.append("plan body_section_map is missing")
    if not plan.get("main_figures"):
        errors.append("plan main_figures is missing")
    return errors


def build(
    raw: dict[str, Any],
    blueprint: dict[str, Any],
    paper_key: str,
    plan: dict[str, Any] | None,
    plan_path: Path | None,
) -> dict[str, Any]:
    sections = all_sections(raw)
    assets: list[dict[str, Any]] = []
    for asset in raw.get("assets", []):
        study = asset.get("study") or {}
        assets.append(
            {
                "id": asset.get("id"),
                "kind_detected": asset.get("kind"),
                "source_page": asset.get("source_page"),
                "source_title": asset.get("title_en"),
                "source_caption": asset.get("caption_en"),
                "image_src_present": bool(asset.get("image_src")),
                "detected_panels": [
                    {
                        "label": panel.get("label"),
                        "source_title": panel.get("title"),
                        "source_explanation": panel.get("explanation"),
                    }
                    for panel in study.get("panels", [])
                ],
                "required_output": {
                    "kind": "figure or table according to the source, not according to parser convenience",
                    "title_en": "complete source number and descriptive title",
                    "title_zh": "accurate scientific Chinese translation",
                    "intro": "one or two reader-facing sentences explaining the role of this asset in the paper",
                    "caption_en": "complete source legend with no adjacent body text or axis-label contamination",
                    "caption_zh": "complete contextual Chinese translation",
                    "study": {
                        "overview": "how to read the whole figure and how it connects to the paper argument",
                        "panels": "every labeled panel or logical block, explaining objects, axes, comparisons, results and evidence limits",
                        "conclusion": "the figure-level conclusion and the next logical step",
                    },
                },
            }
        )

    plan_errors = validate_plan(raw, plan, paper_key) if plan else []
    has_valid_plan = bool(plan) and not plan_errors
    references = [
        {
            "id": item.get("id"),
            "text": norm(item.get("text")),
            "url": item.get("url"),
        }
        for item in raw.get("references", [])
    ]

    module_tasks = [
        {
            "module": "paper_header",
            "reader_goal": "A reader can identify the paper, research team, publication status and disciplinary position before entering the body.",
            "paper_plan": (plan or {}).get("paper"),
            "evidence": select_paragraphs(sections, tuple(), 12),
        },
        {
            "module": "one_page_overview",
            "reader_goal": "A reader can understand the study question, cohorts, analytical transformation, biological finding, clinical result and limitations without reading the body.",
            "paper_plan": (plan or {}).get("overview"),
            "evidence": {
                "summary": select_paragraphs(sections, ("summary", "abstract"), 20),
                "results": select_paragraphs(sections, ("result",), 60),
                "discussion": select_paragraphs(sections, ("discussion", "limitation"), 40),
            },
        },
        {
            "module": "section_map",
            "reader_goal": "The table of contents follows the scientific argument rather than PDF layout fragments.",
            "paper_plan": (plan or {}).get("body_section_map"),
            "evidence": [
                {"id": section.get("id"), "title_en": section.get("title_en")}
                for section in sections
            ],
        },
        {
            "module": "bilingual_body",
            "reader_goal": "Every natural source paragraph has source-faithful English and complete contextual Chinese with stable terminology.",
            "paper_plan": {
                "preserve_source_order": True,
                "one_natural_paragraph_per_unit": True,
                "retain_citations_and_asset_links": True,
                "forbid_identity_translation": True,
                "forbid_running_headers_axis_labels_and_captions_in_body": True,
            },
            "evidence": sections,
        },
        {
            "module": "figures_and_tables",
            "reader_goal": "A reader can understand what each asset proves, inspect the complete source image or structured table and learn each panel rather than reread the caption.",
            "paper_plan": {
                "main_figures": (plan or {}).get("main_figures"),
                "supplementary_source_requirement": (plan or {}).get("supplementary_source_requirement"),
            },
            "evidence": assets,
        },
        {
            "module": "references",
            "reader_goal": "Every in-text citation resolves to the original numbered bibliographic item and missing numbers are explicit.",
            "paper_plan": (plan or {}).get("reference_requirement"),
            "evidence": references,
        },
    ]

    return {
        "task_version": "v082-reader-content-task-2",
        "paper_key": paper_key,
        "title": raw.get("paper", {}).get("title_en"),
        "doi": raw.get("paper", {}).get("doi"),
        "instruction": (
            "Produce a complete reader-ready paper content manifest. Do not emit HTML, CSS, layout, buttons or JavaScript. "
            "Do not copy parser diagnostics, page counts, arbitrary first/last sentences, Methods fragments or captions into reader synthesis fields."
        ),
        "blueprint_version": blueprint.get("version"),
        "blueprint_modules": blueprint.get("modules"),
        "paper_specific_plan_path": str(plan_path) if plan_path else None,
        "paper_specific_plan": plan,
        "plan_errors": plan_errors,
        "ready_for_content_generation": has_valid_plan,
        "ready_for_rendering": False,
        "module_tasks": module_tasks,
        "source_evidence_inventory": {
            "sections": len(sections),
            "paragraphs": sum(len(section.get("source_paragraphs", [])) for section in sections),
            "assets": len(assets),
            "references": len(references),
        },
        "required_output": f"content/v082_manifests/{paper_key}.json",
        "completion_gates": [
            "paper-specific plan exists and matches source DOI/title",
            "final manifest passes schemas/paper_content_manifest_v082.schema.json",
            "final manifest passes tools/validate_v082_reader_content_quality.py",
            "final manifest passes tools/validate_v082_final_manifest.py with source audit",
            "final manifest passes tools/validate_v082_manifest_code_boundary.py",
            "only then may tools/render_v082_from_frozen_shell.py create HTML",
            "rendered HTML must pass tools/audit_v082_reader_experience.py against the original CANVAS baseline",
        ],
        "forbidden_shortcuts": [
            "automatic translation of the evidence manifest treated as completed reader content",
            "identity translation",
            "placeholder authors or affiliations",
            "page count, parser block count or file hash described as scientific data",
            "generic figure titles such as Fig. or Figure 1. without descriptive title",
            "caption reused as figure overview, panel explanation or conclusion",
            "reference renumbering that hides missing source entries",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create paper-specific reader-content generation tasks from PDF evidence")
    parser.add_argument("raw_manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--blueprint", type=Path, default=Path("config/v082_reader_content_blueprint.json"))
    parser.add_argument("--paper-key")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plans-dir", type=Path, default=Path("config/v082_reader_content_plans"))
    parser.add_argument("--require-plan", action="store_true")
    args = parser.parse_args()

    raw = json.loads(args.raw_manifest.read_text("utf-8"))
    blueprint = json.loads(args.blueprint.read_text("utf-8"))
    inferred_key = norm(raw.get("paper", {}).get("key"))
    paper_key = norm(args.paper_key or inferred_key)
    if not paper_key:
        raise SystemExit("paper key is required")

    plan_path = args.plan
    if plan_path is None:
        candidate = args.plans_dir / f"{paper_key}.json"
        if candidate.exists():
            plan_path = candidate
    plan = json.loads(plan_path.read_text("utf-8")) if plan_path and plan_path.exists() else None

    task = build(raw, blueprint, paper_key, plan, plan_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {
                "paper_key": paper_key,
                "title": task["title"],
                "output": str(args.output),
                "plan": task["paper_specific_plan_path"],
                "plan_errors": task["plan_errors"],
                "ready_for_content_generation": task["ready_for_content_generation"],
                "ready_for_rendering": False,
                "inventory": task["source_evidence_inventory"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.require_plan and not task["ready_for_content_generation"]:
        raise SystemExit(f"paper-specific reader plan missing or invalid for {paper_key}")


if __name__ == "__main__":
    main()
