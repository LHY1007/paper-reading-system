#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_github_models_v4 as reliable

base = reliable.base
CJK = re.compile(r"[\u3400-\u9fff]")
FIXED_QUESTIONS = [
    "研究解决什么问题？",
    "核心数据是什么？",
    "模型或分析的输入与输出是什么？",
    "主要生物学发现是什么？",
    "主要临床结果是什么？",
    "最重要的限制是什么？",
]
BAD_READER_TEXT = re.compile(
    r"source pdf|extracted|sha-?256|ethics statement|nuclei isolation|https?://doi\.org",
    re.I,
)


def norm(value: Any) -> str:
    return base.norm(value)


def paragraph_text(block: dict[str, Any], language: str = "english") -> str:
    return norm("".join(str(item.get("text", "")) for item in block.get(language) or []))


def collect_evidence_digest(evidence: dict[str, Any], max_chars: int = 18000) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    used = 0
    for section in evidence.get("sections") or []:
        title = norm(section.get("title_en"))
        paragraphs = [
            paragraph_text(block)
            for block in section.get("blocks") or []
            if block.get("type") == "paragraph" and paragraph_text(block)
        ]
        if not paragraphs:
            continue
        selected: list[str] = []
        if title.lower() in {"summary", "abstract", "introduction", "discussion", "conclusion", "conclusions"}:
            selected = paragraphs[:5]
        elif re.search(r"result|finding|analysis|validation|performance|clinical|survival|outcome", title, re.I):
            selected = paragraphs[:3] + paragraphs[-1:]
        else:
            selected = paragraphs[:2]
        text = "\n".join(selected)
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining]
        sections.append({"title": title, "text": text})
        used += len(text)
    figures = [
        {
            "id": asset.get("id"),
            "title": norm(asset.get("title_en")),
            "caption": norm(asset.get("caption_en"))[:2500],
        }
        for asset in evidence.get("assets") or []
        if asset.get("kind") == "figure"
    ][:8]
    return {
        "paper": evidence.get("paper") or {},
        "sections": sections,
        "figures": figures,
    }


def overview_issues(overview: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    qa = overview.get("qa") or []
    questions = [norm(item.get("question")) for item in qa if isinstance(item, dict)]
    if questions != FIXED_QUESTIONS:
        issues.append("qa questions must exactly match the six fixed questions in order")
    if len(qa) != 6:
        issues.append("qa must contain exactly six items")
    for index, item in enumerate(qa[:6]):
        answer = norm(item.get("answer"))
        if not CJK.search(answer) or not (35 <= len(answer) <= 260):
            issues.append(f"qa[{index}] must be 35-260 characters of specific Chinese")
        if BAD_READER_TEXT.search(answer):
            issues.append(f"qa[{index}] contains parser or source-audit language")
    if len(qa) >= 3:
        data_answer = norm(qa[1].get("answer"))
        io_answer = norm(qa[2].get("answer"))
        if not re.search(r"\d", data_answer):
            issues.append("core-data answer must contain concrete cohort/sample/channel counts")
        if not re.search(r"输入|输出|预测|生成|分析对象|得到", io_answer):
            issues.append("input-output answer must explicitly state analytical input and output")
    if len(qa) >= 6:
        limitation = norm(qa[5].get("answer"))
        if not re.search(r"限制|局限|尚未|不能|缺乏|仍需|未能|依赖|偏倚", limitation):
            issues.append("limitation answer must state a design-supported limitation")
    method = norm(overview.get("method"))
    if not CJK.search(method) or not (4 <= method.count("→") <= 8):
        issues.append("method must be a 5-9-stage Chinese arrow-linked workflow")
    story = norm(overview.get("story"))
    if not CJK.search(story) or len(story) < 90:
        issues.append("story must be at least 90 Chinese characters")
    return issues


def generate_overview(
    evidence: dict[str, Any], plan: dict[str, Any], *, token: str, model: str,
    cache_dir: Path, cache_prefix: str,
) -> dict[str, Any]:
    digest = collect_evidence_digest(evidence)
    payload = {
        "source_evidence": digest,
        "paper_specific_plan": plan.get("overview") or {},
        "fixed_questions": FIXED_QUESTIONS,
    }
    system = """You are writing the one-page overview of a publication-grade bilingual biomedical paper reader. Use only the supplied source evidence and paper-specific plan. Do not copy an abstract sentence verbatim and do not mention PDF parsing, pages extracted, SHA values, ethics boilerplate, or source files. Return strict JSON only with keys qa, method, story. qa must contain exactly the six supplied questions in the same order. Each answer must be specific to this paper and 45-180 Chinese characters. The core-data answer must name cohorts, sample sizes, modalities, and discovery/validation relationships. The input-output answer must state the actual analytical input, transformation, and output rather than a generic method description. Keep biological findings separate from clinical results. The limitation must be directly supported by study design or the authors' discussion and must not be a generic disclaimer. method must be a 5-9-stage arrow-linked Chinese workflow. story must explain the paper's full argument, what it establishes, and what it does not establish, in 120-260 Chinese characters. Preserve numbers, biomarker names, cohort names, directions of effect, and uncertainty. Do not invent facts."""
    result = base.call_model_json(
        token=token, model=model, system=system, user_payload=payload,
        cache_dir=cache_dir, cache_name=f"{cache_prefix}-overview-v5", max_tokens=10000,
    )
    candidate = result.get("overview") if isinstance(result, dict) and isinstance(result.get("overview"), dict) else result
    if not isinstance(candidate, dict):
        raise RuntimeError("overview response is not an object")
    candidate = {
        "qa": [
            {"question": norm(item.get("question")), "answer": norm(item.get("answer"))}
            for item in candidate.get("qa") or [] if isinstance(item, dict)
        ],
        "method_heading": "方法流程概括",
        "method": norm(candidate.get("method")),
        "story_label": "整体结论",
        "story": norm(candidate.get("story")),
        "scope_note": "正文与图注严格保留来源证据；中文按自然段翻译；图表精读仅解释图中及正文明确支持的结果。",
    }
    issues = overview_issues(candidate)
    if issues:
        repair_payload = {**payload, "previous_answer": candidate, "validation_issues": issues}
        repair_system = system + "\nRepair every listed validation issue. Return the complete corrected overview, not a patch."
        repaired = base.call_model_json(
            token=token, model=model, system=repair_system, user_payload=repair_payload,
            cache_dir=cache_dir, cache_name=f"{cache_prefix}-overview-v5-repair", max_tokens=10000,
        )
        item = repaired.get("overview") if isinstance(repaired, dict) and isinstance(repaired.get("overview"), dict) else repaired
        if not isinstance(item, dict):
            raise RuntimeError("overview repair response is not an object")
        candidate.update({
            "qa": [
                {"question": norm(x.get("question")), "answer": norm(x.get("answer"))}
                for x in item.get("qa") or [] if isinstance(x, dict)
            ],
            "method": norm(item.get("method")),
            "story": norm(item.get("story")),
        })
        issues = overview_issues(candidate)
    if issues:
        raise RuntimeError(f"overview remains below reader contract after repair: {issues}")
    return candidate


def related_body_by_asset(evidence: dict[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for section in evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            text = paragraph_text(block)
            if not text:
                continue
            ids: list[str] = []
            for inline in block.get("english") or []:
                ids.extend(str(value) for value in inline.get("figure_ids") or [])
            for asset_id in dict.fromkeys(ids):
                output.setdefault(asset_id, []).append(text)
    return output


def panel_labels(figure: dict[str, Any]) -> list[str]:
    labels = [
        norm(panel.get("label")) or "整图"
        for panel in (figure.get("study") or {}).get("panels") or []
    ]
    return labels or ["整图"]


def figure_issues(study: dict[str, Any], labels: list[str]) -> list[str]:
    issues: list[str] = []
    if not CJK.search(norm(study.get("intro"))) or len(norm(study.get("intro"))) < 45:
        issues.append("intro must explain the figure's role in at least 45 Chinese characters")
    if not CJK.search(norm(study.get("overview"))) or len(norm(study.get("overview"))) < 100:
        issues.append("overview must explain reading order and encodings in at least 100 Chinese characters")
    panels = study.get("panels") or []
    actual = [norm(item.get("label")) or "整图" for item in panels if isinstance(item, dict)]
    if actual != labels:
        issues.append(f"panel labels/order must exactly match {labels}")
    for index, item in enumerate(panels):
        if not isinstance(item, dict):
            issues.append(f"panel {index} is not an object")
            continue
        if not CJK.search(norm(item.get("title"))) or len(norm(item.get("title"))) < 4:
            issues.append(f"panel {index} needs a specific Chinese title")
        explanation = norm(item.get("explanation"))
        if not CJK.search(explanation) or len(explanation) < 120:
            issues.append(f"panel {index} explanation must be at least 120 Chinese characters")
        if re.search(r"本图仅能|不能证明因果|需要进一步验证", explanation) and len(explanation) < 170:
            issues.append(f"panel {index} is dominated by a generic boundary disclaimer")
    if not CJK.search(norm(study.get("conclusion"))) or len(norm(study.get("conclusion"))) < 70:
        issues.append("conclusion must synthesize the figure in at least 70 Chinese characters")
    if not CJK.search(norm(study.get("boundary"))) or len(norm(study.get("boundary"))) < 40:
        issues.append("boundary must state the specific evidence boundary")
    return issues


def generate_grounded_studies(
    figures: list[dict[str, Any]], evidence: dict[str, Any], plan: dict[str, Any], *,
    token: str, model: str, cache_dir: Path, cache_prefix: str, paper_context: str,
) -> dict[str, dict[str, Any]]:
    related = related_body_by_asset(evidence)
    plan_figures = {str(item.get("id")): item for item in plan.get("main_figures") or []}
    output: dict[str, dict[str, Any]] = {}
    system = f"""You are the scientific figure editor for a publication-grade bilingual biomedical reader. Paper context: {paper_context}. Explain one figure at a time using only its source title, complete legend, supplied panel evidence, nearby body paragraphs that explicitly cite it, and the reader-role plan. Return strict JSON only with id, intro, overview, panels, conclusion, boundary. Preserve the exact panel labels and order. intro must explain why this figure appears at this point in the paper. overview must teach the reading order, visual encodings, axes, colors, groups, and relationship among panels. Each panel explanation must state the object, comparison, encoding/axis where applicable, result, and its role in the paper's argument. Distinguish direct measurement, association, computational inference, model prediction, in-vitro evidence, and clinical evidence. Do not invent numerical values, directions, cohorts, methods, or panels. Do not use generic boilerplate in place of explaining the figure."""
    for figure in figures:
        figure_id = str(figure.get("id"))
        labels = panel_labels(figure)
        source_panels = [
            {
                "label": norm(panel.get("label")) or "整图",
                "source_text": norm(panel.get("source_text") or panel.get("explanation") or panel.get("title")),
            }
            for panel in (figure.get("study") or {}).get("panels") or []
        ] or [{"label": "整图", "source_text": norm(figure.get("caption_en"))}]
        payload = {
            "id": figure_id,
            "title_en": norm(figure.get("title_en")),
            "caption_en": norm(figure.get("caption_en")),
            "source_panels": source_panels,
            "nearby_body_evidence": (related.get(figure_id) or [])[:8],
            "expected_panel_labels": labels,
            "reader_role": (plan_figures.get(figure_id) or {}).get("reader_role"),
            "panel_requirement": (plan_figures.get(figure_id) or {}).get("panel_requirement"),
        }
        result = base.call_model_json(
            token=token, model=model, system=system, user_payload=payload,
            cache_dir=cache_dir, cache_name=f"{cache_prefix}-figure-v5-{figure_id}", max_tokens=14000,
        )
        item = result.get("item") if isinstance(result, dict) and isinstance(result.get("item"), dict) else result
        if not isinstance(item, dict):
            raise RuntimeError(f"figure {figure_id} response is not an object")
        candidate = {
            "intro": norm(item.get("intro")),
            "overview": norm(item.get("overview")),
            "panels": [
                {
                    "label": norm(panel.get("label")) or "整图",
                    "title": norm(panel.get("title")),
                    "explanation": norm(panel.get("explanation")),
                }
                for panel in item.get("panels") or [] if isinstance(panel, dict)
            ],
            "conclusion": norm(item.get("conclusion")),
            "boundary": norm(item.get("boundary")),
        }
        issues = figure_issues(candidate, labels)
        if issues:
            repaired = base.call_model_json(
                token=token,
                model=model,
                system=system + "\nRepair every validation issue and return the complete corrected figure explanation.",
                user_payload={**payload, "previous_answer": candidate, "validation_issues": issues},
                cache_dir=cache_dir,
                cache_name=f"{cache_prefix}-figure-v5-{figure_id}-repair",
                max_tokens=14000,
            )
            item = repaired.get("item") if isinstance(repaired, dict) and isinstance(repaired.get("item"), dict) else repaired
            if not isinstance(item, dict):
                raise RuntimeError(f"figure {figure_id} repair response is not an object")
            candidate = {
                "intro": norm(item.get("intro")),
                "overview": norm(item.get("overview")),
                "panels": [
                    {
                        "label": norm(panel.get("label")) or "整图",
                        "title": norm(panel.get("title")),
                        "explanation": norm(panel.get("explanation")),
                    }
                    for panel in item.get("panels") or [] if isinstance(panel, dict)
                ],
                "conclusion": norm(item.get("conclusion")),
                "boundary": norm(item.get("boundary")),
            }
            issues = figure_issues(candidate, labels)
        if issues:
            raise RuntimeError(f"figure {figure_id} remains below reader contract: {issues}")
        output[figure_id] = candidate
    return output


def generate_table_intro(
    asset: dict[str, Any], *, token: str, model: str, cache_dir: Path, cache_prefix: str,
) -> str:
    table = asset.get("table") or {}
    payload = {
        "title_en": norm(asset.get("title_en")),
        "caption_en": norm(asset.get("caption_en")),
        "headers": table.get("headers") or [],
        "sample_rows": (table.get("rows") or [])[:8],
    }
    system = """Write one reader-facing Simplified Chinese introduction for a scientific table. Use only the supplied title, caption, headers and rows. In 60-160 Chinese characters, explain what entities are organized by rows and columns, what comparison or lookup the table supports, and how it connects to the paper. Do not say merely that the table summarizes variables. Preserve marker names, cohort names and units. Return JSON only: {\"intro\":\"...\"}."""
    result = base.call_model_json(
        token=token, model=model, system=system, user_payload=payload,
        cache_dir=cache_dir, cache_name=f"{cache_prefix}-table-intro-v5-{asset.get('id')}", max_tokens=3000,
    )
    intro = norm(result.get("intro") if isinstance(result, dict) else "")
    if not CJK.search(intro) or not (45 <= len(intro) <= 220):
        raise RuntimeError(f"table {asset.get('id')} intro is not reader-ready")
    return intro


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a grounded, component-by-component V0.8.2 reader manifest")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default=os.environ.get("GITHUB_MODELS_MODEL", "openai/gpt-4.1"))
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
    cache_dir = args.cache_dir / paper_key
    plan_paper = plan.get("paper") or {}
    source_paper = evidence.get("paper") or {}
    paper = {key: value for key, value in source_paper.items() if key in {
        "key", "title_en", "title_zh", "authors", "affiliations", "journal", "publisher", "year", "doi", "pages",
        "article_type", "publication_timeline", "citation", "correspondence", "lead_contact", "article_url",
    }}
    for field in ("title_zh", "journal", "publisher", "article_type", "publication_timeline", "citation"):
        if norm(plan_paper.get(field)):
            paper[field] = plan_paper[field]
    paper["article_url"] = norm(paper.get("article_url")) or f"https://doi.org/{paper.get('doi')}"
    paper["metadata"] = base.make_metadata(paper, plan_paper)

    section_map, figure_title_map = base.title_map(plan)
    title_records = [
        {"id": str(section.get("id")), "text": norm(section.get("title_en"))}
        for section in evidence.get("sections") or []
        if norm(section.get("title_en")).lower() not in section_map
    ]
    translated_section_titles = base.translate_records(
        title_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-sections-v5", context=paper["title_en"],
    ) if title_records else {}

    paragraph_records: list[dict[str, str]] = []
    for section in evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") == "paragraph":
                paragraph_records.append({
                    "id": f"{section.get('id')}/{block.get('id')}",
                    "text": paragraph_text(block),
                })
    paragraph_translations = base.translate_records(
        paragraph_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-body-v5", context=paper["title_en"],
    )

    sections: list[dict[str, Any]] = []
    for source_section in evidence.get("sections") or []:
        section_id = str(source_section.get("id"))
        title_en = norm(source_section.get("title_en"))
        section = {
            "id": section_id,
            "title_en": title_en,
            "title_zh": section_map.get(title_en.lower()) or translated_section_titles[section_id],
            "level": int(source_section.get("level") or 2),
            "blocks": [],
        }
        for source_block in source_section.get("blocks") or []:
            if source_block.get("type") == "asset":
                section["blocks"].append({"type": "asset", "asset_id": source_block["asset_id"]})
                continue
            block_id = f"{section_id}/{source_block.get('id')}"
            links = base.collect_inline_links(source_block.get("english") or [])
            block = {
                "type": "paragraph",
                "id": source_block["id"],
                "english": source_block["english"],
                "chinese": [{"text": paragraph_translations[block_id], **links}],
                "source_fragments": source_block["source_fragments"],
            }
            for optional in ("source_pages", "tip", "term_note"):
                if optional in source_block:
                    block[optional] = source_block[optional]
            section["blocks"].append(block)
        sections.append(section)

    asset_title_records: list[dict[str, str]] = []
    caption_records: list[dict[str, str]] = []
    table_records: list[dict[str, str]] = []
    for asset in evidence.get("assets") or []:
        asset_id = str(asset.get("id"))
        if asset_id not in figure_title_map:
            asset_title_records.append({"id": asset_id, "text": norm(asset.get("title_en"))})
        caption_records.append({"id": asset_id, "text": norm(asset.get("caption_en"))})
        if asset.get("kind") == "table":
            table = asset.get("table") or {}
            for index, value in enumerate(table.get("headers") or []):
                table_records.append({"id": f"{asset_id}/h/{index}", "text": norm(value)})
            for row_index, row in enumerate(table.get("rows") or []):
                for column_index, value in enumerate(row):
                    table_records.append({"id": f"{asset_id}/r/{row_index}/{column_index}", "text": norm(value)})
    translated_titles = base.translate_records(
        asset_title_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-asset-titles-v5", context=paper["title_en"],
    ) if asset_title_records else {}
    translated_captions = base.translate_records(
        caption_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-captions-v5", context=paper["title_en"],
    ) if caption_records else {}
    translated_tables = base.translate_records(
        table_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-tables-v5", context=paper["title_en"],
    ) if table_records else {}

    source_figures = [asset for asset in evidence.get("assets") or [] if asset.get("kind") == "figure"]
    overview = generate_overview(
        evidence, plan, token=token, model=args.model, cache_dir=cache_dir, cache_prefix=paper_key,
    )
    studies = generate_grounded_studies(
        source_figures, evidence, plan, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key, paper_context=f"{paper['title_en']}。{overview['story']}",
    ) if source_figures else {}

    assets: list[dict[str, Any]] = []
    for source_asset in evidence.get("assets") or []:
        asset = base.clean_asset_for_schema(source_asset)
        asset_id = str(asset["id"])
        asset["title_zh"] = figure_title_map.get(asset_id) or translated_titles[asset_id]
        asset["caption_zh"] = translated_captions[asset_id]
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
            table["headers"] = [translated_tables[f"{asset_id}/h/{i}"] for i, _ in enumerate(table.get("headers") or [])]
            table["rows"] = [
                [translated_tables[f"{asset_id}/r/{ri}/{ci}"] for ci, _ in enumerate(row)]
                for ri, row in enumerate(table.get("rows") or [])
            ]
            asset["table"] = table
            asset["intro"] = generate_table_intro(
                source_asset, token=token, model=args.model, cache_dir=cache_dir, cache_prefix=paper_key,
            )
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
    manifest["terms"] = base.generate_terms(
        manifest, token=token, model=args.model, cache_dir=cache_dir, cache_prefix=paper_key + "-v5",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "generator": "v082-reader-manifest-v5-grounded-components",
        "paper_key": paper_key,
        "sections": len(sections),
        "paragraphs": len(paragraph_records),
        "assets": len(assets),
        "terms": len(manifest["terms"]),
        "references": len(manifest["references"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
