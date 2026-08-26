#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

import build_v082_reader_content_task_v3 as v3
from v083_reader_profile import classify, load_config


base = v3.base
ORIGINAL_BUILD = v3.build


def build(
    raw: dict[str, Any],
    blueprint: dict[str, Any],
    paper_key: str,
    plan: dict[str, Any] | None,
    plan_path,
) -> dict[str, Any]:
    task = ORIGINAL_BUILD(raw, blueprint, paper_key, plan, plan_path)
    profile = classify(raw, plan=plan, config=load_config())
    task["task_version"] = "v083-reader-content-task-4"
    task["reader_profile"] = profile

    for module in task.get("module_tasks", []):
        if module.get("module") == "bilingual_body":
            module["reader_goal"] = (
                "Every source sentence remains exactly the source English sentence and is paired with a pure Chinese translation. "
                "The bilingual body is not a summary layer and must never paraphrase, explain, infer or strengthen the source."
            )
            module["paper_plan"] = {
                "source_fidelity": "English visible text must reconstruct the PDF source text exactly after removing only structural citation markup; no AI-authored English is permitted.",
                "translation": "Chinese is translation only. Do not summarize, explain, infer, add background knowledge, rewrite conclusions or omit qualifiers.",
                "sentence_pairing": "one English scientific sentence to one Chinese translation sentence",
                "terminology": "retain the V0.8.3 terminology system in both English and Chinese. Mark source terms with term_id and reuse one stable definition across the paper.",
                "citations": "keep every citation at its original source position; every citation node must resolve to referenceData and a clickable external reference URL",
                "asset_links": "keep every Figure/Table/Extended Data/Supplementary mention at its original source position and link it to the corresponding asset",
                "forbidden": [
                    "AI-authored English summary inserted into the bilingual body",
                    "Chinese interpretation mixed into translation",
                    "citations moved to paragraph or sentence ends",
                    "figure/table mentions moved to paragraph or sentence ends",
                    "plain unclickable terminology where the term dictionary contains a matching alias"
                ]
            }
        elif module.get("module") == "figures_and_tables":
            if profile["figure_study_enabled"]:
                module["reader_goal"] = (
                    "Preserve the standard V0.8.3 asset preview/right-viewer/caption modules and additionally create source-grounded figure study because this paper is figure-intensive."
                )
                module["paper_plan"] = dict(module.get("paper_plan") or {})
                module["paper_plan"]["figure_study"] = {
                    "enabled": True,
                    "scope": "CNS-family or biology/bioinformatics-heavy paper",
                    "requirement": "inventory every labeled panel and meaningful logical block before explanation"
                }
            else:
                module["reader_goal"] = (
                    "Preserve the original V0.8.3 figure/table preview, right-side viewer and bilingual captions. "
                    "Do not create the full-screen figure-study layer for this conventional low-reading-difficulty paper."
                )
                module["paper_plan"] = dict(module.get("paper_plan") or {})
                module["paper_plan"]["figure_study"] = {
                    "enabled": False,
                    "scope": "conventional method/engineering/clinical paper",
                    "requirement": "preview + right viewer + bilingual caption only"
                }
                for evidence in module.get("evidence", []):
                    required = evidence.get("required_output") or {}
                    required.pop("study", None)
                    evidence["required_output"] = required
        elif module.get("module") == "references":
            module["reader_goal"] = (
                "Every in-text citation resolves at its original position to the correct numbered bibliographic entry; cited references expose an external DOI/publisher/arXiv URL in the popup."
            )

    task["completion_gates"].extend([
        "tools/finalize_v083_manifest.py has applied the reader profile, exact-position bracket citations, figure/table links, terminology markup and deterministic reference URLs without rewriting text",
        "tools/validate_v083_manifest_contract.py passes source fidelity, terminology, citation-link, asset-link and conditional figure-study gates",
    ])
    task["forbidden_shortcuts"].extend([
        "using figure-study for every paper regardless of figure complexity or paper type",
        "removing terminology markup from source-faithful bilingual text",
        "keeping citation numbers as plain text without popup/link behavior",
        "rewriting English source text in order to make translation or markup easier",
    ])
    return task


base.build = build


if __name__ == "__main__":
    base.main()
