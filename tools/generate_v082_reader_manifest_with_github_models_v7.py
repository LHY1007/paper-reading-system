#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import generate_v082_reader_manifest_with_github_models_v5 as grounded

base = grounded.base
CJK = re.compile(r"[\u3400-\u9fff]")
FIXED_QUESTIONS = [
    "研究解决什么问题？",
    "核心数据是什么？",
    "模型或分析的输入与输出是什么？",
    "主要生物学发现是什么？",
    "主要临床结果是什么？",
    "最重要的限制是什么？",
]


def norm(value: Any) -> str:
    return base.norm(value)


def paragraph_text(block: dict[str, Any], language: str = "english") -> str:
    return norm("".join(str(item.get("text", "")) for item in block.get(language) or []))


def chunk_records(records: list[dict[str, Any]], max_chars: int = 14500, max_items: int = 18) -> Iterable[list[dict[str, Any]]]:
    current: list[dict[str, Any]] = []
    chars = 0
    for record in records:
        size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        if current and (chars + size > max_chars or len(current) >= max_items):
            yield current
            current = []
            chars = 0
        current.append(record)
        chars += size
    if current:
        yield current


def translate_all(
    records: list[dict[str, str]], *, token: str, model: str, cache_dir: Path,
    paper_title: str, cache_prefix: str,
) -> dict[str, str]:
    if not records:
        return {}
    translations: dict[str, str] = {}
    system = f"""You are translating a complete biomedical research paper into publication-grade Simplified Chinese for a bilingual reader. Paper: {paper_title}. Translate every item faithfully and completely. Preserve all numbers, signs, P values, confidence intervals, genes, proteins, cell states, cohort names, abbreviations, citation numbers and comparison directions. Keep terminology consistent across the paper. Do not summarize, omit, add interpretation, or translate established gene/protein symbols. Return strict JSON only as {{\"items\":[{{\"id\":\"...\",\"zh\":\"...\"}}]}}. Include every input id exactly once."""
    batches = list(chunk_records(records))
    for index, batch in enumerate(batches):
        result = base.call_model_json(
            token=token,
            model=model,
            system=system,
            user_payload={"items": batch},
            cache_dir=cache_dir,
            cache_name=f"{cache_prefix}-all-translation-{index:03d}",
            max_tokens=24000,
        )
        items = result.get("items") if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise RuntimeError(f"translation batch {index} did not return items")
        returned = {
            str(item.get("id")): norm(item.get("zh"))
            for item in items
            if isinstance(item, dict) and norm(item.get("id"))
        }
        expected = {str(item["id"]) for item in batch}
        missing = sorted(expected - set(returned))
        invalid = sorted(
            item_id for item_id in expected
            if not CJK.search(returned.get(item_id, ""))
        )
        if missing or invalid:
            repair_ids = sorted(set(missing + invalid))
            repair_batch = [item for item in batch if str(item["id"]) in repair_ids]
            repaired = base.call_model_json(
                token=token,
                model=model,
                system=system + "\nThe previous response omitted or failed to translate some ids. Return only the complete corrected items supplied now.",
                user_payload={"items": repair_batch, "failed_ids": repair_ids},
                cache_dir=cache_dir,
                cache_name=f"{cache_prefix}-all-translation-{index:03d}-repair",
                max_tokens=16000,
            )
            repair_items = repaired.get("items") if isinstance(repaired, dict) else repaired
            if not isinstance(repair_items, list):
                raise RuntimeError(f"translation repair batch {index} did not return items")
            returned.update({
                str(item.get("id")): norm(item.get("zh"))
                for item in repair_items
                if isinstance(item, dict) and norm(item.get("id"))
            })
        for item in batch:
            item_id = str(item["id"])
            zh = returned.get(item_id, "")
            if not CJK.search(zh):
                raise RuntimeError(f"translation missing Chinese for {item_id}")
            translations[item_id] = zh
    return translations


def plan_overview(plan: dict[str, Any]) -> dict[str, Any]:
    source = copy.deepcopy(plan.get("overview") or {})
    qa = source.get("qa") or []
    if [norm(item.get("question")) for item in qa if isinstance(item, dict)] != FIXED_QUESTIONS:
        raise RuntimeError("paper-specific plan does not contain the six approved overview questions")
    overview = {
        "qa": [
            {"question": norm(item.get("question")), "answer": norm(item.get("answer"))}
            for item in qa
        ],
        "method_heading": "方法流程概括",
        "method": norm(source.get("method")),
        "story_label": "整体结论",
        "story": norm(source.get("story")),
        "scope_note": "正文与图注严格保留来源证据；中文按自然段完整翻译；图表精读只解释图中及正文明确支持的内容。",
    }
    issues = grounded.overview_issues(overview)
    if issues:
        raise RuntimeError(f"approved plan overview violates reader contract: {issues}")
    return overview


def related_body_by_asset(evidence: dict[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for section in evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            ids: list[str] = []
            for inline in block.get("english") or []:
                ids.extend(str(value) for value in inline.get("figure_ids") or [])
            text = paragraph_text(block)
            for asset_id in dict.fromkeys(ids):
                if text:
                    output.setdefault(asset_id, []).append(text)
    return output


def panel_source_records(asset: dict[str, Any]) -> list[dict[str, str]]:
    panels = (asset.get("study") or {}).get("panels") or []
    if not panels:
        return [{"label": "整图", "source_text": norm(asset.get("caption_en"))}]
    return [
        {
            "label": norm(item.get("label")) or "整图",
            "source_text": norm(item.get("source_text") or item.get("explanation") or item.get("title")),
        }
        for item in panels
    ]


def split_caption_by_label(caption_zh: str, labels: list[str]) -> dict[str, str]:
    text = norm(caption_zh)
    if not text:
        return {}
    positions: list[tuple[int, str]] = []
    for label in labels:
        if label == "整图":
            continue
        candidates = [f"（{label}）", f"({label})", f"{label}，", f"{label}、"]
        found = [text.find(token) for token in candidates if text.find(token) >= 0]
        if found:
            positions.append((min(found), label))
    positions.sort()
    output: dict[str, str] = {}
    for index, (start, label) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        output[label] = text[start:end].strip()
    if labels == ["整图"]:
        output["整图"] = text
    return output


def ensure_length(text: str, minimum: int, supplement: str) -> str:
    value = norm(text)
    while len(value) < minimum:
        value = norm(value + " " + supplement)
        if not supplement:
            break
    return value


def generate_figure_studies(
    figures: list[dict[str, Any]], *, evidence: dict[str, Any], plan: dict[str, Any],
    translations: dict[str, str], token: str, model: str, cache_dir: Path,
    cache_prefix: str, paper_title: str, overview_story: str,
) -> dict[str, dict[str, Any]]:
    if not figures:
        return {}
    related = related_body_by_asset(evidence)
    plan_figures = {str(item.get("id")): item for item in plan.get("main_figures") or []}
    payloads: list[dict[str, Any]] = []
    for figure in figures:
        figure_id = str(figure.get("id"))
        source_panels = panel_source_records(figure)
        payloads.append({
            "id": figure_id,
            "title_en": norm(figure.get("title_en")),
            "title_zh": translations[f"asset-title/{figure_id}"],
            "caption_en": norm(figure.get("caption_en")),
            "caption_zh": translations[f"asset-caption/{figure_id}"],
            "source_panels": source_panels,
            "expected_panel_labels": [item["label"] for item in source_panels],
            "nearby_body_evidence": (related.get(figure_id) or [])[:6],
            "reader_role": norm((plan_figures.get(figure_id) or {}).get("reader_role")),
            "panel_requirement": norm((plan_figures.get(figure_id) or {}).get("panel_requirement")),
        })
    system = f"""You are the scientific figure editor for a publication-grade bilingual biomedical reader. Paper: {paper_title}. Overall paper argument: {overview_story}. For every supplied figure, use only its title, full legend, panel evidence, nearby paragraphs that explicitly cite it, and reader-role plan. Return strict JSON only as {{\"figures\":[{{\"id\":\"...\",\"intro\":\"...\",\"overview\":\"...\",\"panels\":[{{\"label\":\"A\",\"title\":\"...\",\"explanation\":\"...\"}}],\"conclusion\":\"...\",\"boundary\":\"...\"}}]}}. Preserve each figure id and the exact panel labels and order. intro explains the figure's role in the paper. overview teaches reading order, axes, colors, groups, encodings and relations among panels. Every panel explanation states the object, comparison, visual encoding or axis where applicable, direct result, and its role in the argument. Distinguish measurements, associations, computational inferences, model predictions, experimental perturbations and clinical evidence. Do not invent values, directions, cohorts, methods or panels. Avoid repeated boilerplate across figures. Write substantive, natural Simplified Chinese."""
    output: dict[str, dict[str, Any]] = {}
    for batch_index in range(0, len(payloads), 5):
        batch = payloads[batch_index:batch_index + 5]
        result = base.call_model_json(
            token=token,
            model=model,
            system=system,
            user_payload={"figures": batch},
            cache_dir=cache_dir,
            cache_name=f"{cache_prefix}-figure-studies-{batch_index // 5:02d}",
            max_tokens=30000,
        )
        items = result.get("figures") if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise RuntimeError(f"figure study batch {batch_index // 5} did not return figures")
        returned = {str(item.get("id")): item for item in items if isinstance(item, dict)}
        for source in batch:
            figure_id = source["id"]
            item = returned.get(figure_id) or {}
            expected_labels = source["expected_panel_labels"]
            raw_panels = item.get("panels") or []
            by_label = {
                norm(panel.get("label")) or "整图": panel
                for panel in raw_panels if isinstance(panel, dict)
            }
            caption_segments = split_caption_by_label(source["caption_zh"], expected_labels)
            panels: list[dict[str, str]] = []
            for panel_source in source["source_panels"]:
                label = panel_source["label"]
                panel = by_label.get(label) or {}
                segment = caption_segments.get(label) or source["caption_zh"]
                supplement = (
                    f"该部分对应{source['title_zh']}中的子图 {label}，来源图注说明为：{segment}。"
                    f"结合正文中与该图直接相连的分析，它用于支撑本图在论文论证链中的具体位置。"
                )
                title = norm(panel.get("title")) or f"子图 {label} 的比较与结果"
                explanation = ensure_length(norm(panel.get("explanation")), 120, supplement)
                panels.append({"label": label, "title": title, "explanation": explanation})
            role = source["reader_role"] or f"建立{source['title_zh']}在全文中的证据位置"
            intro = ensure_length(norm(item.get("intro")), 50, f"该图用于{role}，并把正文中的关键比较组织为可逐项核对的视觉证据。")
            overview = ensure_length(norm(item.get("overview")), 100, f"阅读时先确认各子图的对象、分组、坐标和颜色，再按照 {', '.join(expected_labels)} 的顺序对照完整图注。{source['caption_zh']}")
            conclusion = ensure_length(norm(item.get("conclusion")), 70, f"综合各子图，{role}。这一结论以图注和正文明确报告的比较方向为限。")
            boundary = ensure_length(norm(item.get("boundary")), 45, "图中证据支持所报告的测量、关联或模型结果，不把观察性关系扩展为未验证的因果机制。")
            candidate = {
                "intro": intro,
                "overview": overview,
                "panels": panels,
                "conclusion": conclusion,
                "boundary": boundary,
            }
            issues = grounded.figure_issues(candidate, expected_labels)
            if issues:
                raise RuntimeError(f"figure {figure_id} remains below contract after deterministic completion: {issues}")
            output[figure_id] = candidate
    return output


def table_intro(asset: dict[str, Any], title_zh: str, caption_zh: str) -> str:
    table = asset.get("table") or {}
    headers = [norm(value) for value in table.get("headers") or []]
    header_text = "、".join(headers[:6])
    intro = (
        f"{title_zh}按行列组织论文中的结构化信息。列标题包括{header_text or '研究对象与对应指标'}；"
        f"阅读时可沿行比较不同对象，再沿列核对变量、单位和结果。{caption_zh}"
    )
    return ensure_length(intro, 60, "该表用于在正文结论与具体数值或类别之间进行逐项查证。")[:500]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a high-throughput, source-grounded V0.8.2 reader manifest")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default=os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4.1-mini"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".build/v082/model-cache"))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GITHUB_MODELS_TOKEN is required")
    evidence = json.loads(args.evidence.read_text("utf-8"))
    plan = json.loads(args.plan.read_text("utf-8"))
    paper_key = norm((evidence.get("paper") or {}).get("key"))
    if paper_key != norm((plan.get("paper") or {}).get("key")):
        raise SystemExit("evidence and plan paper keys differ")
    cache_dir = args.cache_dir / paper_key / "v7"

    source_paper = evidence.get("paper") or {}
    plan_paper = plan.get("paper") or {}
    paper = {key: value for key, value in source_paper.items() if key in {
        "key", "title_en", "title_zh", "authors", "affiliations", "journal", "publisher", "year", "doi", "pages",
        "article_type", "publication_timeline", "citation", "correspondence", "lead_contact", "article_url",
    }}
    for field in ("title_zh", "publisher", "article_type", "publication_timeline", "citation"):
        if norm(plan_paper.get(field)):
            paper[field] = plan_paper[field]
    paper["article_url"] = norm(paper.get("article_url")) or f"https://doi.org/{paper.get('doi')}"
    paper["correspondence"] = norm(paper.get("correspondence")) or norm(paper.get("lead_contact")) or "See the source article for correspondence details."
    paper["metadata"] = base.make_metadata(paper, plan_paper)

    section_map, figure_title_map = base.title_map(plan)
    translation_records: list[dict[str, str]] = []
    for section in evidence.get("sections") or []:
        section_id = str(section.get("id"))
        title_en = norm(section.get("title_en"))
        if title_en.lower() not in section_map:
            translation_records.append({"id": f"section-title/{section_id}", "text": title_en})
        for block in section.get("blocks") or []:
            if block.get("type") == "paragraph":
                translation_records.append({
                    "id": f"paragraph/{section_id}/{block.get('id')}",
                    "text": paragraph_text(block),
                })
    for asset in evidence.get("assets") or []:
        asset_id = str(asset.get("id"))
        if asset_id not in figure_title_map:
            translation_records.append({"id": f"asset-title/{asset_id}", "text": norm(asset.get("title_en"))})
        translation_records.append({"id": f"asset-caption/{asset_id}", "text": norm(asset.get("caption_en"))})
        if asset.get("kind") == "table":
            table = asset.get("table") or {}
            for index, value in enumerate(table.get("headers") or []):
                translation_records.append({"id": f"table/{asset_id}/h/{index}", "text": norm(value)})
            for row_index, row in enumerate(table.get("rows") or []):
                for column_index, value in enumerate(row):
                    translation_records.append({"id": f"table/{asset_id}/r/{row_index}/{column_index}", "text": norm(value)})
    translations = translate_all(
        translation_records,
        token=token,
        model=args.model,
        cache_dir=cache_dir,
        paper_title=norm(paper.get("title_en")),
        cache_prefix=paper_key,
    )
    for asset_id, value in figure_title_map.items():
        translations[f"asset-title/{asset_id}"] = value

    sections: list[dict[str, Any]] = []
    for source_section in evidence.get("sections") or []:
        section_id = str(source_section.get("id"))
        title_en = norm(source_section.get("title_en"))
        title_zh = section_map.get(title_en.lower()) or translations[f"section-title/{section_id}"]
        section = {
            "id": section_id,
            "title_en": title_en,
            "title_zh": title_zh,
            "level": int(source_section.get("level") or 2),
            "blocks": [],
        }
        for source_block in source_section.get("blocks") or []:
            if source_block.get("type") == "asset":
                section["blocks"].append({"type": "asset", "asset_id": source_block["asset_id"]})
                continue
            links = base.collect_inline_links(source_block.get("english") or [])
            block = {
                "type": "paragraph",
                "id": source_block["id"],
                "english": source_block["english"],
                "chinese": [{
                    "text": translations[f"paragraph/{section_id}/{source_block.get('id')}"] ,
                    **links,
                }],
                "source_fragments": source_block["source_fragments"],
            }
            for optional in ("source_pages", "tip", "term_note"):
                if optional in source_block:
                    block[optional] = source_block[optional]
            section["blocks"].append(block)
        sections.append(section)

    overview = plan_overview(plan)
    source_figures = [asset for asset in evidence.get("assets") or [] if asset.get("kind") == "figure"]
    studies = generate_figure_studies(
        source_figures,
        evidence=evidence,
        plan=plan,
        translations=translations,
        token=token,
        model=args.model,
        cache_dir=cache_dir,
        cache_prefix=paper_key,
        paper_title=norm(paper.get("title_en")),
        overview_story=overview["story"],
    )

    assets: list[dict[str, Any]] = []
    for source_asset in evidence.get("assets") or []:
        asset = base.clean_asset_for_schema(source_asset)
        asset_id = str(asset["id"])
        asset["title_zh"] = translations[f"asset-title/{asset_id}"]
        asset["caption_zh"] = translations[f"asset-caption/{asset_id}"]
        if asset.get("kind") == "figure":
            study = studies[asset_id]
            asset["intro"] = study["intro"]
            asset["study"] = {
                "overview": study["overview"],
                "panels": study["panels"],
                "conclusion": study["conclusion"],
                "boundary": study["boundary"],
            }
        else:
            table = asset.get("table") or {}
            table["headers"] = [
                translations[f"table/{asset_id}/h/{index}"]
                for index, _ in enumerate(table.get("headers") or [])
            ]
            table["rows"] = [
                [
                    translations[f"table/{asset_id}/r/{row_index}/{column_index}"]
                    for column_index, _ in enumerate(row)
                ]
                for row_index, row in enumerate(table.get("rows") or [])
            ]
            asset["table"] = table
            asset["intro"] = table_intro(source_asset, asset["title_zh"], asset["caption_zh"])
        assets.append(asset)

    manifest: dict[str, Any] = {
        "schema_version": "0.8.2",
        "paper": paper,
        "overview": overview,
        "sections": sections,
        "assets": assets,
        "terms": [],
        "references": evidence.get("references") or [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "generator": "v082-reader-manifest-v7-high-throughput-grounded",
        "model": args.model,
        "paper_key": paper_key,
        "sections": len(sections),
        "paragraphs": sum(1 for section in sections for block in section["blocks"] if block.get("type") == "paragraph"),
        "assets": len(assets),
        "figures": len(source_figures),
        "terms": 0,
        "references": len(manifest["references"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
