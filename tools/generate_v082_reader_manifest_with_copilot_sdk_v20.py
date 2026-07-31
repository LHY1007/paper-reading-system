#!/usr/bin/env python3
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import generate_v082_reader_manifest_with_copilot_sdk_v19 as v19


v13 = v19.v13
_ORIGINAL_DRAFT_BATCH = v19.draft_batch
_ORIGINAL_REVIEW_BATCH = v19.review_batch


@contextmanager
def translation_reasoning_effort() -> Iterator[None]:
    """Use a dedicated effort level only for objective translation calls.

    Figure interpretation, overview synthesis and all other scientific reasoning
    remain on the workflow-wide high setting. Translation still uses GPT-5.4 for
    both generation and an independent review, but does not spend high-reasoning
    latency on a source-preserving language conversion task.
    """
    key = "V082_REASONING_EFFORT"
    previous = os.environ.get(key)
    os.environ[key] = os.environ.get("V082_TRANSLATION_REASONING_EFFORT", "medium")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def draft_batch_with_translation_effort(*args, **kwargs):
    with translation_reasoning_effort():
        return _ORIGINAL_DRAFT_BATCH(*args, **kwargs)


def review_batch_with_translation_effort(*args, **kwargs):
    with translation_reasoning_effort():
        return _ORIGINAL_REVIEW_BATCH(*args, **kwargs)


v19.draft_batch = draft_batch_with_translation_effort
v19.review_batch = review_batch_with_translation_effort
v13.sequential_translate_all = v19.batched_translate_all


if __name__ == "__main__":
    v13.main()
