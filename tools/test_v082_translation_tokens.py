#!/usr/bin/env python3
from __future__ import annotations

import json

import generate_v082_reader_manifest_with_copilot_sdk_v17 as v17


def test_hyphenated_abbreviation_boundary() -> None:
    source = "This challenges distinct subgroups toward a TME-determined risk continuum."
    accepted = v17.component_translation_issues(
        "paragraph/abstract/p-0001",
        source,
        "这一结果将离散亚组模型修正为由TME决定的风险连续谱。",
    )
    assert not any("abbreviations not preserved" in issue for issue in accepted), accepted

    rejected = v17.component_translation_issues(
        "paragraph/abstract/p-0001",
        source,
        "这一结果将离散亚组模型修正为由微环境决定的风险连续谱。",
    )
    assert any("TME" in issue for issue in rejected), rejected
    assert not any("TME-" in issue for issue in rejected), rejected


def test_internal_hyphenated_marker() -> None:
    source = "PD-1 and CD8 were measured."
    accepted = v17.component_translation_issues(
        "paragraph/results/p-0002",
        source,
        "检测了PD-1和CD8。",
    )
    assert not any("abbreviations not preserved" in issue for issue in accepted), accepted


if __name__ == "__main__":
    test_hyphenated_abbreviation_boundary()
    test_internal_hyphenated_marker()
    print(json.dumps({"translation_token_contracts": 2, "passed": True}, indent=2))
