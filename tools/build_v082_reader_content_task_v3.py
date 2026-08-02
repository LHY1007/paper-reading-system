#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

import build_v082_reader_content_task as base


ORIGINAL_BUILD = base.build


def build(
    raw: dict[str, Any],
    blueprint: dict[str, Any],
    paper_key: str,
    plan: dict[str, Any] | None,
    plan_path,
) -> dict[str, Any]:
    task = ORIGINAL_BUILD(raw, blueprint, paper_key, plan, plan_path)
    task["task_version"] = "v082-reader-content-task-3"
    task["source_outline"] = raw.get("evidence_outline") or []
    task["source_front_matter"] = raw.get("evidence_front_matter") or {}
    task["source_evidence_repairs"] = raw.get("evidence_repairs") or {}

    raw_assets = {str(asset.get("id")): asset for asset in raw.get("assets", [])}
    for module in task.get("module_tasks", []):
        if module.get("module") != "figures_and_tables":
            continue
        for evidence in module.get("evidence", []):
            raw_asset = raw_assets.get(str(evidence.get("id"))) or {}
            study = raw_asset.get("study") or {}
            evidence["detected_panels"] = [
                {
                    "label": panel.get("label"),
                    "source_title": panel.get("title"),
                    "source_text": panel.get("source_text") or panel.get("explanation"),
                }
                for panel in study.get("panels", [])
            ]
            evidence["source_caption"] = raw_asset.get("caption_en")
            evidence["source_title"] = raw_asset.get("title_en")
    task["completion_gates"].insert(
        0,
        "PDF outline, figure titles, caption boundaries and original reference numbering are present in the evidence task",
    )
    return task


base.build = build


if __name__ == "__main__":
    base.main()
