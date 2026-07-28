#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup
import render_v082_canvas_component_locked_v2_core as core


def replace_const_expression(script: str, name: str, expression: str) -> str:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=", script)
    if not match:
        raise ValueError(f"missing JavaScript assignment for {name}")
    pos = match.end()
    quote = None
    escaped = False
    depth = 0
    index = pos
    while index < len(script):
        char = script[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in "'\"`":
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == ";" and depth == 0:
                return script[:pos] + expression + script[index:]
        index += 1
    raise ValueError(f"unterminated JavaScript assignment for {name}")


def complete_review_manifest(soup: BeautifulSoup, manifest: dict[str, Any], study_ids: list[str]) -> None:
    node = soup.find("script", id="v080ReviewManifest")
    if not node:
        return
    all_card_ids = [card.get("id") for card in soup.select("#bilingual-pane .figure-card[id]")]
    table_ids = [card.get("id") for card in soup.select("#bilingual-pane .table-card[id]")]
    data = {
        "version": "0.8.2-component-locked",
        "base_version": "0.8.2-CANVAS",
        "content_hashes": {},
        "expected": {
            "figure_cards": len(all_card_ids),
            "table_cards": len(table_ids),
            "study_buttons": len(study_ids),
            "figure_ids": all_card_ids,
            "table_ids": table_ids,
            "study_ids": study_ids,
        },
        "panel_location_policy": {
            "mode": "verified-only",
            "verified_panel_maps": {},
        },
    }
    node["type"] = "application/json"
    node.string = json.dumps(data, ensure_ascii=False, separators=(",", ":"))


core.base.replace_const_expression = replace_const_expression
core.complete_review_manifest = complete_review_manifest


if __name__ == "__main__":
    core.main()
