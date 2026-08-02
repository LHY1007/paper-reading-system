#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag


PLACEHOLDERS = {
    "title": "__V082_PAPER_TITLE__",
    "title_zh": "__V082_PAPER_TITLE_ZH__",
    "authors": "__V082_PAPER_AUTHORS__",
    "metadata_label": "__V082_METADATA_LABEL__",
    "metadata_value": "__V082_METADATA_VALUE__",
    "author": "__V082_AUTHOR__",
    "question": "__V082_OVERVIEW_QUESTION__",
    "answer": "__V082_OVERVIEW_ANSWER__",
    "method": "__V082_OVERVIEW_METHOD__",
    "story": "__V082_OVERVIEW_STORY__",
    "section": "__V082_SECTION__",
    "english": "__V082_ENGLISH_PARAGRAPH__",
    "chinese": "__V082_CHINESE_PARAGRAPH__",
    "figure": "__V082_FIGURE__",
    "table": "__V082_TABLE__",
    "caption_en": "__V082_CAPTION_EN__",
    "caption_zh": "__V082_CAPTION_ZH__",
    "reference": "__V082_REFERENCE__",
}

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


def require_one(soup: BeautifulSoup | Tag, selector: str) -> Tag:
    nodes = soup.select(selector)
    if len(nodes) != 1:
        raise RuntimeError(f"expected one {selector!r}, found {len(nodes)}")
    return nodes[0]


def set_text(node: Tag | None, value: str) -> None:
    if node is None:
        raise RuntimeError(f"missing node for placeholder {value}")
    node.clear()
    node.append(NavigableString(value))


def keep_first(parent: Tag, selector: str) -> Tag:
    exemplar = parent.select_one(selector)
    if exemplar is None:
        raise RuntimeError(f"missing exemplar {selector!r}")
    exemplar = copy.deepcopy(exemplar)
    parent.clear()
    parent.append(exemplar)
    return exemplar


def replace_const_expression(script: str, name: str, expression: str) -> str:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=", script)
    if not match:
        return script
    pos = match.end()
    quote: str | None = None
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
    raise RuntimeError(f"unterminated JavaScript assignment for {name}")


def patch_script(soup: BeautifulSoup, script_id: str, replacements: dict[str, str]) -> None:
    node = soup.find("script", id=script_id)
    if node is None:
        return
    text = node.get_text() or ""
    for name, expression in replacements.items():
        text = replace_const_expression(text, name, expression)
    node.string = text


def scrub_metadata(soup: BeautifulSoup) -> None:
    for meta in soup.find_all("meta"):
        key = str(meta.get("name") or meta.get("property") or "").lower()
        if key in PAPER_META_KEYS:
            meta["content"] = "__V082_PAPER_META__"
    for link in soup.find_all("link"):
        rel = {str(value).lower() for value in (link.get("rel") or [])}
        if "canonical" in rel:
            link["href"] = "__V082_ARTICLE_URL__"


def scrub_hero(soup: BeautifulSoup) -> None:
    hero = require_one(soup, ".hero")
    set_text(hero.find("h1", recursive=False), PLACEHOLDERS["title"])
    set_text(hero.select_one(":scope > .zh-title"), PLACEHOLDERS["title_zh"])
    set_text(hero.select_one(":scope > .paper-byline"), PLACEHOLDERS["authors"])

    info = require_one(hero, ":scope > .paper-info")
    metadata = require_one(info, ":scope > .metadata")
    row = keep_first(metadata, ":scope > div")
    label = row.find("span")
    value = row.find("b")
    set_text(label, PLACEHOLDERS["metadata_label"])
    if value is None:
        value = soup.new_tag("b")
        row.append(value)
    set_text(value, PLACEHOLDERS["metadata_value"])
    for child in list(row.contents):
        if isinstance(child, Tag) and child not in {label, value}:
            child.decompose()

    authors = require_one(info, ":scope > .author-list")
    heading = authors.find("h3", recursive=False)
    author_row = authors.find("div", recursive=False)
    if heading is None or author_row is None:
        raise RuntimeError("hero author-list lacks heading or author exemplar")
    heading_copy = copy.deepcopy(heading)
    author_copy = copy.deepcopy(author_row)
    authors.clear()
    set_text(heading_copy, "Authors and affiliations")
    author_copy.clear()
    bold = soup.new_tag("b")
    bold.append(NavigableString(PLACEHOLDERS["author"]))
    author_copy.append(bold)
    authors.append(heading_copy)
    authors.append(author_copy)


def scrub_overview(card: Tag) -> None:
    h2 = card.find("h2", recursive=False)
    if h2 is not None:
        set_text(h2, "一页概览")
    grid = require_one(card, ":scope > .qa-grid")
    qa = keep_first(grid, ":scope > .qa")
    set_text(qa.find("h3"), PLACEHOLDERS["question"])
    set_text(qa.find("p"), PLACEHOLDERS["answer"])

    direct = card.find_all(recursive=False)
    method_heading = next((node for node in direct if node.name == "h3"), None)
    method_text = next((node for node in direct if node.name == "p"), None)
    story = card.select_one(":scope > .story")
    if method_heading is not None:
        set_text(method_heading, "方法流程概括")
    if method_text is not None:
        set_text(method_text, PLACEHOLDERS["method"])
    if story is not None:
        bold = story.find("b")
        paragraph = story.find("p")
        if bold is not None:
            set_text(bold, "整体结论")
        if paragraph is not None:
            set_text(paragraph, PLACEHOLDERS["story"])
        elif not story.find_all(recursive=False):
            set_text(story, PLACEHOLDERS["story"])


def scrub_index(index: Tag) -> None:
    set_text(index.find("summary", recursive=False), "图表索引")
    body = require_one(index, ":scope > .figure-index-content")
    intro = body.find("p", recursive=False)
    section = body.select_one(":scope > .figure-index-section")
    if intro is None or section is None:
        raise RuntimeError("figure index lacks intro or section exemplar")
    intro_copy = copy.deepcopy(intro)
    section_copy = copy.deepcopy(section)
    body.clear()
    set_text(intro_copy, "按论文小节列出相关图表。小节标题用于跳转正文，图表按钮用于在右侧查看。")
    link = require_one(section_copy, ":scope > .section-jump")
    link["href"] = "#__V082_SECTION_ID__"
    set_text(link, PLACEHOLDERS["section"])
    buttons = require_one(section_copy, ":scope > .figure-index-buttons")
    button = keep_first(buttons, ":scope > .figure-ref")
    button["data-target"] = "__V082_ASSET_ID__"
    button.attrs.pop("data-figure", None)
    set_text(button, PLACEHOLDERS["figure"])
    body.append(intro_copy)
    body.append(section_copy)


def scrub_unit(unit: Tag) -> None:
    unit["id"] = "unit-__V082_UNIT_ID__"
    unit["data-unit-id"] = "__V082_UNIT_ID__"
    unit["data-paragraph-id"] = "__V082_UNIT_ID__"
    unit["data-source-pages"] = ""
    source = require_one(unit, ":scope > .source-block > p")
    translation_block = require_one(unit, ":scope > .translation-block")
    translation = translation_block.find("p", recursive=False)
    if translation is None:
        raise RuntimeError("bilingual unit lacks translation paragraph")
    set_text(source, PLACEHOLDERS["english"])
    set_text(translation, PLACEHOLDERS["chinese"])
    source["data-annotation-block"] = "source-__V082_UNIT_ID__"
    translation["data-annotation-block"] = "translation-__V082_UNIT_ID__"
    fragments = unit.select_one(":scope > script.source-fragments")
    if fragments is None:
        raise RuntimeError("bilingual unit lacks source-fragments script")
    fragments["type"] = "application/json"
    fragments.string = "[]"
    for extra in unit.select(":scope > .tip, :scope > .term-note"):
        extra.decompose()


def scrub_figure(card: Tag) -> None:
    card["id"] = "__V082_FIGURE_ID__"
    card["data-card-kind"] = "figure"
    card["data-source-page"] = ""
    card["data-title"] = PLACEHOLDERS["figure"]
    heading = require_one(card, ":scope > .figure-heading")
    title_wrap = heading.find("div", recursive=False)
    if title_wrap is None:
        raise RuntimeError("figure heading lacks title wrapper")
    spans = title_wrap.find_all("span", recursive=False)
    if len(spans) < 2:
        raise RuntimeError("figure heading lacks bilingual title spans")
    set_text(spans[0], PLACEHOLDERS["figure"])
    set_text(spans[1], f"（{PLACEHOLDERS['figure']}）")
    for selector in (".card-toggle", ".open-in-viewer", ".zoom-button", ".figure-study-button"):
        button = heading.select_one(selector)
        if button is not None:
            button["data-target"] = "__V082_FIGURE_ID__"
            button["data-card"] = "__V082_FIGURE_ID__"
            button["data-figure-id"] = "__V082_FIGURE_ID__"
            button.attrs.pop("data-figure", None)
    content = require_one(card, ":scope > .figure-content")
    image = content.find("img", recursive=False)
    if image is None:
        raise RuntimeError("figure card lacks image exemplar")
    image["src"] = ""
    image["alt"] = PLACEHOLDERS["figure"]
    image["data-source-page"] = ""
    image["data-complete-page"] = ""
    image.attrs.pop("srcset", None)
    caps = require_one(content, ":scope > .captions.bilingual-caption")
    cap_en = require_one(caps, ":scope > .caption-en")
    cap_zh = require_one(caps, ":scope > .caption-zh")
    set_text(cap_en.find("p"), PLACEHOLDERS["caption_en"])
    set_text(cap_zh.find("p"), PLACEHOLDERS["caption_zh"])


def scrub_table(card: Tag) -> None:
    card["id"] = "__V082_TABLE_ID__"
    card["data-card-kind"] = "table"
    card["data-source-page"] = ""
    card["data-title"] = PLACEHOLDERS["table"]
    heading = require_one(card, ":scope > .figure-heading")
    title_wrap = heading.find("div", recursive=False)
    if title_wrap is None:
        raise RuntimeError("table heading lacks title wrapper")
    spans = title_wrap.find_all("span", recursive=False)
    if len(spans) < 2:
        raise RuntimeError("table heading lacks bilingual title spans")
    set_text(spans[0], PLACEHOLDERS["table"])
    set_text(spans[1], f"（{PLACEHOLDERS['table']}）")
    table = require_one(card, ":scope > .figure-content .table-wrap table")
    table.clear()
    tbody = BeautifulSoup("<tbody><tr><td>__V082_TABLE_CELL__</td></tr></tbody>", "html.parser").tbody
    table.append(tbody)
    caps = require_one(card, ":scope > .figure-content > .captions.bilingual-caption")
    set_text(require_one(caps, ":scope > .caption-en").find("p"), PLACEHOLDERS["caption_en"])
    set_text(require_one(caps, ":scope > .caption-zh").find("p"), PLACEHOLDERS["caption_zh"])


def scrub_reference(reference: Tag) -> None:
    reference["id"] = "reference-__V082_REFERENCE_ID__"
    reference["data-annotation-block"] = "reference-__V082_REFERENCE_ID__"
    reference.clear()
    bold = reference.new_tag("b")
    bold.append(NavigableString("0."))
    reference.append(bold)
    reference.append(NavigableString(" " + PLACEHOLDERS["reference"]))


def scrub_bilingual_pane(soup: BeautifulSoup) -> None:
    pane = require_one(soup, "#bilingual-pane")
    folded = copy.deepcopy(require_one(pane, "#overview-bilingual-folded"))
    index = copy.deepcopy(require_one(pane, "#figure-table-index"))
    section = copy.deepcopy(require_one(pane, "section.paper-section"))
    unit = copy.deepcopy(require_one(pane, ".bilingual-unit"))
    figure = copy.deepcopy(require_one(pane, ".figure-card:not(.table-card)"))
    table = copy.deepcopy(require_one(pane, ".table-card"))
    reference = copy.deepcopy(require_one(pane, ".reference-item"))

    scrub_overview(require_one(folded, ":scope > .card"))
    scrub_index(index)
    scrub_unit(unit)
    scrub_figure(figure)
    scrub_table(table)
    scrub_reference(reference)

    section["id"] = "__V082_SECTION_ID__"
    section["data-level"] = "2"
    section["data-title"] = PLACEHOLDERS["section"]
    heading = section.find("h2", recursive=False)
    if heading is None:
        raise RuntimeError("paper section exemplar lacks h2")
    heading["data-toc-en"] = PLACEHOLDERS["section"]
    heading["data-toc-zh"] = PLACEHOLDERS["section"]
    set_text(heading, PLACEHOLDERS["section"])
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


def scrub_runtime_data(soup: BeautifulSoup) -> None:
    reference_data = soup.find("script", id="referenceData")
    if reference_data is not None:
        reference_data["type"] = "application/json"
        reference_data.string = "{}"
    review = soup.find("script", id="v080ReviewManifest")
    if review is not None:
        review["type"] = "application/json"
        review.string = json.dumps({"version": "0.8.2-frozen-shell", "expected": {}}, separators=(",", ":"))
    preview = soup.select_one("#crossRefPreviewStore")
    if preview is not None:
        preview.clear()
        preview["data-paper-key"] = "__V082_PAPER_KEY__"

    patch_script(soup, "canvas-reader-v060-script", {"V6_ASSETS": "[]", "V6_HOTSPOTS": "{}", "V6_STUDY": "{}"})
    patch_script(soup, "canvas-reader-v061-script", {"TERM_DATA": "[]"})
    patch_script(soup, "canvas-reader-v062-script", {"supported": "new Set([])"})
    patch_script(soup, "canvas-v077-script", {"STUDY_IDS": "new Set([])"})
    patch_script(soup, "canvas-v078-final-script", {"TERMS": "[]"})
    patch_script(soup, "canvas-v081-script", {"EXTRA_TERMS": "[]"})
    patch_script(soup, "canvas-v082-script", {"STUDY_IDS": "new Set([])", "ONTOLOGY": "[]"})


def freeze(source: Path, output: Path) -> dict[str, Any]:
    raw = source.read_text("utf-8")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    soup = BeautifulSoup(raw, "html.parser")
    normalized = soup.select_one('meta[name="v082-canonical-normalized"][content="1"]')
    if normalized is None:
        raise SystemExit("source must be the normalized V0.8.2 CANVAS master")

    soup.html["data-v082-template"] = "frozen-shell"
    soup.html["data-v082-template-version"] = "1"
    soup.title.string = PLACEHOLDERS["title"]
    soup.body["data-paper-key"] = "__V082_PAPER_KEY__"
    soup.body["data-mode"] = "bilingual"
    set_text(require_one(soup, "#topbar .brand"), PLACEHOLDERS["title"])
    scrub_metadata(soup)
    scrub_hero(soup)
    scrub_overview(require_one(soup, "#quick-pane #overview"))
    scope_note = soup.select_one("#quick-pane .reader-scope-note")
    if scope_note is not None:
        set_text(scope_note, "__V082_SCOPE_NOTE__")
    scrub_bilingual_pane(soup)
    scrub_runtime_data(soup)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(str(soup), "utf-8")
    output_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    output_raw = output.read_text("utf-8")
    return {
        "version": "v082-frozen-shell-1",
        "source": str(source),
        "source_sha256": source_sha,
        "source_bytes": source.stat().st_size,
        "output": str(output),
        "output_sha256": output_sha,
        "output_bytes": output.stat().st_size,
        "size_ratio": round(output.stat().st_size / max(1, source.stat().st_size), 6),
        "placeholder_count": output_raw.count("__V082_"),
        "component_exemplars": {
            "sections": len(soup.select("#bilingual-pane > section.paper-section")),
            "bilingual_units": len(soup.select("#bilingual-pane .bilingual-unit")),
            "figures": len(soup.select("#bilingual-pane .figure-card:not(.table-card)")),
            "tables": len(soup.select("#bilingual-pane .table-card")),
            "references": len(soup.select("#bilingual-pane .reference-item")),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a deterministic content-free shell from the normalized V0.8.2 CANVAS HTML")
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
