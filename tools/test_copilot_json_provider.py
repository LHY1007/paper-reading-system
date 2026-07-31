#!/usr/bin/env python3
from __future__ import annotations

import json

import copilot_sdk_json_provider as provider


def test_valid_json() -> None:
    value = provider.parse_json_response('{"zh":"摘要","passed":true}')
    assert value == {"zh": "摘要", "passed": True}


def test_markdown_fence() -> None:
    value = provider.parse_json_response('```json\n{"zh":"摘要"}\n```')
    assert value == {"zh": "摘要"}


def test_missing_comma_repair() -> None:
    value = provider.parse_json_response('{"zh":"摘要" "passed":true}')
    assert value == {"zh": "摘要", "passed": True}, value


def test_truncated_object_repair() -> None:
    value = provider.parse_json_response('preface {"zh":"完整中文译文","issues":[]')
    assert isinstance(value, dict), value
    assert value.get("zh") == "完整中文译文", value
    assert value.get("issues") == [], value


def test_balanced_extraction() -> None:
    value = provider.parse_json_response('commentary before {"a":[1,2,{"b":"c"}]} commentary after')
    assert value == {"a": [1, 2, {"b": "c"}]}, value


if __name__ == "__main__":
    test_valid_json()
    test_markdown_fence()
    test_missing_comma_repair()
    test_truncated_object_repair()
    test_balanced_extraction()
    print(json.dumps({"provider_json_contracts": 5, "passed": True}, indent=2))
