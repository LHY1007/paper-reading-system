#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag


FORBIDDEN_PAPER_SPECIFIC_CLASSES = {
    "overview-grid",
    "overview-card",
    "method-flow",
    "paper-info-grid",
}

REQUIRED_STYLE_TOKENS = (
    ".metadata{",
    ".qa-grid",
    ".qa,",
    ".qa h3",
    ".story{",
)


def direct_children(node: Tag, name: str | None = None, class_name: str | None = None) -> list[Tag]:
    out: list[Tag] = []
    for child in node.find_all(recursive=False):
        if name and child.name != name:
            continue
        if class_name and class_name not in (child.get("class") or []):
            continue
        out.append(child)
    return out


def validate(path: Path) -> dict[str, Any]:
    html = path.read_text("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # The one-page overview is a fixed product component. Paper-specific generators
    # are not allowed to invent parallel markup/classes and hope global typography
    # happens to style them correctly.
    overview = soup.select_one("#overview-bilingual-folded")
    if overview is None:
        errors.append("missing #overview-bilingual-folded")
    else:
        cards = overview.select(":scope > section.card#overview-clone")
        if len(cards) != 1:
            errors.append("overview must contain exactly one direct section.card#overview-clone")
        else:
            card = cards[0]
            h2s = direct_children(card, "h2")
            if len(h2s) != 1:
                errors.append("overview-clone must contain exactly one direct h2")
            elif h2s[0].get("data-toc-en") != "Overview" or h2s[0].get("data-toc-zh") != "一页概览":
                errors.append("overview h2 must use the locked bilingual TOC attributes")

            grids = direct_children(card, "div", "qa-grid")
            if len(grids) != 1:
                errors.append("overview-clone must contain exactly one direct .qa-grid")
            else:
                qas = direct_children(grids[0], "article", "qa")
                if len(qas) != 6:
                    errors.append(f"overview must contain exactly six article.qa blocks; found {len(qas)}")
                for index, qa in enumerate(qas, 1):
                    hs = direct_children(qa, "h3")
                    ps = direct_children(qa, "p")
                    if len(hs) != 1 or len(ps) != 1:
                        errors.append(f"overview qa {index} must be exactly h3 + p")
                        continue
                    if hs[0].get("data-toc-ignore") != "1":
                        errors.append(f"overview qa {index} h3 lacks data-toc-ignore=1")
                    if not hs[0].get_text(" ", strip=True) or not ps[0].get_text(" ", strip=True):
                        errors.append(f"overview qa {index} contains empty question/answer text")
                    if qa.get("style"):
                        errors.append(f"overview qa {index} contains paper-specific inline style")

            method_h = direct_children(card, "h3")
            method_p = direct_children(card, "p")
            if len(method_h) != 1 or len(method_p) != 1:
                errors.append("overview method summary must use one direct h3 followed by one direct p")
            elif method_h[0].get("data-toc-ignore") != "1":
                errors.append("overview method h3 lacks data-toc-ignore=1")

            stories = direct_children(card, "div", "story")
            if len(stories) != 1:
                errors.append("overview must contain exactly one direct .story conclusion block")
            else:
                story = stories[0]
                if len(direct_children(story, "b")) != 1 or len(direct_children(story, "p")) != 1:
                    errors.append("overview .story must be exactly b + p")

    # Hero metadata must use the same component as every other paper. This prevents
    # labels/values from collapsing together (for example DOI10... or Received21...).
    info = soup.select_one(".hero > .paper-info")
    if info is None:
        errors.append("missing .hero > .paper-info")
    else:
        metadata = info.select(":scope > .metadata")
        if len(metadata) != 1:
            errors.append("paper-info must contain exactly one direct .metadata component")
        else:
            rows = direct_children(metadata[0], "div")
            if not rows:
                errors.append("metadata component is empty")
            for index, row in enumerate(rows, 1):
                labels = direct_children(row, "span")
                if len(labels) != 1 or not labels[0].get_text(" ", strip=True):
                    errors.append(f"metadata row {index} must contain one non-empty direct span label")
                value_text = " ".join(row.stripped_strings)
                label_text = labels[0].get_text(" ", strip=True) if labels else ""
                if not value_text or value_text == label_text:
                    errors.append(f"metadata row {index} has no value")
                if row.get("style"):
                    errors.append(f"metadata row {index} contains paper-specific inline style")

    for class_name in sorted(FORBIDDEN_PAPER_SPECIFIC_CLASSES):
        if soup.select_one("." + class_name) is not None:
            errors.append(f"forbidden paper-specific component class remains: .{class_name}")

    css = "\n".join(node.get_text() for node in soup.find_all("style"))
    for token in REQUIRED_STYLE_TOKENS:
        if token not in css:
            errors.append(f"locked component stylesheet token is missing: {token}")

    html_root = soup.html
    if html_root is not None:
        html_root["data-v083-component-format"] = html_root.get("data-v083-component-format") or "unmarked"

    return {
        "version": "v083-component-format-gate-1",
        "path": str(path),
        "passed": not errors,
        "errors": errors,
        "counts": {
            "overview_qa": len(soup.select("#overview-clone > .qa-grid > article.qa")),
            "metadata_rows": len(soup.select(".hero > .paper-info > .metadata > div")),
            "forbidden_custom_component_nodes": sum(len(soup.select("." + name)) for name in FORBIDDEN_PAPER_SPECIFIC_CLASSES),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail closed when a V0.8.3 reader invents paper-specific hero/overview markup instead of the locked reader components.")
    parser.add_argument("readers", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    results = [validate(path) for path in args.readers]
    report = {
        "version": "v083-component-format-batch-gate-1",
        "passed": all(item["passed"] for item in results),
        "readers": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
