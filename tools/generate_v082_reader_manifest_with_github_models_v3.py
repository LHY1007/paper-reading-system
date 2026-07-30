#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

import generate_v082_reader_manifest_with_github_models_v2 as constrained

base = constrained.base
_original_generate_studies = base.generate_studies


def translate_records_with_repairs(
    records: list[dict[str, str]], *, token: str, model: str, cache_dir,
    cache_prefix: str, context: str,
) -> dict[str, str]:
    translations: dict[str, str] = {}
    source_by_id = {str(item["id"]): base.norm(item.get("text")) for item in records}
    system = f"""You are producing a publication-grade bilingual biomedical paper reader. Translate every English item into accurate, fluent Simplified Chinese. Preserve all numbers, gene/protein names, abbreviations, statistical symbols, comparison directions, citation numbers and uncertainty. Use consistent terminology across items. Do not summarize, omit, add interpretation, or output English as the translation. If an item is a formula, variable definition, code-like expression or statistical notation, preserve the expression and add a Chinese sentence stating what it defines or computes; every zh value must contain Chinese characters. Context: {context}\nReturn JSON only: {{\"items\":[{{\"id\":\"...\",\"zh\":\"...\"}}]}}. Include every input id exactly once."""
    repair_system = f"""Translate the supplied biomedical technical text into Simplified Chinese. The previous answer failed because it contained no Chinese. Preserve every formula, variable, number and symbol exactly, but add a precise Chinese explanation of what the expression or definition means. Do not omit content. Context: {context}. Return JSON only: {{\"items\":[{{\"id\":\"...\",\"zh\":\"...\"}}]}}."""
    for index, batch in enumerate(base.batches(records)):
        result = base.call_model_json(
            token=token, model=model, system=system,
            user_payload={"items": batch}, cache_dir=cache_dir,
            cache_name=f"{cache_prefix}-translate-{index:03d}",
        )
        items = result.get("items") if isinstance(result, dict) else result
        returned = {
            str(item.get("id")): base.norm(item.get("zh"))
            for item in items or [] if isinstance(item, dict)
        }
        expected = [str(item["id"]) for item in batch]
        repair_ids = [item_id for item_id in expected if item_id not in returned or not base.CJK.search(returned[item_id])]
        if repair_ids:
            repair_payload = {
                "items": [{"id": item_id, "text": source_by_id[item_id]} for item_id in repair_ids]
            }
            repaired = base.call_model_json(
                token=token, model=model, system=repair_system,
                user_payload=repair_payload, cache_dir=cache_dir,
                cache_name=f"{cache_prefix}-repair-{index:03d}", max_tokens=8000,
            )
            repaired_items = repaired.get("items") if isinstance(repaired, dict) else repaired
            for item in repaired_items or []:
                if isinstance(item, dict):
                    returned[str(item.get("id"))] = base.norm(item.get("zh"))
        missing = [item_id for item_id in expected if item_id not in returned]
        if missing:
            raise RuntimeError(f"translation response missing ids after repair: {missing[:20]}")
        for item_id in expected:
            value = returned[item_id]
            if not base.CJK.search(value):
                raise RuntimeError(f"translation for {item_id} still has no Chinese text after dedicated repair")
            translations[item_id] = value
    return translations


def _expected_panel_labels(figure: dict[str, Any]) -> list[str]:
    labels = [
        base.norm(panel.get("label")) or "整图"
        for panel in (figure.get("study") or {}).get("panels") or []
    ]
    return labels or ["整图"]


def _study_issues(study: dict[str, Any], expected_labels: list[str]) -> list[str]:
    issues: list[str] = []
    if not base.CJK.search(base.norm(study.get("intro"))) or len(base.norm(study.get("intro"))) < 40:
        issues.append("intro must contain at least 40 characters of substantive Chinese")
    if not base.CJK.search(base.norm(study.get("overview"))) or len(base.norm(study.get("overview"))) < 90:
        issues.append("overview must contain at least 90 characters of reader guidance in Chinese")
    panels = study.get("panels") or []
    labels = [base.norm(panel.get("label")) or "整图" for panel in panels if isinstance(panel, dict)]
    if labels != expected_labels:
        issues.append(f"panel labels must exactly match source order: {expected_labels}")
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            issues.append(f"panel {index} is not an object")
            continue
        title = base.norm(panel.get("title"))
        explanation = base.norm(panel.get("explanation"))
        if not base.CJK.search(title) or len(title) < 4:
            issues.append(f"panel {labels[index] if index < len(labels) else index} needs a specific Chinese title")
        if not base.CJK.search(explanation) or len(explanation) < 110:
            issues.append(f"panel {labels[index] if index < len(labels) else index} explanation must contain at least 110 characters of substantive Chinese")
    if not base.CJK.search(base.norm(study.get("conclusion"))) or len(base.norm(study.get("conclusion"))) < 60:
        issues.append("conclusion must contain at least 60 characters of Chinese synthesis")
    if not base.CJK.search(base.norm(study.get("boundary"))) or len(base.norm(study.get("boundary"))) < 35:
        issues.append("boundary must explicitly state the evidence boundary in Chinese")
    return issues


def _normalize_repaired_study(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "intro": base.norm(item.get("intro")),
        "overview": base.norm(item.get("overview")),
        "panels": [
            {
                "label": base.norm(panel.get("label")) or "整图",
                "title": base.norm(panel.get("title")) or "图中信息",
                "explanation": base.norm(panel.get("explanation")),
            }
            for panel in item.get("panels") or [] if isinstance(panel, dict)
        ],
        "conclusion": base.norm(item.get("conclusion")),
        "boundary": base.norm(item.get("boundary")),
    }


def generate_studies_with_repairs(
    figures: list[dict[str, Any]], plan: dict[str, Any], *, token: str, model: str,
    cache_dir, cache_prefix: str, paper_context: str,
) -> dict[str, dict[str, Any]]:
    output = _original_generate_studies(
        figures, plan, token=token, model=model, cache_dir=cache_dir,
        cache_prefix=cache_prefix, paper_context=paper_context,
    )
    plan_figures = {str(item.get("id")): item for item in plan.get("main_figures") or []}
    repair_system = f"""You are repairing one scientific figure explanation for a publication-grade bilingual biomedical paper reader. Paper context: {paper_context}. Use only the supplied English source title, full legend, panel evidence and reader-role plan. Return the complete figure explanation in Simplified Chinese. Preserve the exact supplied panel labels and order, with no missing or added panels. The intro must explain the figure's role in the paper and contain at least 50 Chinese characters. The overview must explain the reading order and visual encodings and contain at least 120 Chinese characters. Each panel requires a specific Chinese title and an explanation of at least 140 Chinese characters covering the object, axes or encoding when applicable, comparison, observed result and evidence boundary. The conclusion must contain at least 80 Chinese characters and connect this figure to the paper's next argument. The boundary must explicitly distinguish association, computational inference, model prediction, in-vitro evidence and clinical or causal proof as applicable. Do not invent values, directions, methods or panels. Return JSON only: {{\"id\":\"...\",\"intro\":\"...\",\"overview\":\"...\",\"panels\":[{{\"label\":\"A\",\"title\":\"...\",\"explanation\":\"...\"}}],\"conclusion\":\"...\",\"boundary\":\"...\"}}."""
    for figure in figures:
        figure_id = str(figure.get("id"))
        expected_labels = _expected_panel_labels(figure)
        issues = _study_issues(output[figure_id], expected_labels)
        if not issues:
            continue
        source_panels = [
            {
                "label": base.norm(panel.get("label")) or "整图",
                "source_text": base.norm(panel.get("source_text") or panel.get("explanation") or panel.get("title")),
            }
            for panel in (figure.get("study") or {}).get("panels") or []
        ] or [{"label": "整图", "source_text": base.norm(figure.get("caption_en"))}]
        payload = {
            "id": figure_id,
            "title_en": base.norm(figure.get("title_en")),
            "caption_en": base.norm(figure.get("caption_en")),
            "source_panels": source_panels,
            "expected_panel_labels": expected_labels,
            "reader_role": (plan_figures.get(figure_id) or {}).get("reader_role"),
            "panel_requirement": (plan_figures.get(figure_id) or {}).get("panel_requirement"),
            "previous_answer": output[figure_id],
            "validation_issues": issues,
        }
        repaired_study: dict[str, Any] | None = None
        last_issues = issues
        for attempt in range(2):
            payload["validation_issues"] = last_issues
            result = base.call_model_json(
                token=token, model=model, system=repair_system,
                user_payload=payload, cache_dir=cache_dir,
                cache_name=f"{cache_prefix}-study-repair-{figure_id}-{attempt + 1}",
                max_tokens=12000,
            )
            item = result.get("item") if isinstance(result, dict) and isinstance(result.get("item"), dict) else result
            if not isinstance(item, dict):
                last_issues = ["repair response is not a JSON object"]
                continue
            candidate = _normalize_repaired_study(item)
            last_issues = _study_issues(candidate, expected_labels)
            if not last_issues:
                repaired_study = candidate
                break
            payload["previous_answer"] = candidate
        if repaired_study is None:
            raise RuntimeError(f"figure {figure_id} remains below reader-quality thresholds after repair: {last_issues}")
        output[figure_id] = repaired_study
    return output


base.translate_records = translate_records_with_repairs
base.generate_studies = generate_studies_with_repairs


if __name__ == "__main__":
    base.main()
