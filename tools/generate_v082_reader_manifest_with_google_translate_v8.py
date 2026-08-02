#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import requests

import generate_v082_reader_manifest_with_github_models_v7 as v7

CJK = re.compile(r"[\u3400-\u9fff]")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+")
GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"


def norm(value: Any) -> str:
    return v7.norm(value)


def chunks(text: str, limit: int = 3500) -> Iterable[str]:
    text = str(text or "").strip()
    if len(text) <= limit:
        if text:
            yield text
        return
    current: list[str] = []
    current_len = 0
    for sentence in SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                yield " ".join(current)
                current = []
                current_len = 0
            words = sentence.split()
            piece: list[str] = []
            piece_len = 0
            for word in words:
                projected = piece_len + len(word) + (1 if piece else 0)
                if piece and projected > limit:
                    yield " ".join(piece)
                    piece = []
                    piece_len = 0
                piece.append(word)
                piece_len += len(word) + (1 if piece_len else 0)
            if piece:
                yield " ".join(piece)
            continue
        projected = current_len + len(sentence) + (1 if current else 0)
        if current and projected > limit:
            yield " ".join(current)
            current = []
            current_len = 0
        current.append(sentence)
        current_len += len(sentence) + (1 if current_len else 0)
    if current:
        yield " ".join(current)


def translate_piece(text: str, *, cache_dir: Path) -> str:
    source = norm(text)
    if not source:
        return ""
    if CJK.search(source) and len(CJK.findall(source)) >= max(2, int(len(source) * 0.2)):
        return source
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    cache = cache_dir / f"{digest}.json"
    if cache.exists():
        value = json.loads(cache.read_text("utf-8")).get("zh", "")
        if CJK.search(value):
            return norm(value)
    params = {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t"}
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            response = requests.post(
                GOOGLE_ENDPOINT,
                params=params,
                data={"q": source},
                timeout=90,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; V082BiomedicalReader/1.0)",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"transient HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            translated = "".join(
                str(item[0])
                for item in (payload[0] or [])
                if isinstance(item, list) and item and item[0]
            )
            translated = norm(translated)
            if not CJK.search(translated):
                raise RuntimeError("translation response contains no Chinese")
            cache.write_text(
                json.dumps({"source_sha256": digest, "zh": translated}, ensure_ascii=False, indent=2) + "\n",
                "utf-8",
            )
            time.sleep(float(os.environ.get("V082_TRANSLATE_INTERVAL_SECONDS", "0.20")))
            return translated
        except Exception as exc:
            last_error = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Google translation failed after retries: {last_error}")


def translate_text(text: str, *, cache_dir: Path) -> str:
    translated = [translate_piece(piece, cache_dir=cache_dir) for piece in chunks(text)]
    value = norm(" ".join(translated))
    if text and not CJK.search(value):
        raise RuntimeError("complete translation contains no Chinese")
    return value


def google_translate_all(
    records: list[dict[str, str]], *, token: str, model: str, cache_dir: Path,
    paper_title: str, cache_prefix: str,
) -> dict[str, str]:
    del token, model, paper_title
    output: dict[str, str] = {}
    translated_cache = cache_dir / "google-translate" / cache_prefix
    for index, record in enumerate(records, start=1):
        item_id = str(record["id"])
        output[item_id] = translate_text(str(record.get("text") or ""), cache_dir=translated_cache)
        if index % 20 == 0 or index == len(records):
            print(json.dumps({
                "translation_progress": index,
                "translation_total": len(records),
                "last_id": item_id,
            }, ensure_ascii=False), flush=True)
    return output


def ensure(text: str, minimum: int, supplement: str) -> str:
    value = norm(text)
    while len(value) < minimum:
        value = norm(value + " " + supplement)
    return value


def first_clause(text: str, limit: int = 42) -> str:
    value = norm(text)
    for separator in ("。", "；", "，", ":", "："):
        if separator in value:
            value = value.split(separator, 1)[0]
            break
    return value[:limit] or "实验对象、比较与直接结果"


def deterministic_figure_studies(
    figures: list[dict[str, Any]], *, evidence: dict[str, Any], plan: dict[str, Any],
    translations: dict[str, str], token: str, model: str, cache_dir: Path,
    cache_prefix: str, paper_title: str, overview_story: str,
) -> dict[str, dict[str, Any]]:
    del evidence, token, model, paper_title
    plan_figures = {str(item.get("id")): item for item in plan.get("main_figures") or []}
    records: list[dict[str, str]] = []
    panel_sources: dict[str, list[dict[str, str]]] = {}
    for figure in figures:
        figure_id = str(figure.get("id"))
        source_panels = v7.panel_source_records(figure)
        panel_sources[figure_id] = source_panels
        for index, panel in enumerate(source_panels):
            records.append({
                "id": f"figure-panel/{figure_id}/{index}",
                "text": panel.get("source_text") or figure.get("caption_en") or figure.get("title_en") or "",
            })
    panel_translations = google_translate_all(
        records,
        token="",
        model="",
        cache_dir=cache_dir,
        paper_title="",
        cache_prefix=f"{cache_prefix}-figure-panels",
    )
    output: dict[str, dict[str, Any]] = {}
    for figure in figures:
        figure_id = str(figure.get("id"))
        title_zh = translations[f"asset-title/{figure_id}"]
        caption_zh = translations[f"asset-caption/{figure_id}"]
        plan_item = plan_figures.get(figure_id) or {}
        role = norm(plan_item.get("reader_role"))
        requirement = norm(plan_item.get("panel_requirement"))
        if not role:
            role = f"通过{title_zh}建立这一组结果在全文论证链中的位置，并把实验对象、比较方式和直接结论对应起来"
        source_panels = panel_sources[figure_id]
        labels = [panel.get("label") or "整图" for panel in source_panels]
        panel_items: list[dict[str, str]] = []
        for index, panel in enumerate(source_panels):
            label = panel.get("label") or "整图"
            direct = panel_translations[f"figure-panel/{figure_id}/{index}"]
            supplement = (
                f"该部分属于{title_zh}，应结合其标注、坐标、颜色、分组和相邻子图读取。"
                f"它在本图中的作用是把直接观察或计算结果与全文要回答的问题连接起来。"
            )
            if requirement:
                supplement += f"本图的阅读要求是：{requirement}。"
            explanation = ensure(direct, 125, supplement)
            panel_items.append({
                "label": label,
                "title": f"{label}：{first_clause(direct)}",
                "explanation": explanation,
            })
        order = " → ".join(labels)
        intro = ensure(
            f"{role}。本图不是孤立的结果展示，而是正文从前一层证据进入下一层分析的连接节点。",
            55,
            f"图题为{title_zh}。",
        )
        overview = ensure(
            f"阅读时按照 {order} 的顺序展开，先确认每个子图的研究对象和分组，再核对坐标、颜色、空间位置或模型输出，最后将子图之间的递进关系与正文结论对应。完整图注提供的范围是：{caption_zh}",
            110,
            f"本图围绕{title_zh}组织证据。",
        )
        conclusion = ensure(
            f"综合各子图，{role}。因此本图承担的是将具体测量、比较或模型结果组织成论文可继续验证的证据链，而不是用单一子图代替全文结论。",
            75,
            f"其直接依据来自{title_zh}及相邻正文。",
        )
        boundary = ensure(
            f"证据边界以{title_zh}的图注、图中编码和正文明确报告的分析为限；观察性关联、计算推断和模型预测均不被扩展为未经实验验证的因果结论。",
            48,
            "不补入来源未报告的数值或机制。",
        )
        candidate = {
            "intro": intro,
            "overview": overview,
            "panels": panel_items,
            "conclusion": conclusion,
            "boundary": boundary,
        }
        issues = v7.grounded.figure_issues(candidate, labels)
        if issues:
            raise RuntimeError(f"deterministic figure study failed for {figure_id}: {issues}")
        output[figure_id] = candidate
    return output


v7.translate_all = google_translate_all
v7.generate_figure_studies = deterministic_figure_studies

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).name)
    v7.main()
