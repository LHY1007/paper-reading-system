#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Iterable

import generate_v082_reader_manifest_with_github_models as base


def constrained_batches(
    records: list[dict[str, Any]], max_chars: int = 16000, max_items: int = 10
) -> Iterable[list[dict[str, Any]]]:
    # The free GitHub Models GPT-4.1 endpoint enforces an 8k-token request body.
    # Keep source JSON well below that limit after the system prompt is included.
    char_limit = min(max_chars, 15000)
    item_limit = min(max_items, 10)
    current: list[dict[str, Any]] = []
    chars = 0
    for record in records:
        size = len(base.json_text(record))
        if size > char_limit:
            if current:
                yield current
                current = []
                chars = 0
            yield [record]
            continue
        if current and (chars + size > char_limit or len(current) >= item_limit):
            yield current
            current = []
            chars = 0
        current.append(record)
        chars += size
    if current:
        yield current


base.batches = constrained_batches


if __name__ == "__main__":
    base.main()
