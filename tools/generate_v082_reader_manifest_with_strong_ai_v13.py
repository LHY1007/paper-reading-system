#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

import generate_v082_reader_manifest_with_github_models_v7 as legacy

base = legacy.base
CJK = re.compile(r"[\u3400-\u9fff]")
NUMBER = re.compile(r"(?<![A-Za-z])(?:\d+(?:[.,]\d+)?(?:\s*[×x]\s*10[−–-]?\d+)?%?)")
ABBREVIATION = re.compile(r"\b[A-Z][A-Z0-9α-ωΑ-Ω./+-]{1,}\b")
DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
TABLE_LIKE = re.compile(r"^(?:Extended Data |Supplementary )?Table\b", re.I)
GENERIC_FIGURE = re.compile(
    r"该部分属于图|应结合其标注|连接起来|图中信息|子图\s*[A-Z0-9]+\s*的比较与结果|"
    r"把正文中的关键比较组织为|按照.*顺序对照完整图注"
)
FIXED_QUESTIONS = [
    "研究解决什么问题？",
    "核心数据是什么？",
    "模型或分析的输入与输出是什么？",
    "主要生物学发现是什么？",
    "主要临床结果是什么？",
    "最重要的限制是什么？",
]
REVIEW_LOG: dict[str, Any] = {
    "version": "v082-strong-ai-component-review-1",
    "generator": "strong-ai-v13",
    "models": {},
    "translation": [],
    "figures": [],
    "tables": [],
    "overview": {},
    "terms": {},
    "references": {},
    "errors": [],
}


def norm(value: Any) -> str:
    return base.norm(value)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def stable_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def model_settings() -> tuple[str, str, str]:
    primary = os.environ.get("V082_PRIMARY_MODEL", "openai/gpt-5")
    reviewer = os.environ.get("V082_REVIEW_MODEL", primary)
    vision = os.environ.get("V082_VISION_MODEL", primary)
    REVIEW_LOG["models"] = {"primary": primary, "reviewer": reviewer, "vision": vision}
    return primary, reviewer, vision


def validate_translation(source: str, chinese: str) -> list[str]:
    issues: list[str] = []
    if source and not CJK.search(chinese):
        issues.append("missing Chinese")
    source_numbers = Counter(token.replace(" ", "") for token in NUMBER.findall(source))
    target_numbers = Counter(token.replace(" ", "") for token in NUMBER.findall(chinese))
    for token, count in source_numbers.items():
        if target_numbers[token] < count:
            issues.append(f"number not preserved: {token}")
    source_abbreviations = {
        token for token in ABBREVIATION.findall(source)
        if len(token) >= 2 and not token.isdigit()
    }
    missing_abbreviations = sorted(token for token in source_abbreviations if token not in chinese)
    if missing_abbreviations:
        issues.append("abbreviations not preserved: " + ", ".join(missing_abbreviations[:12]))
    if len(chinese) < max(4, int(len(source) * 0.10)):
        issues.append("translation implausibly short")
    return issues


def translate_one(
    source: str,
    *,
    item_id: str,
    paper_title: str,
    token: str,
    primary_model: str,
    reviewer_model: str,
    cache_dir: Path,
) -> str:
    source = norm(source)
    if not source:
        return ""
    system = f"""你是生物医学论文的专业中英翻译编辑。论文题目：{paper_title}。
任务类型是纯客观翻译，不是解释。逐句完整翻译给定英文，保持原段落信息量、逻辑关系和不确定性。
必须保留所有数字、单位、P值、置信区间、基因/蛋白符号、细胞状态、队列名称、缩写、图表编号和参考文献编号。
不得总结、删节、补充背景、改写结论强度或加入评价。返回严格JSON：
{{"zh":"完整中文译文"}}"""
    draft = base.call_model_json(
        token=token,
        model=primary_model,
        system=system,
        user_payload={"id": item_id, "source_en": source},
        cache_dir=cache_dir,
        cache_name=f"translation-draft-{stable_name(item_id + source)}",
        max_tokens=12000,
    )
    draft_zh = norm((draft or {}).get("zh"))
    review_system = f"""你是第二位独立的生物医学翻译审校者。论文题目：{paper_title}。
对照英文原文逐项检查候选中文，重点检查遗漏、误译、方向反转、比较对象、否定词、数值、统计量、基因蛋白符号、缩写和引用编号。
这仍然是纯客观翻译，禁止添加解释。直接给出经过修订的最终译文，并列出发现的问题。
返回严格JSON：{{"passed":true,"issues":[],"zh_final":"..."}}。passed只表示修订后的zh_final可用。"""
    reviewed = base.call_model_json(
        token=token,
        model=reviewer_model,
        system=review_system,
        user_payload={"id": item_id, "source_en": source, "candidate_zh": draft_zh},
        cache_dir=cache_dir,
        cache_name=f"translation-review-{stable_name(item_id + source)}",
        max_tokens=12000,
    )
    final_zh = norm((reviewed or {}).get("zh_final"))
    issues = [norm(value) for value in (reviewed or {}).get("issues", []) if norm(value)]
    local_issues = validate_translation(source, final_zh)
    if local_issues:
        repair_system = review_system + "\n本次必须修复下面列出的机械一致性问题，不能省略原文中的任何内容。"
        repaired = base.call_model_json(
            token=token,
            model=reviewer_model,
            system=repair_system,
            user_payload={
                "id": item_id,
                "source_en": source,
                "candidate_zh": final_zh,
                "required_fixes": local_issues,
            },
            cache_dir=cache_dir,
            cache_name=f"translation-repair-{stable_name(item_id + source)}",
            max_tokens=12000,
        )
        final_zh = norm((repaired or {}).get("zh_final"))
        issues.extend(local_issues)
        local_issues = validate_translation(source, final_zh)
    passed = bool(final_zh) and not local_issues
    REVIEW_LOG["translation"].append({
        "id": item_id,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "draft_model": primary_model,
        "review_model": reviewer_model,
        "review_issues": issues,
        "local_issues": local_issues,
        "passed": passed,
    })
    if not passed:
        raise RuntimeError(f"translation review failed for {item_id}: {local_issues}")
    return final_zh


def sequential_translate_all(
    records: list[dict[str, str]],
    *,
    token: str,
    model: str,
    cache_dir: Path,
    paper_title: str,
    cache_prefix: str,
) -> dict[str, str]:
    del model
    primary_model, reviewer_model, _ = model_settings()
    output: dict[str, str] = {}
    strong_cache = cache_dir / "strong-ai-v13" / cache_prefix
    total = len(records)
    for index, record in enumerate(records, start=1):
        item_id = str(record["id"])
        output[item_id] = translate_one(
            norm(record.get("text")),
            item_id=item_id,
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            reviewer_model=reviewer_model,
            cache_dir=strong_cache,
        )
        print(json.dumps({
            "component": "translation",
            "completed": index,
            "total": total,
            "id": item_id,
        }, ensure_ascii=False), flush=True)
    return output


def prepare_image_data_uri(image_src: str | None, max_side: int = 2400) -> str | None:
    value = str(image_src or "")
    if not value.startswith("data:image/") or "," not in value:
        return None
    header, payload = value.split(",", 1)
    try:
        raw = base64.b64decode(payload) if ";base64" in header else urllib.parse.unquote_to_bytes(payload)
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            width, height = image.size
            scale = min(1.0, max_side / max(width, height))
            if scale < 1.0:
                image = image.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        return value


def call_multimodal_json(
    *,
    token: str,
    model: str,
    system: str,
    payload: Any,
    image_src: str | None,
    cache_dir: Path,
    cache_name: str,
    max_tokens: int = 24000,
    retries: int = 8,
) -> Any:
    cache_dir.mkdir(parents=True, exist_ok=True)
    image_src = prepare_image_data_uri(image_src)
    key = json_text({"model": model, "system": system, "payload": payload, "image_sha256": hashlib.sha256((image_src or '').encode('utf-8')).hexdigest()})
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{cache_name}-{digest}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text("utf-8"))
    content: list[dict[str, Any]] = [{"type": "text", "text": json_text(payload)}]
    if image_src and str(image_src).startswith("data:image/"):
        content.append({"type": "image_url", "image_url": {"url": image_src, "detail": "high"}})
    request_body = {
        "model": model,
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }
    data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    endpoint = os.environ.get(
        "GITHUB_MODELS_ENDPOINT",
        "https://models.github.ai/inference/chat/completions",
    )
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
                "User-Agent": "v082-strong-ai-component-review",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            content_text = response_payload["choices"][0]["message"]["content"]
            result = base.parse_json_response(content_text)
            cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
            return result
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            if error.code not in {408, 409, 429, 500, 502, 503, 504} or attempt + 1 >= retries:
                raise RuntimeError(f"GitHub Models HTTP {error.code}: {body[:2000]}") from error
            delay = min(180, 15 * (attempt + 1))
            retry_after = error.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(delay, int(retry_after))
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt + 1 >= retries:
                raise
            time.sleep(min(180, 15 * (attempt + 1)))
    raise RuntimeError("multimodal model request exhausted retries")


def figure_payload(
    figure: dict[str, Any],
    evidence: dict[str, Any],
    plan: dict[str, Any],
    translations: dict[str, str],
) -> dict[str, Any]:
    figure_id = str(figure.get("id"))
    related = legacy.related_body_by_asset(evidence)
    plan_figures = {str(item.get("id")): item for item in plan.get("main_figures") or []}
    source_panels = legacy.panel_source_records(figure)
    return {
        "id": figure_id,
        "title_en": norm(figure.get("title_en")),
        "title_zh": translations.get(f"asset-title/{figure_id}", ""),
        "caption_en": norm(figure.get("caption_en")),
        "caption_zh": translations.get(f"asset-caption/{figure_id}", ""),
        "source_panels": source_panels,
        "expected_panel_labels": [item["label"] for item in source_panels],
        "nearby_body_evidence": (related.get(figure_id) or [])[:10],
        "reader_role": norm((plan_figures.get(figure_id) or {}).get("reader_role")),
        "panel_requirement": norm((plan_figures.get(figure_id) or {}).get("panel_requirement")),
    }


def normalize_study(item: dict[str, Any], expected_labels: list[str]) -> dict[str, Any]:
    panels = item.get("panels") or []
    by_label = {
        norm(panel.get("label")) or "整图": panel
        for panel in panels
        if isinstance(panel, dict)
    }
    normalized_panels = []
    for label in expected_labels:
        panel = by_label.get(label)
        if not panel:
            raise RuntimeError(f"missing panel {label}")
        normalized_panels.append({
            "label": label,
            "title": norm(panel.get("title")),
            "explanation": norm(panel.get("explanation")),
        })
    return {
        "intro": norm(item.get("intro")),
        "overview": norm(item.get("overview")),
        "panels": normalized_panels,
        "conclusion": norm(item.get("conclusion")),
        "boundary": norm(item.get("boundary")),
    }


def study_issues(study: dict[str, Any], labels: list[str]) -> list[str]:
    issues: list[str] = []
    if [item.get("label") for item in study.get("panels") or []] != labels:
        issues.append("panel label/order mismatch")
    for index, panel in enumerate(study.get("panels") or []):
        text = norm(panel.get("explanation"))
        if len(text) < 70:
            issues.append(f"panel {index} explanation too short")
        if GENERIC_FIGURE.search(text):
            issues.append(f"panel {index} contains generic filler")
        if not norm(panel.get("title")):
            issues.append(f"panel {index} title missing")
    for field, minimum in (("intro", 35), ("overview", 70), ("conclusion", 45), ("boundary", 30)):
        if len(norm(study.get(field))) < minimum:
            issues.append(f"{field} too short")
    return issues


def generate_figure_studies_strong(
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
    primary_model, reviewer_model, vision_model = model_settings()
    output: dict[str, dict[str, Any]] = {}
    strong_cache = cache_dir / "strong-ai-v13" / cache_prefix
    total = len(figures)
    for index, figure in enumerate(figures, start=1):
        payload = figure_payload(figure, evidence, plan, translations)
        figure_id = payload["id"]
        image_src = norm(figure.get("image_src"))
        draft_system = f"""你是生物医学论文图表精读编辑，论文题目为：{paper_title}。
任务类型是有证据约束的解释，不是翻译。你必须同时查看原图、英文完整图注、图注面板证据和正文中明确引用该图的段落。
逐个子图解释：研究对象与数据、横纵轴/颜色/形状/分组、比较或模型输出、直接可见结果、该结果在全文论证中的作用。
必须区分直接测量、统计关联、计算推断、模型预测、实验干预和临床证据。不得把关联写成因果，不得编造图中不存在的数值或面板。
不得使用通用套话填充。整体论文论证：{overview_story}
返回严格JSON：
{{"id":"...","intro":"...","overview":"...","panels":[{{"label":"A","title":"...","explanation":"..."}}],"conclusion":"...","boundary":"..."}}。"""
        draft = call_multimodal_json(
            token=token,
            model=vision_model,
            system=draft_system,
            payload=payload,
            image_src=image_src or None,
            cache_dir=strong_cache,
            cache_name=f"figure-draft-{figure_id}",
            max_tokens=24000,
        )
        review_system = f"""你是第二位独立的生物医学图表审稿人。论文题目：{paper_title}。
对照原图、图注、面板证据和相关正文，逐项审查候选图解。核对面板标签顺序、坐标和图例、组别、样本量、数值、趋势方向、统计显著性、模型输入输出和证据边界。
删除任何模板化套话。直接输出修订后的最终图解，不要只给意见。
返回严格JSON：
{{"passed":true,"issues":[],"final":{{"id":"...","intro":"...","overview":"...","panels":[{{"label":"A","title":"...","explanation":"..."}}],"conclusion":"...","boundary":"..."}}}}。"""
        reviewed = call_multimodal_json(
            token=token,
            model=reviewer_model,
            system=review_system,
            payload={"source": payload, "candidate": draft},
            image_src=image_src or None,
            cache_dir=strong_cache,
            cache_name=f"figure-review-{figure_id}",
            max_tokens=24000,
        )
        final_raw = (reviewed or {}).get("final") or {}
        try:
            study = normalize_study(final_raw, payload["expected_panel_labels"])
            local_issues = study_issues(study, payload["expected_panel_labels"])
        except Exception as exc:
            study = {}
            local_issues = [str(exc)]
        review_issues = [norm(value) for value in (reviewed or {}).get("issues", []) if norm(value)]
        if local_issues:
            correction_system = review_system + "\n本次必须修复required_fixes，并保持每个面板标签一一对应。"
            corrected = call_multimodal_json(
                token=token,
                model=reviewer_model,
                system=correction_system,
                payload={"source": payload, "candidate": final_raw, "required_fixes": local_issues},
                image_src=image_src or None,
                cache_dir=strong_cache,
                cache_name=f"figure-repair-{figure_id}",
                max_tokens=24000,
            )
            corrected_raw = (corrected or {}).get("final") or corrected
            study = normalize_study(corrected_raw, payload["expected_panel_labels"])
            local_issues = study_issues(study, payload["expected_panel_labels"])
        passed = not local_issues
        REVIEW_LOG["figures"].append({
            "id": figure_id,
            "source_image_present": bool(image_src),
            "panel_labels": payload["expected_panel_labels"],
            "draft_model": vision_model,
            "review_model": reviewer_model,
            "review_issues": review_issues,
            "local_issues": local_issues,
            "passed": passed,
        })
        if not passed:
            raise RuntimeError(f"figure review failed for {figure_id}: {local_issues}")
        output[figure_id] = study
        print(json.dumps({
            "component": "figure",
            "completed": index,
            "total": total,
            "id": figure_id,
        }, ensure_ascii=False), flush=True)
    return output


def table_like_asset(asset: dict[str, Any]) -> bool:
    return bool(TABLE_LIKE.match(norm(asset.get("title_en"))) or TABLE_LIKE.match(norm(asset.get("id")).replace("-", " ")))


def transcribe_table(
    asset: dict[str, Any],
    *,
    paper_title: str,
    token: str,
    primary_model: str,
    reviewer_model: str,
    vision_model: str,
    cache_dir: Path,
) -> dict[str, Any]:
    asset_id = str(asset.get("id"))
    source = {
        "id": asset_id,
        "title_en": norm(asset.get("title_en")),
        "caption_en": norm(asset.get("caption_en")),
        "source_page": asset.get("source_page"),
    }
    image_src = norm(asset.get("image_src"))
    system = f"""你是论文表格转录编辑。论文题目：{paper_title}。
查看原始表格图像，只转录图中实际存在的表头、行名、数值、均值±误差、箭头和脚注。保持英文原样，不翻译，不推断缺失值，不合并或拆分统计列。
返回严格JSON：
{{"id":"...","headers":["..."],"rows":[["..."]],"footnotes":["..."],"reader_intro_zh":"说明本表比较对象与指标的中文短段落"}}。每行列数必须与headers一致。"""
    draft = call_multimodal_json(
        token=token,
        model=vision_model,
        system=system,
        payload=source,
        image_src=image_src or None,
        cache_dir=cache_dir,
        cache_name=f"table-draft-{asset_id}",
        max_tokens=20000,
    )
    review_system = f"""你是第二位独立表格复核者。论文题目：{paper_title}。
逐格对照原始图像检查候选转录，修正表头、行列错位、数字、小数点、±、上下箭头和脚注。禁止补写图中没有的内容。
返回严格JSON：
{{"passed":true,"issues":[],"final":{{"id":"...","headers":["..."],"rows":[["..."]],"footnotes":["..."],"reader_intro_zh":"..."}}}}。"""
    reviewed = call_multimodal_json(
        token=token,
        model=reviewer_model,
        system=review_system,
        payload={"source": source, "candidate": draft},
        image_src=image_src or None,
        cache_dir=cache_dir,
        cache_name=f"table-review-{asset_id}",
        max_tokens=20000,
    )
    final = (reviewed or {}).get("final") or {}
    headers = [norm(value) for value in final.get("headers") or []]
    rows = [[norm(value) for value in row] for row in final.get("rows") or []]
    issues = [norm(value) for value in (reviewed or {}).get("issues", []) if norm(value)]
    local_issues: list[str] = []
    if len(headers) < 2:
        local_issues.append("fewer than two headers")
    if not rows:
        local_issues.append("no rows")
    for row_index, row in enumerate(rows):
        if len(row) != len(headers):
            local_issues.append(f"row {row_index} has {len(row)} cells; expected {len(headers)}")
    passed = not local_issues
    REVIEW_LOG["tables"].append({
        "id": asset_id,
        "source_image_present": bool(image_src),
        "headers": len(headers),
        "rows": len(rows),
        "review_issues": issues,
        "local_issues": local_issues,
        "passed": passed,
    })
    if not passed:
        raise RuntimeError(f"table transcription failed for {asset_id}: {local_issues}")
    return {
        "headers": headers,
        "rows": rows,
        "footnotes": [norm(value) for value in final.get("footnotes") or [] if norm(value)],
        "intro": norm(final.get("reader_intro_zh")),
    }


def is_textual_cell(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value)) and not bool(re.fullmatch(r"[\d\s.,±%()/<>=−–—+-]+", value))


def bilingualize_table(
    table: dict[str, Any],
    *,
    asset_id: str,
    paper_title: str,
    token: str,
    primary_model: str,
    reviewer_model: str,
    cache_dir: Path,
) -> dict[str, Any]:
    def convert(value: str, path: str) -> str:
        value = norm(value)
        if not value or not is_textual_cell(value):
            return value
        zh = translate_one(
            value,
            item_id=f"table/{asset_id}/{path}",
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            reviewer_model=reviewer_model,
            cache_dir=cache_dir,
        )
        return f"{value}（{zh}）"
    headers = [convert(value, f"h/{index}") for index, value in enumerate(table["headers"])]
    rows = [
        [convert(value, f"r/{row_index}/{column_index}") for column_index, value in enumerate(row)]
        for row_index, row in enumerate(table["rows"])
    ]
    return {"headers": headers, "rows": rows}


def evidence_excerpt(evidence: dict[str, Any], max_chars: int = 85000) -> dict[str, Any]:
    sections = []
    used = 0
    for section in evidence.get("sections") or []:
        paragraphs = []
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            text = legacy.paragraph_text(block)
            if not text:
                continue
            if used + len(text) > max_chars:
                break
            paragraphs.append(text)
            used += len(text)
            if len(paragraphs) >= 4:
                break
        sections.append({"title": norm(section.get("title_en")), "paragraphs": paragraphs})
        if used >= max_chars:
            break
    return {
        "paper": evidence.get("paper") or {},
        "sections": sections,
        "assets": [
            {"id": item.get("id"), "title": item.get("title_en"), "caption": item.get("caption_en")}
            for item in (evidence.get("assets") or [])[:24]
        ],
    }


def review_overview(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    plan: dict[str, Any],
    *,
    token: str,
    primary_model: str,
    reviewer_model: str,
    cache_dir: Path,
) -> dict[str, Any]:
    excerpt = evidence_excerpt(evidence)
    system = """你是论文阅读器的一页概览编辑。这一部分允许基于论文证据进行解释性概括，但不得脱离证据。
六个问题必须严格保持给定顺序。核心数据要写明队列、样本量、数据类型及训练/验证关系；输入输出要操作性明确；生物学发现与临床结果必须分开；限制必须来自研究设计。
方法流程用5至9个阶段，以→连接。返回严格JSON：
{"qa":[{"question":"...","answer":"..."}],"method_heading":"方法流程概括","method":"...→...","story_label":"整体结论","story":"...","scope_note":"..."}。"""
    draft = base.call_model_json(
        token=token,
        model=primary_model,
        system=system,
        user_payload={
            "fixed_questions": FIXED_QUESTIONS,
            "approved_plan": plan.get("overview") or {},
            "source_excerpt": excerpt,
        },
        cache_dir=cache_dir,
        cache_name="overview-draft",
        max_tokens=16000,
    )
    review_system = """你是第二位独立的论文概览审校者。逐条对照来源摘录和论文级计划，删除无来源数字、因果夸大和生物学/临床结果混写，补足遗漏的队列关系与限制。固定问题及顺序不能改变。
直接返回修订后的最终概览：
{"passed":true,"issues":[],"final":{"qa":[...],"method_heading":"方法流程概括","method":"...","story_label":"整体结论","story":"...","scope_note":"..."}}。"""
    reviewed = base.call_model_json(
        token=token,
        model=reviewer_model,
        system=review_system,
        user_payload={"source_excerpt": excerpt, "approved_plan": plan.get("overview") or {}, "candidate": draft},
        cache_dir=cache_dir,
        cache_name="overview-review",
        max_tokens=16000,
    )
    final = (reviewed or {}).get("final") or {}
    issues: list[str] = []
    qa = final.get("qa") or []
    if [norm(item.get("question")) for item in qa if isinstance(item, dict)] != FIXED_QUESTIONS:
        issues.append("fixed question order mismatch")
    if len(qa) != 6:
        issues.append("overview does not contain six answers")
    if not (4 <= norm(final.get("method")).count("→") <= 8):
        issues.append("method flow does not contain 5-9 stages")
    if any(len(norm(item.get("answer"))) < 35 for item in qa if isinstance(item, dict)):
        issues.append("overview answer too short")
    REVIEW_LOG["overview"] = {
        "review_issues": [norm(value) for value in (reviewed or {}).get("issues", []) if norm(value)],
        "local_issues": issues,
        "passed": not issues,
    }
    if issues:
        raise RuntimeError(f"overview review failed: {issues}")
    return final


def section_terms(
    manifest: dict[str, Any],
    *,
    token: str,
    primary_model: str,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, section in enumerate(manifest.get("sections") or []):
        english = [
            norm("".join(item.get("text", "") for item in block.get("english") or []))
            for block in section.get("blocks") or []
            if block.get("type") == "paragraph"
        ]
        source = " ".join(english)
        if not source:
            continue
        system = """从当前论文小节中提取真正需要解释的专业术语。只选在原文中实际出现、且对理解方法、细胞状态、分子标志物、临床终点或统计分析重要的术语。不要选普通词。
返回严格JSON：{"terms":[{"label":"原文术语","aliases":["原文别名或缩写"],"category":"方法/细胞/分子/临床/统计","definition_zh":"结合本论文语境的准确中文定义"}]}。"""
        result = base.call_model_json(
            token=token,
            model=primary_model,
            system=system,
            user_payload={
                "section_title": section.get("title_en"),
                "source_en": source[:26000],
            },
            cache_dir=cache_dir,
            cache_name=f"terms-section-{index:03d}",
            max_tokens=8000,
        )
        for item in (result or {}).get("terms", []):
            if isinstance(item, dict):
                candidates.append(item)
    return candidates


def review_terms(
    manifest: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    token: str,
    reviewer_model: str,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    source_text = " ".join(
        norm("".join(item.get("text", "") for item in block.get("english") or []))
        for section in manifest.get("sections") or []
        for block in section.get("blocks") or []
        if block.get("type") == "paragraph"
    )
    system = """你是生物医学论文术语表审校者。合并候选术语，保留18至35个最重要项目。label和aliases必须在论文英文原文中实际出现；定义必须针对本论文语境，不能是空泛百科句。基因和蛋白符号不翻译，但定义其在本文中的角色。
返回严格JSON：{"terms":[{"id":"ASCII-slug","label":"...","aliases":["..."],"category":"方法/细胞/分子/临床/统计","level":1,"definition_zh":"..."}]}。"""
    reviewed = base.call_model_json(
        token=token,
        model=reviewer_model,
        system=system,
        user_payload={"paper_title": manifest["paper"]["title_en"], "candidates": candidates},
        cache_dir=cache_dir,
        cache_name="terms-review",
        max_tokens=14000,
    )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    rejected = 0
    for index, item in enumerate((reviewed or {}).get("terms", [])):
        if not isinstance(item, dict):
            continue
        label = norm(item.get("label"))
        aliases = [norm(value) for value in item.get("aliases") or [] if norm(value)]
        if label and label not in aliases:
            aliases.insert(0, label)
        if not label or not aliases or not any(alias.lower() in source_text.lower() for alias in aliases):
            rejected += 1
            continue
        definition = norm(item.get("definition_zh"))
        if not CJK.search(definition) or len(definition) < 25:
            rejected += 1
            continue
        term_id = re.sub(r"[^A-Za-z0-9._-]+", "-", norm(item.get("id"))).strip("-")
        if not term_id:
            term_id = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or f"term-{index+1}"
        if term_id in seen:
            continue
        seen.add(term_id)
        output.append({
            "id": term_id,
            "label": label,
            "definition_zh": definition,
            "aliases": aliases,
            "category": norm(item.get("category")) or "专业术语",
            "level": max(1, min(3, int(item.get("level") or 1))),
        })
    issues = []
    if len(output) < 18:
        issues.append(f"only {len(output)} source-grounded terms")
    REVIEW_LOG["terms"] = {
        "candidate_count": len(candidates),
        "accepted_count": len(output),
        "rejected_count": rejected,
        "local_issues": issues,
        "passed": not issues,
    }
    if issues:
        raise RuntimeError(f"term review failed: {issues}")
    return output


def reference_cache_path(cache_dir: Path, text: str) -> Path:
    return cache_dir / "references" / f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}.json"


def title_overlap(reference: str, title: str) -> float:
    stop = {"the", "and", "of", "in", "to", "a", "an", "for", "with", "on", "by", "from"}
    left = {token.lower() for token in re.findall(r"[A-Za-z0-9-]{3,}", reference) if token.lower() not in stop}
    right = {token.lower() for token in re.findall(r"[A-Za-z0-9-]{3,}", title) if token.lower() not in stop}
    return len(left & right) / max(1, len(right))


def resolve_reference(text: str, cache_dir: Path) -> dict[str, Any]:
    text = norm(text)
    path = reference_cache_path(cache_dir, text)
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    doi_match = DOI.search(text)
    if doi_match:
        doi = doi_match.group(0).rstrip(".,;)")
        result = {"url": f"https://doi.org/{doi}", "method": "source-doi", "confidence": 1.0}
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
        return result
    params = urllib.parse.urlencode({
        "query.bibliographic": text,
        "rows": 1,
        "select": "DOI,title,published,URL,score",
    })
    request = urllib.request.Request(
        f"https://api.crossref.org/works?{params}",
        headers={"User-Agent": "V082PaperReader/1.0 (mailto:repository-maintainer@example.com)"},
    )
    result: dict[str, Any] = {"url": "", "method": "unresolved", "confidence": 0.0}
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = ((payload.get("message") or {}).get("items") or [])
        if items:
            item = items[0]
            title = norm(" ".join(item.get("title") or []))
            overlap = title_overlap(text, title)
            source_year = re.search(r"\b(19|20)\d{2}\b", text)
            published = item.get("published") or {}
            date_parts = published.get("date-parts") or []
            target_year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""
            year_ok = not source_year or not target_year or source_year.group(0) == target_year
            if overlap >= 0.52 and year_ok and norm(item.get("DOI")):
                doi = norm(item.get("DOI"))
                result = {
                    "url": f"https://doi.org/{doi}",
                    "method": "crossref-bibliographic",
                    "confidence": round(overlap, 3),
                    "matched_title": title,
                }
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    time.sleep(float(os.environ.get("V082_REFERENCE_INTERVAL_SECONDS", "0.08")))
    return result


def enrich_references(manifest: dict[str, Any], cache_dir: Path) -> None:
    references = manifest.get("references") or []
    resolved = 0
    methods: Counter[str] = Counter()
    for index, reference in enumerate(references, start=1):
        result = resolve_reference(norm(reference.get("text")), cache_dir)
        if norm(result.get("url")):
            reference["url"] = result["url"]
            resolved += 1
        methods[str(result.get("method"))] += 1
        print(json.dumps({
            "component": "reference-link",
            "completed": index,
            "total": len(references),
            "resolved": bool(result.get("url")),
        }, ensure_ascii=False), flush=True)
    ratio = resolved / max(1, len(references))
    REVIEW_LOG["references"] = {
        "total": len(references),
        "resolved": resolved,
        "resolution_ratio": round(ratio, 4),
        "methods": dict(methods),
        "passed": ratio >= 0.65,
    }
    if ratio < 0.65:
        raise RuntimeError(f"reference link resolution below 65%: {resolved}/{len(references)}")


def postprocess_manifest(
    evidence_path: Path,
    plan_path: Path,
    output_path: Path,
    cache_dir: Path,
) -> None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")
    if not token:
        raise RuntimeError("GitHub Models token is required")
    primary_model, reviewer_model, vision_model = model_settings()
    evidence = json.loads(evidence_path.read_text("utf-8"))
    plan = json.loads(plan_path.read_text("utf-8"))
    manifest = json.loads(output_path.read_text("utf-8"))
    paper_title = norm(manifest["paper"]["title_en"])
    strong_cache = cache_dir / norm(manifest["paper"]["key"]) / "strong-ai-v13"

    manifest["overview"] = review_overview(
        manifest,
        evidence,
        plan,
        token=token,
        primary_model=primary_model,
        reviewer_model=reviewer_model,
        cache_dir=strong_cache,
    )

    evidence_assets = {str(item.get("id")): item for item in evidence.get("assets") or []}
    for index, asset in enumerate(manifest.get("assets") or []):
        source = evidence_assets.get(str(asset.get("id"))) or {}
        if source.get("kind") != "figure" or not table_like_asset(source):
            continue
        transcribed = transcribe_table(
            source,
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            reviewer_model=reviewer_model,
            vision_model=vision_model,
            cache_dir=strong_cache,
        )
        table = bilingualize_table(
            transcribed,
            asset_id=str(asset.get("id")),
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            reviewer_model=reviewer_model,
            cache_dir=strong_cache,
        )
        asset["kind"] = "table"
        asset["table"] = table
        asset["intro"] = transcribed["intro"] or f"{asset.get('title_zh')}逐项列出原论文表格中的比较对象、指标与结果。"
        asset.pop("study", None)
        asset["source_render"] = (
            "ai-verified-structured-table-transcription-v1;"
            f"source-page={source.get('source_page')};source-image-retained"
        )
        if source.get("image_src"):
            asset["image_src"] = source["image_src"]
            asset["image_format"] = source.get("image_format", "png")
            asset["hires"] = bool(source.get("hires"))
        manifest["assets"][index] = asset

    candidates = section_terms(
        manifest,
        token=token,
        primary_model=primary_model,
        cache_dir=strong_cache,
    )
    manifest["terms"] = review_terms(
        manifest,
        candidates,
        token=token,
        reviewer_model=reviewer_model,
        cache_dir=strong_cache,
    )
    enrich_references(manifest, strong_cache)

    REVIEW_LOG["paper_key"] = norm(manifest["paper"]["key"])
    REVIEW_LOG["counts"] = {
        "paragraphs": sum(
            1 for section in manifest.get("sections") or []
            for block in section.get("blocks") or []
            if block.get("type") == "paragraph"
        ),
        "assets": len(manifest.get("assets") or []),
        "terms": len(manifest.get("terms") or []),
        "references": len(manifest.get("references") or []),
    }
    component_passes = [
        all(item.get("passed") for item in REVIEW_LOG["translation"]),
        all(item.get("passed") for item in REVIEW_LOG["figures"]),
        all(item.get("passed") for item in REVIEW_LOG["tables"]),
        bool(REVIEW_LOG["overview"].get("passed")),
        bool(REVIEW_LOG["terms"].get("passed")),
        bool(REVIEW_LOG["references"].get("passed")),
    ]
    REVIEW_LOG["passed"] = all(component_passes) and not REVIEW_LOG["errors"]
    if not REVIEW_LOG["passed"]:
        raise RuntimeError("strong AI component review did not pass")
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    review_path = output_path.with_suffix(".strong-ai-review.json")
    review_path.write_text(json.dumps(REVIEW_LOG, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "generator": "v082-strong-ai-v13",
        "paper_key": REVIEW_LOG["paper_key"],
        "review": str(review_path),
        "passed": True,
    }, ensure_ascii=False, indent=2))


def arg_value(argv: list[str], name: str, default: str) -> Path:
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return Path(argv[index + 1])
    return Path(default)


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("usage: generator evidence.json plan.json output.json [--cache-dir PATH]")
    evidence_path = Path(sys.argv[1])
    plan_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])
    cache_dir = arg_value(sys.argv, "--cache-dir", ".build/v082/model-cache")
    legacy.translate_all = sequential_translate_all
    legacy.generate_figure_studies = generate_figure_studies_strong
    legacy.main()
    postprocess_manifest(evidence_path, plan_path, output_path, cache_dir)


if __name__ == "__main__":
    main()
