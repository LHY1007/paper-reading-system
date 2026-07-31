#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

import generate_v082_reader_manifest_with_copilot_sdk_v14 as v14


v13 = v14.v13
_ORIGINAL_FIGURE_PAYLOAD = v13.figure_payload
_ORIGINAL_STUDY_ISSUES = v13.study_issues
_CURRENT_PAYLOAD: dict[str, Any] = {}

NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?")
BIOMEDICAL_TOKEN = re.compile(
    r"\b(?:"
    r"[A-Z]{2,}[A-Z0-9./+-]*|"
    r"[A-Za-z]*\d+[A-Za-z0-9./+-]*|"
    r"[A-Z][a-z]+[A-Z][A-Za-z0-9-]*|"
    r"[A-Za-z]+-[A-Za-z0-9-]+"
    r")\b"
)
GENERIC_PANEL_TITLE = re.compile(
    r"^(?:子图\s*[A-Z0-9]+\s*的)?(?:比较与结果|图中信息|结果展示|数据分析)$"
)
DIRECT_RESULT = re.compile(
    r"显示|表明|观察到|高于|低于|增加|减少|升高|降低|富集|缺失|相关|一致|"
    r"区分|预测|分类|表达|分布|定位|性能|差异|关联|检出|验证"
)


def norm(value: Any) -> str:
    return v13.norm(value)


def traceable_anchors(text: str) -> list[str]:
    value = norm(text)
    anchors: list[str] = []
    for token in NUMBER.findall(value) + BIOMEDICAL_TOKEN.findall(value):
        token = token.strip(".,;:()[]{}")
        if len(token) < 2 or token in {"Fig", "Figure", "Table", "Extended", "Data"}:
            continue
        if token not in anchors:
            anchors.append(token)
    return anchors


def figure_payload_with_trace(
    figure: dict[str, Any],
    evidence: dict[str, Any],
    plan: dict[str, Any],
    translations: dict[str, str],
) -> dict[str, Any]:
    payload = _ORIGINAL_FIGURE_PAYLOAD(figure, evidence, plan, translations)
    global _CURRENT_PAYLOAD
    _CURRENT_PAYLOAD = payload
    return payload


def study_issues_grounded(study: dict[str, Any], labels: list[str]) -> list[str]:
    issues = list(_ORIGINAL_STUDY_ISSUES(study, labels))
    payload = _CURRENT_PAYLOAD
    source_panels = payload.get("source_panels") or []
    nearby = " ".join(payload.get("nearby_body_evidence") or [])
    caption = norm(payload.get("caption_en"))

    for index, panel in enumerate(study.get("panels") or []):
        label = norm(panel.get("label")) or "整图"
        title = norm(panel.get("title"))
        explanation = norm(panel.get("explanation"))
        source_text = ""
        if index < len(source_panels):
            source_text = norm(source_panels[index].get("source_text"))
        anchors = traceable_anchors(" ".join([source_text, caption, nearby]))
        matched = [anchor for anchor in anchors if anchor.lower() in explanation.lower()]
        if anchors and not matched:
            issues.append(
                f"panel {label} lacks a source-traceable identifier or value; "
                f"use at least one of: {', '.join(anchors[:12])}"
            )
        if GENERIC_PANEL_TITLE.match(title):
            issues.append(f"panel {label} title is generic rather than panel-specific")
        if explanation and not DIRECT_RESULT.search(explanation):
            issues.append(
                f"panel {label} explanation does not state a direct observed, measured, inferred or predicted result"
            )
    return list(dict.fromkeys(issues))


v13.figure_payload = figure_payload_with_trace
v13.study_issues = study_issues_grounded


if __name__ == "__main__":
    v13.main()
