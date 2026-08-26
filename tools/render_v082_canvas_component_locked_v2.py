#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag
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


def format_reference_ids(ids: list[str]) -> str:
    values = [int(value) for value in ids]
    if len(values) >= 2 and values == list(range(values[0], values[-1] + 1)):
        return f"{values[0]}–{values[-1]}"
    return ",".join(str(value) for value in values)


def append_inline(soup: BeautifulSoup, parent: Tag, items: list[dict[str, Any]], unit: str, prefix: str, terms: dict[str, dict[str, Any]]) -> None:
    """Render exact inline content without moving citations/figures/terms.

    V0.8.3 adds citation_label so bracketed source citations such as [15] can
    remain at their original position while still using the established
    citation popup. Empty citation-only items do not create empty sentence
    spans. The text content itself is never rewritten here.
    """
    parent.clear()
    for index, item in enumerate(items):
        text = str(item.get("text", ""))
        group = f"sp-{prefix}-{unit}-{index}"
        emitted_text = False
        if item.get("figure_ids"):
            ids = item["figure_ids"]
            for position, asset_id in enumerate(ids):
                if position:
                    parent.append(NavigableString("、"))
                button = soup.new_tag("button")
                button["class"] = ["figure-ref"]
                button["type"] = "button"
                button["data-target"] = asset_id
                button.append(NavigableString(text if len(ids) == 1 else asset_id))
                parent.append(button)
            emitted_text = True
        elif item.get("section_id"):
            button = soup.new_tag("button")
            button["class"] = ["section-ref"]
            button["type"] = "button"
            button["data-target"] = item["section_id"]
            button.append(NavigableString(text))
            parent.append(button)
            emitted_text = True
        elif item.get("term_id"):
            term_data = terms.get(item["term_id"], {})
            outer = soup.new_tag("span")
            outer["class"] = ["term-pop"]
            outer["data-term-id"] = item["term_id"]
            outer["data-term-level"] = str(term_data.get("level", item.get("level", 2)))
            outer["data-tip"] = term_data.get("definition_zh", item.get("definition_zh", ""))
            category = term_data.get("category", item.get("category"))
            if category:
                outer["data-term-category"] = category
            outer["role"] = "button"
            outer["tabindex"] = "0"
            if text:
                outer.append(core.base.sentence(soup, text, group, index))
            parent.append(outer)
            emitted_text = bool(text)
        elif text:
            parent.append(core.base.sentence(soup, text, group, index))
            emitted_text = True

        reference_ids = [str(value) for value in item.get("citation_ids", [])]
        if reference_ids:
            citation = soup.new_tag("sup")
            citation["class"] = ["citation"]
            citation["data-refs"] = ",".join(reference_ids)
            citation["role"] = "button"
            citation["tabindex"] = "0"
            label = str(item.get("citation_label") or format_reference_ids(reference_ids))
            citation["data-citation-label"] = label
            citation.append(NavigableString(label))
            parent.append(citation)
        elif not emitted_text and text:
            parent.append(core.base.sentence(soup, text, group, index))


def complete_review_manifest(soup: BeautifulSoup, manifest: dict[str, Any], study_ids: list[str]) -> None:
    node = soup.find("script", id="v080ReviewManifest")
    if not node:
        return
    all_card_ids = [card.get("id") for card in soup.select("#bilingual-pane .figure-card[id]")]
    table_ids = [card.get("id") for card in soup.select("#bilingual-pane .table-card[id]")]
    data = {
        "version": "0.8.3-component-locked",
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
core.base.append_inline = append_inline
core.complete_review_manifest = complete_review_manifest


if __name__ == "__main__":
    core.main()
