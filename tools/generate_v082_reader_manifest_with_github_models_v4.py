#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_github_models_v3 as repaired

base = repaired.base
_original_call_model_json = base.call_model_json
_last_uncached_request_at = 0.0


def _cache_path(*, model: str, system: str, user_payload: Any, cache_dir: Path, cache_name: str) -> Path:
    key_material = base.json_text({"model": model, "system": system, "payload": user_payload})
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return cache_dir / f"{cache_name}-{digest}.json"


def _throttle_uncached_request() -> None:
    global _last_uncached_request_at
    minimum_interval = max(0.0, float(os.environ.get("GITHUB_MODELS_MIN_INTERVAL_SECONDS", "4")))
    now = time.monotonic()
    delay = minimum_interval - (now - _last_uncached_request_at)
    if delay > 0:
        print(f"GitHub Models pacing: sleeping {delay:.1f}s before next uncached request", flush=True)
        time.sleep(delay)
    _last_uncached_request_at = time.monotonic()


def call_model_json_with_syntax_retry(
    *, token: str, model: str, system: str, user_payload: Any, cache_dir: Path,
    cache_name: str, max_tokens: int = 32768, retries: int = 8,
) -> Any:
    """Retry malformed JSON and pace uncached GitHub Models requests.

    Cached responses are returned without delay. Uncached requests are spaced so a
    long paper cannot immediately exhaust the free inference endpoint's minute-level
    quota. Scientific requirements and fail-closed behavior remain unchanged.
    """
    syntax_errors: list[str] = []
    for syntax_attempt in range(4):
        strict_system = system
        strict_cache_name = cache_name
        if syntax_attempt:
            strict_system = (
                system
                + "\nYour previous response was rejected solely because it was not syntactically valid JSON. "
                  "Return the complete answer again as one strict JSON object. Use double-quoted keys and strings, "
                  "escape internal quotation marks and backslashes, include every required comma and closing bracket, "
                  "and do not add markdown fences or prose outside the JSON object. Do not shorten or change the scientific content."
                + f" This is JSON syntax retry {syntax_attempt}."
            )
            strict_cache_name = f"{cache_name}-strict-json-{syntax_attempt}"
        cache_path = _cache_path(
            model=model,
            system=strict_system,
            user_payload=user_payload,
            cache_dir=cache_dir,
            cache_name=strict_cache_name,
        )
        if not cache_path.exists():
            _throttle_uncached_request()
        try:
            return _original_call_model_json(
                token=token,
                model=model,
                system=strict_system,
                user_payload=user_payload,
                cache_dir=cache_dir,
                cache_name=strict_cache_name,
                max_tokens=max_tokens,
                retries=retries,
            )
        except json.JSONDecodeError as exc:
            syntax_errors.append(f"attempt {syntax_attempt}: {exc}")
            print(
                f"model request {cache_name} returned malformed JSON; "
                f"retrying with strict syntax contract ({syntax_attempt + 1}/3)",
                flush=True,
            )
    raise RuntimeError(
        f"model request {cache_name} returned malformed JSON after strict retries: "
        + " | ".join(syntax_errors)
    )


base.call_model_json = call_model_json_with_syntax_retry


if __name__ == "__main__":
    base.main()
