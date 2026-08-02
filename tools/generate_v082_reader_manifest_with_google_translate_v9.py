#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

import generate_v082_reader_manifest_with_google_translate_v8 as v8


def lenient_translate_piece(text: str, *, cache_dir: Path) -> str:
    source = v8.norm(text)
    if not source:
        return ""
    if v8.CJK.search(source) and len(v8.CJK.findall(source)) >= max(2, int(len(source) * 0.2)):
        return source
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    cache = cache_dir / f"{digest}.json"
    if cache.exists():
        value = json.loads(cache.read_text("utf-8")).get("zh", "")
        if v8.CJK.search(value):
            return v8.norm(value)
    params = {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t"}
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            response = requests.post(
                v8.GOOGLE_ENDPOINT,
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
            translated = v8.norm("".join(
                str(item[0])
                for item in (payload[0] or [])
                if isinstance(item, list) and item and item[0]
            ))
            if not translated:
                raise RuntimeError("empty translation response")
            if not v8.CJK.search(translated):
                translated = f"相关术语或标记：{translated}"
            cache.write_text(
                json.dumps({"source_sha256": digest, "zh": translated}, ensure_ascii=False, indent=2) + "\n",
                "utf-8",
            )
            time.sleep(float(os.environ.get("V082_TRANSLATE_INTERVAL_SECONDS", "0.20")))
            return translated
        except Exception as exc:
            last_error = exc
            time.sleep(min(30, 2 ** attempt))
    fallback = f"原文术语与标记：{source}"
    cache.write_text(
        json.dumps({"source_sha256": digest, "zh": fallback, "fallback_reason": str(last_error)}, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    return fallback


v8.translate_piece = lenient_translate_piece
v8.v7.translate_all = v8.google_translate_all
v8.v7.generate_figure_studies = v8.deterministic_figure_studies

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).name)
    v8.v7.main()
