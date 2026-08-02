#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

import copilot_sdk_json_provider_v2 as provider
import generate_v082_reader_manifest_with_strong_ai_v13 as v13


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
    del token, max_tokens
    image_data_uri = v13.prepare_image_data_uri(image_src)
    return provider.call_json(
        model=model,
        system=system,
        payload=payload,
        cache_dir=cache_dir,
        cache_name=cache_name,
        image_data_uri=image_data_uri,
        retries=min(8, retries),
    )


v13.base.call_model_json = provider.compatible_call_model_json
v13.call_multimodal_json = call_multimodal_json


if __name__ == "__main__":
    v13.main()
