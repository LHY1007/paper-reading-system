#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_github_models_v3 as repaired

base = repaired.base
_original_call_model_json = base.call_model_json


def call_model_json_with_syntax_retry(
    *, token: str, model: str, system: str, user_payload: Any, cache_dir: Path,
    cache_name: str, max_tokens: int = 32768, retries: int = 8,
) -> Any:
    """Retry model output when the transport succeeds but JSON syntax is invalid.

    The evidence, task and quality requirements remain unchanged. Only an explicit
    strict-JSON reminder and a distinct cache key are added after a syntax failure,
    so malformed output is never accepted or silently truncated.
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
