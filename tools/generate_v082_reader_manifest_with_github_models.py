#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

CJK = re.compile(r"[\u3400-\u9fff]")
JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_json_response(text: str) -> Any:
    text = text.strip()
    match = JSON_FENCE.search(text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        if not starts:
            raise
        start = min(starts)
        decoder = json.JSONDecoder()
        return decoder.raw_decode(text[start:])[0]


def call_model_json(
    *, token: str, model: str, system: str, user_payload: Any, cache_dir: Path,
    cache_name: str, max_tokens: int = 32768, retries: int = 8,
) -> Any:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key_material = json_text({"model": model, "system": system, "payload": user_payload})
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{cache_name}-{digest}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text("utf-8"))
    request_body = {
        "model": model,
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json_text(user_payload)},
        ],
    }
    data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    endpoint = os.environ.get("GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference/chat/completions")
    for attempt in range(retries):
        request = urllib.request.Request(
            endpoint,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "v082-reader-manifest-generator",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            result = parse_json_response(content)
            cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
            return result
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            if error.code not in {408, 409, 429, 500, 502, 503, 504} or attempt + 1 >= retries:
                raise RuntimeError(f"GitHub Models HTTP {error.code}: {body[:2000]}") from error
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(120, 10 * (attempt + 1))
            print(f"model request {cache_name} retry {attempt + 1}: HTTP {error.code}; sleeping {delay}s", flush=True)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt + 1 >= retries:
                raise
            delay = min(120, 10 * (attempt + 1))
            print(f"model request {cache_name} retry {attempt + 1}: {error}; sleeping {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError("model request exhausted retries")


def batches(records: list[dict[str, Any]], max_chars: int = 42000, max_items: int = 24) -> Iterable[list[dict[str, Any]]]:
    current: list[dict[str, Any]] = []
    chars = 0
    for record in records:
        size = len(json_text(record))
        if current and (chars + size > max_chars or len(current) >= max_items):
            yield current
            current = []
            chars = 0
        current.append(record)
        chars += size
    if current:
        yield current


def translate_records(records: list[dict[str, str]], *, token: str, model: str, cache_dir: Path, cache_prefix: str, context: str) -> dict[str, str]:
    translations: dict[str, str] = {}
    system = f"""You are producing a publication-grade bilingual biomedical paper reader. Translate every English item into accurate, fluent Simplified Chinese. Preserve all numbers, gene/protein names, abbreviations, statistical symbols, comparison directions, citation numbers and uncertainty. Use consistent terminology across items. Do not summarize, omit, add interpretation, or output English as the translation. Context: {context}\nReturn JSON only: {{\"items\":[{{\"id\":\"...\",\"zh\":\"...\"}}]}}. Include every input id exactly once."""
    for index, batch in enumerate(batches(records)):
        result = call_model_json(
            token=token, model=model, system=system,
            user_payload={"items": batch}, cache_dir=cache_dir,
            cache_name=f"{cache_prefix}-translate-{index:03d}",
        )
        items = result.get("items") if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise RuntimeError(f"translation response is not an item list: {type(items)}")
        returned = {str(item.get("id")): norm(item.get("zh")) for item in items if isinstance(item, dict)}
        expected = {str(item["id"]) for item in batch}
        missing = expected - returned.keys()
        if missing:
            raise RuntimeError(f"translation response missing ids: {sorted(missing)[:20]}")
        for item_id in expected:
            value = returned[item_id]
            if not CJK.search(value):
                raise RuntimeError(f"translation for {item_id} has no Chinese text")
            translations[item_id] = value
    return translations


def collect_inline_links(items: list[dict[str, Any]]) -> dict[str, Any]:
    links: dict[str, list[str]] = {"citation_ids": [], "figure_ids": []}
    for item in items:
        for field in links:
            for value in item.get(field) or []:
                if str(value) not in links[field]:
                    links[field].append(str(value))
    return {key: value for key, value in links.items() if value}


def clean_asset_for_schema(asset: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "kind", "group", "title_en", "title_zh", "intro", "image_src", "source_page",
        "image_format", "hires", "source_render", "caption_en", "caption_zh", "table", "study",
    }
    result = {key: value for key, value in asset.items() if key in allowed}
    if result.get("kind") == "table":
        result.pop("image_src", None)
        result.pop("image_format", None)
        result.pop("hires", None)
    return result


def title_map(plan: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    by_en = {norm(pair[0]).lower(): norm(pair[1]) for pair in plan.get("body_section_map") or [] if len(pair) >= 2}
    figure_zh = {str(item.get("id")): norm(item.get("title_zh")) for item in plan.get("main_figures") or []}
    return by_en, figure_zh


def make_metadata(paper: dict[str, Any], plan_paper: dict[str, Any]) -> list[dict[str, Any]]:
    values = [
        ("Journal", paper.get("journal")),
        ("Publisher", paper.get("publisher")),
        ("DOI", paper.get("doi")),
        ("Article type", paper.get("article_type")),
        ("Publication timeline", paper.get("publication_timeline")),
        ("Volume, issue and pages", paper.get("citation")),
        ("Journal scope", plan_paper.get("journal_scope")),
        ("领域定位", plan_paper.get("field_positioning")),
    ]
    return [{"label": label, "value": norm(value), "bold": label in {"Journal", "DOI"}} for label, value in values if norm(value)]


def generate_studies(
    figures: list[dict[str, Any]], plan: dict[str, Any], *, token: str, model: str,
    cache_dir: Path, cache_prefix: str, paper_context: str,
) -> dict[str, dict[str, Any]]:
    plan_figures = {str(item.get("id")): item for item in plan.get("main_figures") or []}
    requests: list[dict[str, Any]] = []
    for figure in figures:
        source_panels = []
        for panel in (figure.get("study") or {}).get("panels") or []:
            source_panels.append({
                "label": norm(panel.get("label")) or "整图",
                "source_text": norm(panel.get("source_text") or panel.get("explanation") or panel.get("title")),
            })
        if not source_panels:
            source_panels = [{"label": "整图", "source_text": norm(figure.get("caption_en"))}]
        requests.append({
            "id": figure.get("id"),
            "title_en": figure.get("title_en"),
            "caption_en": figure.get("caption_en"),
            "source_panels": source_panels,
            "reader_role": (plan_figures.get(str(figure.get("id"))) or {}).get("reader_role"),
            "panel_requirement": (plan_figures.get(str(figure.get("id"))) or {}).get("panel_requirement"),
        })
    system = f"""You are the scientific figure editor for a high-quality bilingual biomedical paper reader. Paper context: {paper_context}. For every figure, write reader-facing Simplified Chinese that is faithful to the source legend. The intro must state why the figure exists in the paper, not copy the legend. The overview must teach how to read the entire figure and be at least 90 Chinese characters. Preserve every supplied panel label in order; for each panel write a concise Chinese title and an explanation of at least 100 Chinese characters covering the object, axes/encoding where applicable, comparison, observed result, and evidence boundary. For an item labeled 整图, explain the complete unlabelled figure as one logical block. The conclusion must be at least 60 Chinese characters and connect to the next argument. The boundary must explicitly distinguish association, model prediction or in-vitro evidence from causal or clinical proof. Do not invent values. Return JSON only: {{\"items\":[{{\"id\":\"...\",\"intro\":\"...\",\"overview\":\"...\",\"panels\":[{{\"label\":\"A\",\"title\":\"...\",\"explanation\":\"...\"}}],\"conclusion\":\"...\",\"boundary\":\"...\"}}]}}."""
    output: dict[str, dict[str, Any]] = {}
    for index, batch in enumerate(batches(requests, max_chars=34000, max_items=4)):
        result = call_model_json(
            token=token, model=model, system=system,
            user_payload={"figures": batch}, cache_dir=cache_dir,
            cache_name=f"{cache_prefix}-studies-{index:03d}",
        )
        items = result.get("items") if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise RuntimeError("figure-study response is not an item list")
        for item in items:
            if not isinstance(item, dict):
                continue
            figure_id = str(item.get("id"))
            panels = item.get("panels") or []
            if not panels:
                raise RuntimeError(f"figure {figure_id} returned no panels")
            output[figure_id] = {
                "intro": norm(item.get("intro")),
                "overview": norm(item.get("overview")),
                "panels": [
                    {
                        "label": norm(panel.get("label")) or "整图",
                        "title": norm(panel.get("title")) or "图中信息",
                        "explanation": norm(panel.get("explanation")),
                    }
                    for panel in panels
                ],
                "conclusion": norm(item.get("conclusion")),
                "boundary": norm(item.get("boundary")),
            }
    missing = {str(item["id"]) for item in requests} - output.keys()
    if missing:
        raise RuntimeError(f"figure-study response missing figures: {sorted(missing)}")
    return output


def generate_terms(manifest: dict[str, Any], *, token: str, model: str, cache_dir: Path, cache_prefix: str) -> list[dict[str, Any]]:
    context = {
        "title": manifest["paper"]["title_en"],
        "sections": [section["title_en"] for section in manifest["sections"]],
        "figures": [asset["title_en"] for asset in manifest["assets"] if asset.get("kind") == "figure"],
        "sample_paragraphs": [
            norm("".join(item.get("text", "") for item in block.get("english") or []))
            for section in manifest["sections"]
            for block in section.get("blocks") or []
            if block.get("type") == "paragraph"
        ][:20],
    }
    system = """Select 18-28 genuinely important technical terms for this biomedical paper reader. Include methods, cell states, biomarkers and statistical concepts that a reader may need explained. Do not include generic words. Return JSON only: {\"terms\":[{\"id\":\"ascii-slug\",\"label\":\"English label\",\"definition_zh\":\"specific Chinese definition in this paper\",\"aliases\":[\"label\",\"abbreviation\"],\"category\":\"方法/细胞/分子/临床/统计\",\"level\":1}]} . IDs must be unique and match [A-Za-z0-9._-]+. Definitions must be accurate Chinese and at least 25 characters."""
    result = call_model_json(
        token=token, model=model, system=system, user_payload=context,
        cache_dir=cache_dir, cache_name=f"{cache_prefix}-terms", max_tokens=12000,
    )
    items = result.get("terms") if isinstance(result, dict) else result
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        term_id = re.sub(r"[^A-Za-z0-9._-]+", "-", norm(item.get("id"))).strip("-") or f"term-{index + 1}"
        if term_id in seen:
            continue
        seen.add(term_id)
        aliases = [norm(value) for value in item.get("aliases") or [] if norm(value)]
        label = norm(item.get("label"))
        if label and label not in aliases:
            aliases.insert(0, label)
        definition = norm(item.get("definition_zh"))
        if not label or not aliases or not CJK.search(definition):
            continue
        output.append({
            "id": term_id, "label": label, "definition_zh": definition,
            "aliases": aliases, "category": norm(item.get("category")) or "专业术语",
            "level": max(1, min(3, int(item.get("level") or 1))),
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a reader-ready V0.8.2 manifest with GitHub Models")
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
    paper["metadata"] = make_metadata(paper, plan_paper)

    section_map, figure_title_map = title_map(plan)
    section_title_records: list[dict[str, str]] = []
    for section in evidence.get("sections") or []:
        en = norm(section.get("title_en"))
        if en.lower() not in section_map:
            section_title_records.append({"id": str(section.get("id")), "text": en})
    translated_section_titles = translate_records(
        section_title_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-sections", context=paper["title_en"],
    ) if section_title_records else {}

    paragraph_records: list[dict[str, str]] = []
    for section in evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") == "paragraph":
                block_id = f"{section.get('id')}/{block.get('id')}"
                paragraph_records.append({
                    "id": block_id,
                    "text": norm("".join(item.get("text", "") for item in block.get("english") or [])),
                })
    paragraph_translations = translate_records(
        paragraph_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-body", context=paper["title_en"],
    )

    sections: list[dict[str, Any]] = []
    for source_section in evidence.get("sections") or []:
        section = {
            "id": source_section["id"],
            "title_en": source_section["title_en"],
            "title_zh": section_map.get(norm(source_section["title_en"]).lower()) or translated_section_titles[str(source_section["id"])],
            "level": int(source_section.get("level") or 2),
            "blocks": [],
        }
        for source_block in source_section.get("blocks") or []:
            if source_block.get("type") == "asset":
                section["blocks"].append({"type": "asset", "asset_id": source_block["asset_id"]})
                continue
            block_id = f"{source_section.get('id')}/{source_block.get('id')}"
            links = collect_inline_links(source_block.get("english") or [])
            chinese_inline = {"text": paragraph_translations[block_id], **links}
            block = {
                "type": "paragraph", "id": source_block["id"],
                "english": source_block["english"], "chinese": [chinese_inline],
                "source_fragments": source_block["source_fragments"],
            }
            for optional in ("source_pages", "tip", "term_note"):
                if optional in source_block:
                    block[optional] = source_block[optional]
            section["blocks"].append(block)
        sections.append(section)

    title_records: list[dict[str, str]] = []
    caption_records: list[dict[str, str]] = []
    table_records: list[dict[str, str]] = []
    for asset in evidence.get("assets") or []:
        asset_id = str(asset.get("id"))
        if asset_id not in figure_title_map:
            title_records.append({"id": asset_id, "text": norm(asset.get("title_en"))})
        caption_records.append({"id": asset_id, "text": norm(asset.get("caption_en"))})
        if asset.get("kind") == "table":
            table = asset.get("table") or {}
            for index, value in enumerate(table.get("headers") or []):
                table_records.append({"id": f"{asset_id}/h/{index}", "text": norm(value)})
            for row_index, row in enumerate(table.get("rows") or []):
                for column_index, value in enumerate(row):
                    table_records.append({"id": f"{asset_id}/r/{row_index}/{column_index}", "text": norm(value)})
    translated_titles = translate_records(
        title_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-asset-titles", context=paper["title_en"],
    ) if title_records else {}
    translated_captions = translate_records(
        caption_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-captions", context=paper["title_en"],
    ) if caption_records else {}
    translated_tables = translate_records(
        table_records, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key + "-tables", context=paper["title_en"],
    ) if table_records else {}

    source_figures = [asset for asset in evidence.get("assets") or [] if asset.get("kind") == "figure"]
    studies = generate_studies(
        source_figures, plan, token=token, model=args.model, cache_dir=cache_dir,
        cache_prefix=paper_key, paper_context=f"{paper['title_en']}。{(plan.get('overview') or {}).get('story', '')}",
    ) if source_figures else {}

    assets: list[dict[str, Any]] = []
    for source_asset in evidence.get("assets") or []:
        asset = clean_asset_for_schema(source_asset)
        asset_id = str(asset["id"])
        asset["title_zh"] = figure_title_map.get(asset_id) or translated_titles[asset_id]
        asset["caption_zh"] = translated_captions[asset_id]
        if asset.get("kind") == "figure":
            study = studies[asset_id]
            asset["intro"] = study["intro"]
            asset["study"] = {
                "overview": study["overview"], "panels": study["panels"],
                "conclusion": study["conclusion"], "boundary": study["boundary"],
            }
        else:
            asset["intro"] = f"该表汇总{asset['title_zh']}，用于集中查阅正文分析所依赖的变量、标志物或结果。"
            table = asset.get("table") or {}
            table["headers"] = [translated_tables[f"{asset_id}/h/{index}"] for index, _ in enumerate(table.get("headers") or [])]
            table["rows"] = [
                [translated_tables[f"{asset_id}/r/{row_index}/{column_index}"] for column_index, _ in enumerate(row)]
                for row_index, row in enumerate(table.get("rows") or [])
            ]
            asset["table"] = table
        assets.append(asset)

    overview_plan = plan.get("overview") or {}
    overview = {
        "qa": overview_plan["qa"], "method_heading": "方法流程概括",
        "method": overview_plan.get("method", ""), "story_label": "整体结论",
        "story": overview_plan.get("story", ""),
        "scope_note": "正文与图注基于来源PDF逐段保留；中文翻译统一术语，图表精读区分来源结果、计算推断和临床证据。",
    }
    manifest: dict[str, Any] = {
        "schema_version": "0.8.2", "paper": paper, "overview": overview,
        "sections": sections, "assets": assets, "terms": [],
        "references": evidence.get("references") or [],
    }
    manifest["terms"] = generate_terms(
        manifest, token=token, model=args.model, cache_dir=cache_dir, cache_prefix=paper_key,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "paper_key": paper_key, "model": args.model, "sections": len(sections),
        "paragraphs": len(paragraph_records), "assets": len(assets), "terms": len(manifest["terms"]),
        "references": len(manifest["references"]), "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
