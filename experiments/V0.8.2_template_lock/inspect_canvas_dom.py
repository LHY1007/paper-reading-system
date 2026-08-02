#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup


def compact_classes(node):
    return list(node.get("class") or [])


def node_record(node, index: int) -> dict:
    text = " ".join(node.get_text(" ", strip=True).split())
    return {
        "index": index,
        "tag": node.name,
        "id": node.get("id"),
        "classes": compact_classes(node),
        "data": {k: v for k, v in node.attrs.items() if str(k).startswith("data-")},
        "text_preview": text[:180],
        "direct_children": [
            {
                "tag": child.name,
                "id": child.get("id"),
                "classes": compact_classes(child),
            }
            for child in node.find_all(recursive=False)
            if getattr(child, "name", None)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    raw = args.html.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")

    all_nodes = soup.find_all(True)
    classes = Counter()
    tags = Counter()
    for node in all_nodes:
        tags[node.name] += 1
        classes.update(compact_classes(node))

    ids = [node_record(n, i) for i, n in enumerate(all_nodes) if n.get("id")]
    buttons = [node_record(n, i) for i, n in enumerate(all_nodes) if n.name == "button"]
    details = [node_record(n, i) for i, n in enumerate(all_nodes) if n.name == "details"]
    main = soup.find("main") or soup.select_one(".main")
    body = soup.body
    topbar = soup.select_one(".topbar")

    report = {
        "file": args.html.name,
        "sha256": hashlib.sha256(args.html.read_bytes()).hexdigest(),
        "bytes": args.html.stat().st_size,
        "html_attributes": dict(soup.html.attrs) if soup.html else {},
        "body_attributes": dict(body.attrs) if body else {},
        "style_blocks": [hashlib.sha256(tag.get_text().encode("utf-8")).hexdigest() for tag in soup.find_all("style")],
        "script_blocks": [hashlib.sha256(tag.get_text().encode("utf-8")).hexdigest() for tag in soup.find_all("script")],
        "tag_counts": dict(tags),
        "class_counts": dict(classes.most_common()),
        "ids": ids,
        "buttons": buttons,
        "details": details,
        "topbar": node_record(topbar, -1) if topbar else None,
        "main": node_record(main, -1) if main else None,
        "body_direct_children": [
            {
                "tag": child.name,
                "id": child.get("id"),
                "classes": compact_classes(child),
                "text_preview": " ".join(child.get_text(" ", strip=True).split())[:160],
            }
            for child in body.find_all(recursive=False)
            if getattr(child, "name", None)
        ] if body else [],
        "candidate_content_nodes": [
            node_record(n, i)
            for i, n in enumerate(all_nodes)
            if any(c in {
                "hero", "paper-info", "metadata", "mode-pane", "qa-grid", "quick-figure-grid",
                "figure-index", "bilingual-unit", "paper-section", "figure-card", "table-card",
                "references", "reference-item", "review", "terms", "term-grid"
            } for c in compact_classes(n))
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
