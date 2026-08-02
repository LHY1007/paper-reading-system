#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CJK = re.compile(r"[\u3400-\u9fff]")
FIXED_QUESTIONS = [
    "研究解决什么问题？",
    "核心数据是什么？",
    "模型或分析的输入与输出是什么？",
    "主要生物学发现是什么？",
    "主要临床结果是什么？",
    "最重要的限制是什么？",
]
BAD_GENERIC = re.compile(
    r"本图(?:主要|展示|说明)|该图(?:主要|展示|说明)|需要进一步验证|不能证明因果|仅供参考",
)
ENTITY = re.compile(r"\b(?:[A-Z][A-Z0-9-]{1,}|[A-Za-z]+\d+[A-Za-z0-9-]*|\d+(?:\.\d+)?%?|[A-Za-z]+-[A-Za-z0-9-]+)\b")


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def text_of(block: dict[str, Any], key: str) -> str:
    return norm("".join(str(item.get("text", "")) for item in block.get(key) or []))


def sha(value: str) -> str:
    return hashlib.sha256(norm(value).encode("utf-8")).hexdigest()


def add(errors: list[dict[str, Any]], path: str, issue: str, detail: Any = None) -> None:
    item: dict[str, Any] = {"path": path, "issue": issue}
    if detail is not None:
        item["detail"] = detail if isinstance(detail, (int, float, bool, list, dict)) else norm(detail)[:500]
    errors.append(item)


def indexed_blocks(document: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    order: list[str] = []
    blocks: dict[str, dict[str, Any]] = {}
    for section in document.get("sections") or []:
        sid = str(section.get("id"))
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            key = f"{sid}/{block.get('id')}"
            order.append(key)
            blocks[key] = block
    return order, blocks


def source_entities(figure: dict[str, Any], related: list[str]) -> set[str]:
    text = " ".join([
        norm(figure.get("title_en")),
        norm(figure.get("caption_en")),
        *related,
    ])
    return {token.lower() for token in ENTITY.findall(text) if len(token) >= 2}


def related_body(evidence: dict[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for section in evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            ids: list[str] = []
            for inline in block.get("english") or []:
                ids.extend(str(value) for value in inline.get("figure_ids") or [])
            text = text_of(block, "english")
            for asset_id in dict.fromkeys(ids):
                output.setdefault(asset_id, []).append(text)
    return output


def validate(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    mp = manifest.get("paper") or {}
    ep = evidence.get("paper") or {}
    for field in ("key", "title_en", "doi", "journal", "pages"):
        if norm(mp.get(field)).lower() != norm(ep.get(field)).lower():
            add(errors, f"paper.{field}", "manifest diverges from source evidence", {"manifest": mp.get(field), "evidence": ep.get(field)})
    if [norm(x) for x in mp.get("authors") or []] != [norm(x) for x in ep.get("authors") or []]:
        add(errors, "paper.authors", "author order must exactly match source evidence")
    if [norm(x) for x in mp.get("affiliations") or []] != [norm(x) for x in ep.get("affiliations") or []]:
        add(errors, "paper.affiliations", "affiliation order must exactly match source evidence")

    m_order, m_blocks = indexed_blocks(manifest)
    e_order, e_blocks = indexed_blocks(evidence)
    if m_order != e_order:
        add(errors, "sections", "paragraph inventory/order must exactly match evidence", {"manifest_count": len(m_order), "evidence_count": len(e_order)})
    for key in e_order:
        if key not in m_blocks:
            continue
        english_manifest = text_of(m_blocks[key], "english")
        english_evidence = text_of(e_blocks[key], "english")
        if sha(english_manifest) != sha(english_evidence):
            add(errors, f"sections/{key}/english", "English source text changed during content generation")
        chinese = text_of(m_blocks[key], "chinese")
        if not CJK.search(chinese):
            add(errors, f"sections/{key}/chinese", "Chinese translation is missing")
        if len(chinese) < max(8, int(len(english_evidence) * 0.12)):
            add(errors, f"sections/{key}/chinese", "translation is implausibly short relative to source", {"en_chars": len(english_evidence), "zh_chars": len(chinese)})

    overview = manifest.get("overview") or {}
    qa = overview.get("qa") or []
    if [norm(item.get("question")) for item in qa if isinstance(item, dict)] != FIXED_QUESTIONS:
        add(errors, "overview.qa", "fixed overview questions changed or reordered")
    if len(qa) == 6:
        answers = [norm(item.get("answer")) for item in qa]
        if not re.search(r"\d", answers[1]):
            add(errors, "overview.qa[1]", "core-data answer lacks concrete counts")
        if not re.search(r"输入|输出|预测|生成|分析对象|映射|分类|推断", answers[2]):
            add(errors, "overview.qa[2]", "input-output answer is not operationally explicit")
        if answers[3] == answers[4] or len(set(answers[3].split("，")) & set(answers[4].split("，"))) > 4:
            add(errors, "overview.qa[3:5]", "biological and clinical answers are insufficiently separated")
        if not re.search(r"限制|局限|尚未|不能|缺乏|仍需|未能|依赖|偏倚", answers[5]):
            add(errors, "overview.qa[5]", "limitation is not stated as a concrete evidence boundary")
    method = norm(overview.get("method"))
    if not (4 <= method.count("→") <= 8):
        add(errors, "overview.method", "workflow must contain 5-9 stages")

    m_assets = {str(item.get("id")): item for item in manifest.get("assets") or []}
    e_assets = {str(item.get("id")): item for item in evidence.get("assets") or []}
    if list(m_assets) != list(e_assets):
        add(errors, "assets", "asset inventory/order must exactly match evidence", {"manifest": list(m_assets), "evidence": list(e_assets)})
    related = related_body(evidence)
    repeated_explanations: list[tuple[str, str]] = []
    for asset_id, source in e_assets.items():
        target = m_assets.get(asset_id)
        if target is None:
            continue
        if target.get("kind") != source.get("kind"):
            add(errors, f"assets/{asset_id}/kind", "asset kind changed")
        if sha(target.get("title_en", "")) != sha(source.get("title_en", "")):
            add(errors, f"assets/{asset_id}/title_en", "source figure/table title changed")
        if sha(target.get("caption_en", "")) != sha(source.get("caption_en", "")):
            add(errors, f"assets/{asset_id}/caption_en", "source legend changed")
        if target.get("kind") == "figure":
            expected_labels = [
                norm(item.get("label")) or "整图"
                for item in (source.get("study") or {}).get("panels") or []
            ] or ["整图"]
            study = target.get("study") or {}
            panels = study.get("panels") or []
            actual_labels = [norm(item.get("label")) or "整图" for item in panels if isinstance(item, dict)]
            if actual_labels != expected_labels:
                add(errors, f"assets/{asset_id}/study/panels", "panel labels/order diverge from evidence", {"expected": expected_labels, "actual": actual_labels})
            entities = source_entities(source, related.get(asset_id) or [])
            for index, panel in enumerate(panels):
                explanation = norm(panel.get("explanation"))
                overlap = {token.lower() for token in ENTITY.findall(explanation)} & entities
                if entities and not overlap:
                    add(errors, f"assets/{asset_id}/study/panels/{index}", "panel explanation contains no traceable source entity or value")
                repeated_explanations.append((asset_id, explanation))
                if BAD_GENERIC.search(explanation) and len(explanation) < 180:
                    add(errors, f"assets/{asset_id}/study/panels/{index}", "generic prose is substituting for panel-specific explanation")
        else:
            table = target.get("table") or {}
            source_table = source.get("table") or {}
            if len(table.get("headers") or []) != len(source_table.get("headers") or []):
                add(errors, f"assets/{asset_id}/table/headers", "translated table changed column count")
            if len(table.get("rows") or []) != len(source_table.get("rows") or []):
                add(errors, f"assets/{asset_id}/table/rows", "translated table changed row count")
            if len(norm(target.get("intro"))) < 45:
                add(errors, f"assets/{asset_id}/intro", "table introduction is too generic or missing")

    for i, (aid, left) in enumerate(repeated_explanations):
        left_tokens = set(re.findall(r"[\u3400-\u9fff]{2,}", left))
        if not left_tokens:
            continue
        for bid, right in repeated_explanations[i + 1:]:
            if aid == bid:
                continue
            right_tokens = set(re.findall(r"[\u3400-\u9fff]{2,}", right))
            union = left_tokens | right_tokens
            similarity = len(left_tokens & right_tokens) / max(1, len(union))
            if similarity > 0.72:
                add(errors, f"assets/{aid}|{bid}", "figure explanations are suspiciously templated/repeated", round(similarity, 3))
                break

    m_refs = manifest.get("references") or []
    e_refs = evidence.get("references") or []
    if [(str(x.get("id")), sha(x.get("text", ""))) for x in m_refs] != [(str(x.get("id")), sha(x.get("text", ""))) for x in e_refs]:
        add(errors, "references", "reference numbering or bibliographic text changed from evidence")

    return {
        "version": "v082-reader-semantics-2",
        "paper_key": norm(mp.get("key")),
        "paragraphs": len(m_order),
        "assets": len(m_assets),
        "references": len(m_refs),
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate component-level scientific grounding of a V0.8.2 reader manifest")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(
        json.loads(args.manifest.read_text("utf-8")),
        json.loads(args.evidence.read_text("utf-8")),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
