#!/usr/bin/env python3
from __future__ import annotations

import json

import generate_v082_reader_manifest_with_copilot_sdk_v19 as v19


def test_chunking_preserves_order_and_bounds() -> None:
    records = [
        {"id": "a", "text": "A" * 4},
        {"id": "b", "text": "B" * 4},
        {"id": "c", "text": "C" * 4},
        {"id": "d", "text": "D" * 2},
    ]
    batches = v19.chunk_translation_records(records, max_items=2, max_chars=7)
    assert [[item["id"] for item in batch] for batch in batches] == [
        ["a"], ["b"], ["c", "d"]
    ], batches
    assert [item["id"] for batch in batches for item in batch] == ["a", "b", "c", "d"]


def test_response_map_requires_explicit_ids() -> None:
    payload = {
        "items": [
            {"id": "p1", "passed": True, "zh_final": "译文一"},
            {"id": "p2", "passed": False, "zh_final": "译文二"},
            {"passed": True, "zh_final": "无ID"},
        ]
    }
    mapped = v19.response_item_map(payload)
    assert set(mapped) == {"p1", "p2"}, mapped
    assert mapped["p1"]["passed"] is True
    assert mapped["p2"]["passed"] is False


def test_component_validation_remains_fail_closed() -> None:
    source = "The cohort contained 26 cases and had an FDR threshold of 0.05."
    accepted = v19.v17.component_translation_issues(
        "paragraph/results/p-1",
        source,
        "该队列包含26例，FDR阈值为0.05。",
    )
    assert not accepted, accepted
    rejected = v19.v17.component_translation_issues(
        "paragraph/results/p-1",
        source,
        "该队列采用FDR阈值0.05。",
    )
    assert "number not preserved: 26" in rejected, rejected


if __name__ == "__main__":
    test_chunking_preserves_order_and_bounds()
    test_response_map_requires_explicit_ids()
    test_component_validation_remains_fail_closed()
    print(json.dumps({"batched_translation_contracts": 3, "passed": True}, indent=2))
