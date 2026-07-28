#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
import validate_v082_canvas_shell_lock_core as core


core.DYNAMIC_SCRIPT_IDS.update({
    "referenceData",
    "canvas-reader-v060-script",
    "canvas-reader-v061-script",
    "canvas-reader-v062-script",
    "canvas-v073-script",
    "canvas-v077-script",
    "canvas-v078-final-script",
    "canvas-v081-script",
    "canvas-v082-script",
})
if "#crossRefPreviewStore" not in core.CONTENT_SELECTORS:
    core.CONTENT_SELECTORS.append("#crossRefPreviewStore")


def neutralize(path: Path) -> tuple[str, dict]:
    raw = path.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    errors: list[str] = []

    for selector in core.CONTENT_SELECTORS:
        nodes = soup.select(selector)
        if len(nodes) != 1:
            errors.append(f"content slot {selector!r} expected once, found {len(nodes)}")
            continue
        node = nodes[0]
        if node.name == "title":
            node.string = "__PAPER_TITLE__"
        else:
            # Paper-specific attributes are content as well. Preserve only the
            # canonical identity/class contract before inserting the slot marker.
            keep = {}
            if node.get("id"):
                keep["id"] = node.get("id")
            if node.get("class"):
                keep["class"] = list(node.get("class") or [])
            node.attrs = keep
            node.clear()
            node.append(f"__CONTENT_SLOT__{selector}")

    if soup.body:
        soup.body["data-paper-key"] = "__PAPER_KEY__"
        soup.body["data-mode"] = "bilingual"

    for tag in soup.find_all("script"):
        if tag.get("id") in core.DYNAMIC_SCRIPT_IDS or (tag.get("type") == "application/json" and not tag.get("id")):
            tag.string = "__PAPER_DATA__"

    return str(soup), {
        "errors": errors,
        "style_hashes": core.style_hashes(soup),
        "script_inventory": core.script_inventory(soup),
        "topbar_children": core.direct_signature(soup.select_one("#topbar")),
        "layout_children": core.direct_signature(soup.select_one(".layout")),
        "body_children": core.direct_signature(soup.body),
    }


core.neutralize = neutralize


if __name__ == "__main__":
    core.main()
