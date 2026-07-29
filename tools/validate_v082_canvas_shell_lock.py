#!/usr/bin/env python3
from __future__ import annotations

import hashlib
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

PAPER_META_KEYS = {
    "description",
    "citation_title",
    "citation_author",
    "citation_doi",
    "citation_journal_title",
    "citation_publication_date",
    "og:title",
    "og:description",
    "twitter:title",
    "twitter:description",
}


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
            keep = {}
            if node.get("id"):
                keep["id"] = node.get("id")
            if node.get("class"):
                keep["class"] = list(node.get("class") or [])
            node.attrs = keep
            node.clear()
            node.append(f"__CONTENT_SLOT__{selector}")

    if soup.html:
        for attr in ("data-v082-template", "data-v082-template-version", "data-v082-shell-sha256"):
            soup.html.attrs.pop(attr, None)

    if soup.body:
        soup.body["data-paper-key"] = "__PAPER_KEY__"
        soup.body["data-mode"] = "bilingual"

    for meta in soup.find_all("meta"):
        key = str(meta.get("name") or meta.get("property") or "").lower()
        if key in PAPER_META_KEYS:
            meta["content"] = "__PAPER_META__"
    for link in soup.find_all("link"):
        rel = {str(value).lower() for value in (link.get("rel") or [])}
        if "canonical" in rel:
            link["href"] = "__PAPER_URL__"

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
_original_analyze = core.analyze


def analyze(canonical: Path, candidate: Path) -> dict:
    canonical_soup = BeautifulSoup(canonical.read_text("utf-8"), "html.parser")
    normalized = canonical_soup.select_one('meta[name="v082-canonical-normalized"][content="1"]') is not None
    if normalized:
        core.CANONICAL_SHA256 = hashlib.sha256(canonical.read_bytes()).hexdigest()
        required = [
            "#readerModeSwitch.reader-mode-switch",
            '#readerModeSwitch .mode-btn[data-mode="quick"]',
            '#readerModeSwitch .mode-btn[data-mode="bilingual"]',
        ]
        for selector in required:
            if selector not in core.REQUIRED_FIXED_SELECTORS:
                core.REQUIRED_FIXED_SELECTORS.append(selector)
    report = _original_analyze(canonical, candidate)
    report["canonical_kind"] = "normalized-master" if normalized else "original-00"
    return report


core.analyze = analyze


if __name__ == "__main__":
    core.main()
