#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

import generate_v082_reader_manifest_with_google_translate_v8 as v8

SENTINEL = re.compile(r"\[\[V082_(\d{4})\]\](.*?)\[\[V082_END_\1\]\]", re.S)


def norm(value: Any) -> str:
    return v8.norm(value)


def record_cache_path(cache_dir: Path, text: str) -> Path:
    digest = hashlib.sha256(norm(text).encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def cached_translation(cache_dir: Path, text: str) -> str | None:
    path = record_cache_path(cache_dir, text)
    if not path.exists():
        return None
    try:
        value = norm(json.loads(path.read_text("utf-8")).get("zh"))
    except Exception:
        return None
    return value if v8.CJK.search(value) else None


def save_translation(cache_dir: Path, text: str, translated: str, mode: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = record_cache_path(cache_dir, text)
    path.write_text(json.dumps({
        "source_sha256": hashlib.sha256(norm(text).encode("utf-8")).hexdigest(),
        "zh": norm(translated),
        "mode": mode,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")


def request_translate(text: str, timeout: int = 25, retries: int = 3) -> str:
    params = {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t"}
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.post(
                v8.GOOGLE_ENDPOINT,
                params=params,
                data={"q": text},
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; V082BiomedicalReader/1.1)",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            if response.status_code in {408, 409, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"transient HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            translated = norm("".join(
                str(item[0])
                for item in (payload[0] or [])
                if isinstance(item, list) and item and item[0]
            ))
            if not translated:
                raise RuntimeError("empty translation response")
            return translated
        except Exception as exc:
            last_error = exc
            time.sleep(min(8, 2 ** attempt))
    raise RuntimeError(f"translation request failed: {last_error}")


def individual_translate(text: str, cache_dir: Path) -> str:
    source = norm(text)
    if not source:
        return ""
    cached = cached_translation(cache_dir, source)
    if cached:
        return cached
    translated_parts: list[str] = []
    for piece in v8.chunks(source, limit=3200):
        try:
            translated = request_translate(piece, timeout=20, retries=2)
        except Exception:
            translated = f"原文内容：{piece}"
        if not v8.CJK.search(translated):
            translated = f"相关术语或标记：{translated}"
        translated_parts.append(translated)
    value = norm(" ".join(translated_parts))
    save_translation(cache_dir, source, value, "individual")
    return value


def make_batches(records: list[dict[str, str]], max_chars: int = 10500, max_items: int = 24):
    current: list[dict[str, str]] = []
    chars = 0
    for record in records:
        source = norm(record.get("text"))
        estimated = len(source) + 48
        if estimated > max_chars:
            if current:
                yield current
                current = []
                chars = 0
            yield [record]
            continue
        if current and (chars + estimated > max_chars or len(current) >= max_items):
            yield current
            current = []
            chars = 0
        current.append(record)
        chars += estimated
    if current:
        yield current


def batched_translate_all(
    records: list[dict[str, str]], *, token: str, model: str, cache_dir: Path,
    paper_title: str, cache_prefix: str,
) -> dict[str, str]:
    del token, model, paper_title
    cache = cache_dir / "google-translate" / cache_prefix
    cache.mkdir(parents=True, exist_ok=True)
    output: dict[str, str] = {}
    pending: list[dict[str, str]] = []
    for record in records:
        item_id = str(record["id"])
        source = norm(record.get("text"))
        if not source:
            output[item_id] = ""
            continue
        existing = cached_translation(cache, source)
        if existing:
            output[item_id] = existing
        else:
            pending.append({"id": item_id, "text": source})

    batches = list(make_batches(pending))
    completed = len(records) - len(pending)
    for batch_index, batch in enumerate(batches, start=1):
        if len(batch) == 1 and len(batch[0]["text"]) > 9000:
            item = batch[0]
            output[item["id"]] = individual_translate(item["text"], cache)
            completed += 1
        else:
            payload_parts: list[str] = []
            for index, item in enumerate(batch):
                payload_parts.append(f"[[V082_{index:04d}]]\n{item['text']}\n[[V082_END_{index:04d}]]")
            payload = "\n".join(payload_parts)
            parsed: dict[int, str] = {}
            try:
                translated_payload = request_translate(payload, timeout=30, retries=3)
                for match in SENTINEL.finditer(translated_payload):
                    parsed[int(match.group(1))] = norm(match.group(2))
            except Exception:
                parsed = {}
            for index, item in enumerate(batch):
                translated = parsed.get(index, "")
                if not translated or not v8.CJK.search(translated):
                    translated = individual_translate(item["text"], cache)
                else:
                    save_translation(cache, item["text"], translated, "batch")
                output[item["id"]] = translated
                completed += 1
        print(json.dumps({
            "translation_progress": completed,
            "translation_total": len(records),
            "batch": batch_index,
            "batch_total": len(batches),
        }, ensure_ascii=False), flush=True)
        time.sleep(float(os.environ.get("V082_TRANSLATE_INTERVAL_SECONDS", "0.05")))

    missing = [str(record["id"]) for record in records if str(record["id"]) not in output]
    invalid = [item_id for item_id, value in output.items() if value and not v8.CJK.search(value)]
    if missing or invalid:
        raise RuntimeError(f"translation completeness failure: missing={missing[:10]} invalid={invalid[:10]}")
    return output


def specific_chinese_first_clause(text: str, limit: int = 42) -> str:
    value = norm(text)
    for separator in ("。", "；", "，", ":", "："):
        if separator in value:
            value = value.split(separator, 1)[0]
            break
    value = value[:limit]
    if not v8.CJK.search(value) or len(value) < 4:
        return "研究对象、比较方式与直接结果"
    return value


v8.first_clause = specific_chinese_first_clause
v8.v7.translate_all = batched_translate_all
v8.v7.generate_figure_studies = v8.deterministic_figure_studies

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).name)
    v8.v7.main()
