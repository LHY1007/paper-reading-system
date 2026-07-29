#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

import freeze_v082_canvas_shell as base


ORIGINAL_SCRUB_FIGURE = base.scrub_figure


def first(node: BeautifulSoup | Tag, selector: str) -> Tag:
    found = node.select_one(selector)
    if found is None:
        raise RuntimeError(f"missing exemplar {selector!r}")
    return found


def scrub_hero(soup: BeautifulSoup) -> None:
    hero = base.require_one(soup, ".hero")
    base.set_text(hero.find("h1", recursive=False), base.PLACEHOLDERS["title"])
    base.set_text(hero.select_one(":scope > .zh-title"), base.PLACEHOLDERS["title_zh"])
    base.set_text(hero.select_one(":scope > .paper-byline"), base.PLACEHOLDERS["authors"])

    info = base.require_one(hero, ":scope > .paper-info")
    metadata = base.require_one(info, ":scope > .metadata")
    row = base.keep_first(metadata, ":scope > div")
    label = row.find("span")
    value = row.find("b")
    base.set_text(label, base.PLACEHOLDERS["metadata_label"])
    if value is None:
        value = soup.new_tag("b")
        row.append(value)
    base.set_text(value, base.PLACEHOLDERS["metadata_value"])
    for child in list(row.contents):
        if isinstance(child, Tag) and child is not label and child is not value:
            child.decompose()

    authors = base.require_one(info, ":scope > .author-list")
    heading = authors.find("h3", recursive=False)
    author_row = authors.find("div", recursive=False)
    if heading is None or author_row is None:
        raise RuntimeError("hero author-list lacks heading or author exemplar")
    heading_copy = copy.deepcopy(heading)
    author_copy = copy.deepcopy(author_row)
    authors.clear()
    base.set_text(heading_copy, "Authors and affiliations")
    author_copy.clear()
    bold = soup.new_tag("b")
    bold.append(NavigableString(base.PLACEHOLDERS["author"]))
    author_copy.append(bold)
    authors.append(heading_copy)
    authors.append(author_copy)


def scrub_reference(reference: Tag) -> None:
    reference["id"] = "reference-__V082_REFERENCE_ID__"
    reference["data-annotation-block"] = "reference-__V082_REFERENCE_ID__"
    reference.clear()
    bold = BeautifulSoup("<b>0.</b>", "html.parser").b
    if bold is None:
        raise RuntimeError("failed to build reference exemplar")
    reference.append(bold)
    reference.append(NavigableString(" " + base.PLACEHOLDERS["reference"]))


def retain_only_data_attribute(button: Tag | None, name: str) -> None:
    if button is None:
        return
    for attr in ("data-card", "data-target", "data-figure-id", "data-figure"):
        button.attrs.pop(attr, None)
    button[name] = "__V082_FIGURE_ID__"


def scrub_figure(card: Tag) -> None:
    ORIGINAL_SCRUB_FIGURE(card)
    heading = base.require_one(card, ":scope > .figure-heading")
    retain_only_data_attribute(heading.select_one(".card-toggle"), "data-card")
    retain_only_data_attribute(heading.select_one(".open-in-viewer"), "data-target")
    retain_only_data_attribute(heading.select_one(".figure-study-button"), "data-figure-id")
    zoom = heading.select_one(".zoom-button")
    if zoom is not None:
        for attr in ("data-card", "data-target", "data-figure-id", "data-figure"):
            zoom.attrs.pop(attr, None)


def scrub_bilingual_pane(soup: BeautifulSoup) -> None:
    pane = base.require_one(soup, "#bilingual-pane")
    folded = copy.deepcopy(base.require_one(pane, "#overview-bilingual-folded"))
    index = copy.deepcopy(base.require_one(pane, "#figure-table-index"))
    section = copy.deepcopy(first(pane, "section.paper-section"))
    unit = copy.deepcopy(first(pane, ".bilingual-unit"))
    figure = copy.deepcopy(first(pane, ".figure-card:not(.table-card)"))
    table = copy.deepcopy(first(pane, ".table-card"))
    reference = copy.deepcopy(first(pane, ".reference-item"))

    base.scrub_overview(base.require_one(folded, ":scope > .card"))
    base.scrub_index(index)
    base.scrub_unit(unit)
    base.scrub_figure(figure)
    base.scrub_table(table)
    scrub_reference(reference)

    section["id"] = "__V082_SECTION_ID__"
    section["data-level"] = "2"
    section["data-title"] = base.PLACEHOLDERS["section"]
    heading = section.find("h2", recursive=False)
    if heading is None:
        raise RuntimeError("paper section exemplar lacks h2")
    heading["data-toc-en"] = base.PLACEHOLDERS["section"]
    heading["data-toc-zh"] = base.PLACEHOLDERS["section"]
    base.set_text(heading, base.PLACEHOLDERS["section"])
    for child in list(section.find_all(recursive=False)):
        if child is not heading:
            child.decompose()
    section.append(unit)
    section.append(figure)
    section.append(table)
    section.append(reference)

    pane.clear()
    pane.append(folded)
    pane.append(index)
    pane.append(section)


def clear_paper_images(soup: BeautifulSoup) -> int:
    changed = 0
    selectors = [
        "#quick-pane img[src^='data:image/']",
        ".hero img[src^='data:image/']",
        "#viewerContent img[src^='data:image/']",
        "#crossRefPreviewStore img[src^='data:image/']",
    ]
    for selector in selectors:
        for image in soup.select(selector):
            image["src"] = ""
            image.attrs.pop("srcset", None)
            changed += 1
    return changed


def freeze(source: Path, output: Path) -> dict[str, Any]:
    base.scrub_hero = scrub_hero
    base.scrub_reference = scrub_reference
    base.scrub_figure = scrub_figure
    base.scrub_bilingual_pane = scrub_bilingual_pane
    report = base.freeze(source, output)

    soup = BeautifulSoup(output.read_text("utf-8"), "html.parser")
    cleared_images = clear_paper_images(soup)
    output.write_text(str(soup), "utf-8")
    raw = output.read_text("utf-8")
    report.update(
        {
            "version": "v082-frozen-shell-2",
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "output_bytes": output.stat().st_size,
            "size_ratio": round(output.stat().st_size / max(1, source.stat().st_size), 6),
            "placeholder_count": raw.count("__V082_"),
            "paper_images_cleared": cleared_images,
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract the deterministic content-free V0.8.2 CANVAS shell")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = freeze(args.source, args.output)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")


if __name__ == "__main__":
    main()
