#!/usr/bin/env python3
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_copilot_sdk_v15 as v15


v13 = v15.v13
_ORIGINAL_GENERATE = v13.generate_figure_studies_strong


def norm(value: Any) -> str:
    return v13.norm(value)


def parser_labels(figure: dict[str, Any]) -> list[str]:
    labels = [
        norm(item.get("label")) or "整图"
        for item in (figure.get("study") or {}).get("panels") or []
        if isinstance(item, dict)
    ]
    return labels or ["整图"]


def normalize_label(value: Any) -> str:
    label = norm(value)
    label = re.sub(r"^(?:panel|subpanel|子图)\s*", "", label, flags=re.I)
    label = label.strip("()[]{}:：,，.。 ")
    if not label or label.lower() in {"whole", "whole figure", "unlabelled", "unlabeled", "整图"}:
        return "整图"
    if re.fullmatch(r"[a-z]", label):
        return label.upper()
    return label


def normalize_labels(values: Any) -> list[str]:
    output: list[str] = []
    for value in values or []:
        label = normalize_label(value)
        if label not in output:
            output.append(label)
    if not output:
        return ["整图"]
    if len(output) > 1 and "整图" in output:
        output = [value for value in output if value != "整图"]
    return output[:40]


def caption_segments(caption: str, labels: list[str]) -> dict[str, str]:
    text = norm(caption)
    if labels == ["整图"] or not text:
        return {"整图": text}
    positions: list[tuple[int, str]] = []
    for label in labels:
        escaped = re.escape(label)
        patterns = [
            rf"\({escaped}\)",
            rf"\[{escaped}\]",
            rf"(?<![A-Za-z0-9]){escaped}[\.,:;](?![A-Za-z0-9])",
        ]
        found: list[int] = []
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                found.append(match.start())
        if found:
            positions.append((min(found), label))
    positions.sort()
    if not positions:
        return {label: text for label in labels}
    output: dict[str, str] = {}
    for index, (start, label) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        output[label] = text[start:end].strip()
    for label in labels:
        output.setdefault(label, text)
    return output


def inventory_one(
    figure: dict[str, Any],
    *,
    paper_title: str,
    token: str,
    primary_model: str,
    reviewer_model: str,
    cache_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    figure_id = str(figure.get("id"))
    image_src = norm(figure.get("image_src"))
    parsed = parser_labels(figure)
    if not image_src:
        return figure, {
            "id": figure_id,
            "parser_labels": parsed,
            "visual_labels": parsed,
            "source_image_present": False,
            "passed": parsed != ["整图"] or bool(norm(figure.get("caption_en"))),
            "reason": "source image unavailable; parser inventory retained",
        }

    payload = {
        "id": figure_id,
        "title_en": norm(figure.get("title_en")),
        "caption_en": norm(figure.get("caption_en")),
        "parser_panel_labels": parsed,
    }
    detect_system = f"""你是生物医学论文图像结构标注员。论文题目：{paper_title}。
只完成面板清点，不解释科学结论。直接查看原始图像，按阅读顺序列出所有明确可见的子图标签，例如A、B、C或a、b、c。不得根据图注推测图像中没有显示的标签，也不得把坐标轴刻度、分组名称或图例项目当成面板标签。
若图像确实是一个没有面板标签的单一逻辑块，只返回整图。若图像包含多个未标字母但视觉上独立的逻辑块，使用逻辑块1、逻辑块2等名称。
返回严格JSON：{{"id":"...","labels":["A","B"],"notes":"简述识别依据"}}。"""
    draft = v13.call_multimodal_json(
        token=token,
        model=primary_model,
        system=detect_system,
        payload=payload,
        image_src=image_src,
        cache_dir=cache_dir,
        cache_name=f"panel-inventory-draft-{figure_id}",
        max_tokens=8000,
    )
    review_system = f"""你是第二位独立的论文图像面板审校者。论文题目：{paper_title}。
重新查看原始图像，核对候选面板清单是否漏掉、重复或误把坐标轴/图例当作面板。解析器标签只作参考，不得盲从。最终标签必须与图像中实际可见结构一致并按阅读顺序排列。
若解析器已识别多个明确面板，最终结果不得无证据地删掉这些面板；存在冲突时在issues中说明。
返回严格JSON：{{"passed":true,"issues":[],"final":{{"id":"...","labels":["A","B"],"notes":"..."}}}}。"""
    reviewed = v13.call_multimodal_json(
        token=token,
        model=reviewer_model,
        system=review_system,
        payload={"source": payload, "candidate": draft},
        image_src=image_src,
        cache_dir=cache_dir,
        cache_name=f"panel-inventory-review-{figure_id}",
        max_tokens=8000,
    )
    final = (reviewed or {}).get("final") or {}
    visual = normalize_labels(final.get("labels"))
    review_issues = [norm(value) for value in (reviewed or {}).get("issues", []) if norm(value)]

    parser_explicit = [label for label in parsed if label != "整图"]
    missing_parser_labels = [label for label in parser_explicit if label not in visual]
    if missing_parser_labels:
        repair_system = review_system + "\n必须重新核对required_fixes；除非原图明确证明解析器标签错误，否则不得删除已识别面板。"
        repaired = v13.call_multimodal_json(
            token=token,
            model=reviewer_model,
            system=repair_system,
            payload={
                "source": payload,
                "candidate": final,
                "required_fixes": [
                    "visual inventory omitted parser-supported labels: "
                    + ", ".join(missing_parser_labels)
                ],
            },
            image_src=image_src,
            cache_dir=cache_dir,
            cache_name=f"panel-inventory-repair-{figure_id}",
            max_tokens=8000,
        )
        final = (repaired or {}).get("final") or repaired
        visual = normalize_labels(final.get("labels"))
        missing_parser_labels = [label for label in parser_explicit if label not in visual]

    if missing_parser_labels:
        raise RuntimeError(
            f"panel inventory for {figure_id} omitted parser-supported labels: {missing_parser_labels}"
        )
    if not visual:
        raise RuntimeError(f"panel inventory for {figure_id} is empty")

    updated = copy.deepcopy(figure)
    segments = caption_segments(norm(figure.get("caption_en")), visual)
    updated.setdefault("study", {})["panels"] = [
        {
            "label": label,
            "source_text": segments.get(label) or norm(figure.get("caption_en")),
        }
        for label in visual
    ]
    return updated, {
        "id": figure_id,
        "parser_labels": parsed,
        "visual_labels": visual,
        "source_image_present": True,
        "review_issues": review_issues,
        "passed": True,
    }


def generate_with_visual_inventory(
    figures: list[dict[str, Any]],
    *,
    evidence: dict[str, Any],
    plan: dict[str, Any],
    translations: dict[str, str],
    token: str,
    model: str,
    cache_dir: Path,
    cache_prefix: str,
    paper_title: str,
    overview_story: str,
) -> dict[str, dict[str, Any]]:
    del model
    primary_model, reviewer_model, _ = v13.model_settings()
    inventory_cache = cache_dir / "strong-ai-v16" / cache_prefix
    updated_figures: list[dict[str, Any]] = []
    inventory_reports: dict[str, dict[str, Any]] = {}
    for index, figure in enumerate(figures, start=1):
        updated, report = inventory_one(
            figure,
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            reviewer_model=reviewer_model,
            cache_dir=inventory_cache,
        )
        updated_figures.append(updated)
        inventory_reports[str(updated.get("id"))] = report
        print({
            "component": "panel-inventory",
            "completed": index,
            "total": len(figures),
            "id": updated.get("id"),
            "labels": report.get("visual_labels"),
        }, flush=True)

    output = _ORIGINAL_GENERATE(
        updated_figures,
        evidence=evidence,
        plan=plan,
        translations=translations,
        token=token,
        model=primary_model,
        cache_dir=cache_dir,
        cache_prefix=cache_prefix,
        paper_title=paper_title,
        overview_story=overview_story,
    )
    for item in v13.REVIEW_LOG.get("figures") or []:
        report = inventory_reports.get(str(item.get("id")))
        if report:
            item["panel_inventory"] = report
    return output


v13.generate_figure_studies_strong = generate_with_visual_inventory


if __name__ == "__main__":
    v13.main()
