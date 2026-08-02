#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bs4 import BeautifulSoup

SELECTORS = {
    "hero": ".hero",
    "quick_overview": "#quick-pane #overview",
    "bilingual_overview": "#overview-bilingual-folded",
    "figure_index": "#figure-table-index",
    "paper_section": "section.paper-section",
    "bilingual_unit": ".bilingual-unit",
    "figure_card": ".figure-card",
    "table_card": ".table-card",
    "reference_item": ".reference-item",
    "term_card": ".term-card",
    "viewer": "#viewer",
    "settings": "#settings",
    "annotation_drawer": ".annotation-drawer",
}


def attrs(node):
    return {k: v for k, v in node.attrs.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    soup = BeautifulSoup(args.html.read_text("utf-8"), "html.parser")
    report = {"file": args.html.name, "components": {}, "controls": {}}
    for name, selector in SELECTORS.items():
        node = soup.select_one(selector)
        report["components"][name] = {
            "selector": selector,
            "found": node is not None,
            "attrs": attrs(node) if node else None,
            "outer_html": str(node) if node else None,
        }
    for selector in [
        ".figure-ref", ".section-ref", ".open-in-viewer", ".figure-study-button",
        ".card-toggle", ".zoom-button", ".asset-group-ref", ".section-jump"
    ]:
        report["controls"][selector] = [
            {"tag": n.name, "attrs": attrs(n), "text": " ".join(n.get_text(" ", strip=True).split())}
            for n in soup.select(selector)[:10]
        ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
