#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag


def direct_tags(node: Tag) -> list[Tag]:
    return [x for x in node.find_all(recursive=False) if isinstance(x, Tag)]


def classes(node: Tag) -> tuple[str, ...]:
    return tuple(node.get("class") or [])


def names(nodes: Iterable[Tag]) -> list[str]:
    return [n.name + ("." + ".".join(classes(n)) if classes(n) else "") for n in nodes]


def check_overview(root: BeautifulSoup, selector: str, errors: list[str]) -> None:
    card = root.select_one(selector)
    if not card:
        errors.append(f"missing overview card {selector}")
        return
    children = direct_tags(card)
    expected = ["h2", "div.qa-grid", "h3", "p", "div.story"]
    if names(children) != expected:
        errors.append(f"{selector} direct structure {names(children)} != {expected}")
    grid = card.select_one(":scope > .qa-grid")
    qa = grid.select(":scope > .qa") if grid else []
    if len(qa) != 6:
        errors.append(f"{selector} requires exactly 6 qa cards, found {len(qa)}")
    for i, item in enumerate(qa, 1):
        if names(direct_tags(item)) != ["h3", "p"]:
            errors.append(f"{selector} qa {i} must be article.qa > h3+p")
        h3 = item.find("h3", recursive=False)
        if not h3 or h3.get("data-toc-ignore") != "1":
            errors.append(f"{selector} qa {i} h3 missing data-toc-ignore=1")
    story = card.select_one(":scope > .story")
    if story and names(direct_tags(story)) != ["b", "p"]:
        errors.append(f"{selector} story must contain b+p")


def check_index(root: BeautifulSoup, errors: list[str]) -> None:
    index = root.select_one("#figure-table-index")
    if not index:
        errors.append("missing #figure-table-index")
        return
    if names(direct_tags(index)) != ["summary", "div.figure-index-content"]:
        errors.append("figure index must contain summary + figure-index-content")
    content = index.select_one(":scope > .figure-index-content")
    children = direct_tags(content) if content else []
    if not children or children[0].name != "p":
        errors.append("figure index content must begin with explanatory p")
    for i, section in enumerate(content.select(":scope > .figure-index-section") if content else [], 1):
        if section.name != "section":
            errors.append(f"figure index group {i} must use section element")
        if names(direct_tags(section)) != ["a.section-jump", "div.figure-index-buttons"]:
            errors.append(f"figure index group {i} structure mismatch")
        link = section.select_one(":scope > .section-jump")
        if not link or not str(link.get("href", "")).startswith("#"):
            errors.append(f"figure index group {i} missing href section target")
        for button in section.select(":scope > .figure-index-buttons > .figure-ref"):
            if not button.get("data-target"):
                errors.append(f"figure index group {i} button missing data-target")
            if button.has_attr("data-figure"):
                errors.append(f"figure index group {i} uses obsolete data-figure")


def check_units(root: BeautifulSoup, errors: list[str]) -> None:
    units = root.select("#bilingual-pane .bilingual-unit")
    if not units:
        errors.append("no bilingual units")
    for i, unit in enumerate(units, 1):
        children = direct_tags(unit)
        core = children[:3]
        if names(core) != ["div.source-block", "div.translation-block.translation-content", "script.source-fragments"]:
            errors.append(f"unit {i} direct core mismatch: {names(core)}")
        uid = unit.get("data-unit-id")
        if not uid or unit.get("id") != "unit-" + uid or unit.get("data-paragraph-id") != uid:
            errors.append(f"unit {i} id/data-unit-id/data-paragraph-id mismatch")
        source = unit.select_one(":scope > .source-block")
        trans = unit.select_one(":scope > .translation-block.translation-content")
        if source and names(direct_tags(source)) != ["p"]:
            errors.append(f"unit {i} source-block must directly contain one p")
        if trans and names(direct_tags(trans)) != ["p"]:
            errors.append(f"unit {i} translation-block must directly contain one p")
        if unit.select("p p"):
            errors.append(f"unit {i} contains nested p")
        src = unit.select_one(":scope > script.source-fragments[type='application/json']")
        if not src:
            errors.append(f"unit {i} missing direct source-fragments JSON")
        for span in unit.select(".sentence-piece"):
            if not span.get("data-sentence-group") or span.get("data-sentence-index") is None:
                errors.append(f"unit {i} sentence-piece missing group/index")
        for term in unit.select(".term-pop"):
            required = ["data-term-id", "data-term-level", "data-tip", "role", "tabindex"]
            if any(term.get(x) is None for x in required):
                errors.append(f"unit {i} term-pop missing required attributes")
            if term.get("role") != "button" or term.get("tabindex") != "0":
                errors.append(f"unit {i} term-pop accessibility mismatch")
            if not term.select_one(":scope > .sentence-piece"):
                errors.append(f"unit {i} term-pop must wrap sentence-piece")
        if unit.select(":scope > .label") or unit.select(":scope > .source-block > .label") or unit.select(":scope > .translation-block > .label"):
            errors.append(f"unit {i} contains non-canonical language labels")


def check_card_heading(card: Tag, kind: str, errors: list[str], index: int) -> None:
    head = card.select_one(":scope > .figure-heading")
    content = card.select_one(":scope > .figure-content")
    if names(direct_tags(card)) != ["div.figure-heading", "div.figure-content"]:
        errors.append(f"{kind} card {index} direct structure mismatch")
    if not head or head.get("role") != "button" or head.get("tabindex") != "0" or not head.get("aria-label"):
        errors.append(f"{kind} card {index} heading accessibility mismatch")
    if not content or not content.has_attr("hidden"):
        errors.append(f"{kind} card {index} content must start hidden")
    title = head.find("div", recursive=False) if head else None
    if not title or names(direct_tags(title)) != ["span", "span.title-zh.translation-content"]:
        errors.append(f"{kind} card {index} title structure mismatch")


def check_figures(root: BeautifulSoup, errors: list[str]) -> None:
    cards = root.select("#bilingual-pane .figure-card:not(.table-card)")
    for i, card in enumerate(cards, 1):
        check_card_heading(card, "figure", errors, i)
        if card.name != "figure" or card.get("data-card-kind") != "figure":
            errors.append(f"figure card {i} tag/data-card-kind mismatch")
        controls = card.select_one(":scope > .figure-heading > .card-controls")
        order = [classes(x)[0] if classes(x) else x.name for x in direct_tags(controls)] if controls else []
        allowed = [["card-toggle", "zoom-button", "open-in-viewer", "figure-study-button"], ["card-toggle", "zoom-button", "open-in-viewer"]]
        if order not in allowed:
            errors.append(f"figure card {i} control order {order}")
        toggle = card.select_one(".card-toggle")
        viewer = card.select_one(".open-in-viewer")
        study = card.select_one(".figure-study-button")
        if not toggle or toggle.get("data-card") != card.get("id") or toggle.get("aria-expanded") != "false":
            errors.append(f"figure card {i} toggle target mismatch")
        if not viewer or viewer.get("data-target") != card.get("id") or viewer.has_attr("data-figure"):
            errors.append(f"figure card {i} viewer target mismatch")
        if study and study.get("data-figure-id") != card.get("id"):
            errors.append(f"figure card {i} study target mismatch")
        image = card.select_one(":scope > .figure-content > img.zoomable")
        for attr in ["src", "alt", "loading", "draggable", "data-source-page", "data-complete-page", "data-hires", "data-lossless", "data-source-render"]:
            if not image or image.get(attr) is None:
                errors.append(f"figure card {i} image missing {attr}")
        caps = card.select_one(":scope > .figure-content > .captions.bilingual-caption")
        if not caps or caps.get("data-required-module") != "bilingual-caption":
            errors.append(f"figure card {i} missing canonical captions module")
            continue
        if names(direct_tags(caps)) != ["div.caption.caption-en", "div.caption.caption-zh.translation-content"]:
            errors.append(f"figure card {i} caption structure mismatch")
        for side in ["en", "zh"]:
            box = caps.select_one(f":scope > .caption-{side}")
            if not box or box.get("data-required-field") != f"caption_{side}" or names(direct_tags(box)) != ["p"]:
                errors.append(f"figure card {i} caption {side} mismatch")


def check_tables(root: BeautifulSoup, errors: list[str]) -> None:
    cards = root.select("#bilingual-pane .table-card")
    for i, card in enumerate(cards, 1):
        check_card_heading(card, "table", errors, i)
        if card.name != "section" or classes(card) != ("figure-card", "table-card", "collapsed") or card.get("data-card-kind") != "table":
            errors.append(f"table card {i} tag/class/data-card-kind mismatch")
        controls = card.select_one(":scope > .figure-heading > .card-controls")
        order = [classes(x)[0] if classes(x) else x.name for x in direct_tags(controls)] if controls else []
        if order != ["card-toggle", "open-in-viewer"]:
            errors.append(f"table card {i} control order {order}")
        if card.select_one(".zoom-button,.figure-study-button"):
            errors.append(f"table card {i} must not have zoom/study")
        table = card.select_one(":scope > .figure-content > .table-wrap > table")
        if not table or not table.find("tbody", recursive=False):
            errors.append(f"table card {i} missing table/tbody")
        caps = card.select_one(":scope > .figure-content > .captions.bilingual-caption")
        if not caps or names(direct_tags(caps)) != ["div.caption.caption-en", "div.caption.caption-zh.translation-content"]:
            errors.append(f"table card {i} captions mismatch")


def check_sections_refs(root: BeautifulSoup, errors: list[str]) -> None:
    sections = root.select("#bilingual-pane > section.paper-section")
    for i, section in enumerate(sections, 1):
        h2 = section.find("h2", recursive=False)
        if not h2 or direct_tags(section)[0] is not h2:
            errors.append(f"paper section {i} must begin with direct h2")
        if not h2 or not h2.get("data-toc-en") or not h2.get("data-toc-zh"):
            errors.append(f"paper section {i} h2 missing bilingual toc attributes")
        if section.get("data-level") != "2" or not section.get("data-title"):
            errors.append(f"paper section {i} missing canonical data-level/title")
    refs = root.select("#references > .reference-item")
    for i, ref in enumerate(refs, 1):
        rid = ref.get("id", "")
        if not rid.startswith("reference-") or ref.get("data-annotation-block") != rid:
            errors.append(f"reference item {i} id/annotation mismatch")
        children = direct_tags(ref)
        if not children or children[0].name != "b" or any(x.name not in {"b", "a"} for x in children):
            errors.append(f"reference item {i} structure mismatch")


def validate(path: Path) -> dict:
    soup = BeautifulSoup(path.read_text("utf-8"), "html.parser")
    errors: list[str] = []
    check_overview(soup, "#quick-pane #overview", errors)
    check_overview(soup, "#overview-bilingual-folded > .card", errors)
    check_index(soup, errors)
    check_units(soup, errors)
    check_figures(soup, errors)
    check_tables(soup, errors)
    check_sections_refs(soup, errors)
    return {
        "file": path.name,
        "bilingual_units": len(soup.select("#bilingual-pane .bilingual-unit")),
        "figure_cards": len(soup.select("#bilingual-pane .figure-card:not(.table-card)")),
        "table_cards": len(soup.select("#bilingual-pane .table-card")),
        "references": len(soup.select("#references > .reference-item")),
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Validate exact V0.8.2 CANVAS component contracts")
    p.add_argument("html", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--diagnostic", action="store_true")
    a = p.parse_args()
    report = validate(a.html)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(text + "\n", "utf-8")
    if not report["passed"] and not a.diagnostic:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
