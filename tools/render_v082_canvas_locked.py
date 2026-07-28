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

DYNAMIC_SCRIPT_IDS = {
    "v080ReviewManifest",
    "canvas-reader-v060-script",
    "canvas-reader-v061-script",
    "canvas-v082-script",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def validate_manifest(data: dict, schema_path: Path | None) -> None:
    if schema_path:
        try:
            import jsonschema
        except ImportError as exc:
            raise SystemExit("jsonschema is required when --schema is supplied") from exc
        jsonschema.validate(data, load_json(schema_path))
    if data.get("schema_version") != "0.8.2":
        raise SystemExit("manifest schema_version must be 0.8.2")


def clear_keep(node: Tag, selector: str) -> Tag | None:
    keep = node.select_one(selector)
    keep_copy = copy.copy(keep) if keep else None
    node.clear()
    if keep_copy:
        node.append(keep_copy)
    return keep_copy


def tag(soup: BeautifulSoup, name: str, classes: str | None = None, text: str | None = None, **attrs) -> Tag:
    node = soup.new_tag(name)
    if classes:
        node["class"] = classes.split()
    for key, value in attrs.items():
        node[key.replace("_", "-")] = value
    if text is not None:
        node.append(NavigableString(text))
    return node


def append_plain(parent: Tag, text: str) -> None:
    parent.append(NavigableString(text))


def append_inline(soup: BeautifulSoup, parent: Tag, item: dict[str, Any]) -> None:
    text = item.get("text", "")
    term_id = item.get("term_id")
    figure_ids = item.get("figure_ids") or []
    section_id = item.get("section_id")

    if figure_ids:
        for index, figure_id in enumerate(figure_ids):
            if index:
                append_plain(parent, "、")
            button = tag(soup, "button", "figure-ref", text=text if len(figure_ids) == 1 else figure_id)
            button["type"] = "button"
            button["data-figure"] = figure_id
            parent.append(button)
    elif section_id:
        button = tag(soup, "button", "section-ref", text=text)
        button["type"] = "button"
        button["data-section"] = section_id
        parent.append(button)
    else:
        span = tag(soup, "span", "sentence-piece")
        if term_id:
            term = tag(soup, "span", "term-pop", text=text)
            term["data-term-id"] = term_id
            span.append(term)
        else:
            span.append(NavigableString(text))
        parent.append(span)

    for citation_id in item.get("citation_ids") or []:
        sup = tag(soup, "sup", "citation", text=citation_id)
        sup["data-ref"] = citation_id
        parent.append(sup)


def paragraph_block(soup: BeautifulSoup, block: dict) -> Tag:
    article = tag(soup, "article", "bilingual-unit")
    article["id"] = block["id"]

    source = tag(soup, "div", "source-block")
    source.append(tag(soup, "div", "label", text="ENGLISH"))
    p_en = tag(soup, "p")
    for inline in block["english"]:
        append_inline(soup, p_en, inline)
    source.append(p_en)
    fragments = tag(soup, "div", "source-fragments")
    fragments["hidden"] = "hidden"
    source_script = soup.new_tag("script")
    source_script["type"] = "application/json"
    source_script.string = json.dumps(block["source_fragments"], ensure_ascii=False)
    fragments.append(source_script)
    source.append(fragments)

    translation = tag(soup, "div", "translation-block")
    translation.append(tag(soup, "div", "label", text="中文"))
    content = tag(soup, "div", "translation-content")
    p_zh = tag(soup, "p")
    for inline in block["chinese"]:
        append_inline(soup, p_zh, inline)
    content.append(p_zh)
    translation.append(content)

    article.append(source)
    article.append(translation)
    if block.get("tip"):
        article.append(tag(soup, "div", "tip", text=block["tip"]))
    if block.get("term_note"):
        article.append(tag(soup, "div", "term-note", text=block["term_note"]))
    return article


def asset_buttons(soup: BeautifulSoup, asset: dict) -> Tag:
    controls = tag(soup, "div", "card-controls")
    toggle = tag(soup, "button", "card-toggle", text="展开")
    toggle["type"] = "button"
    controls.append(toggle)
    right = tag(soup, "button", "open-in-viewer", text="右侧")
    right["type"] = "button"
    right["data-figure"] = asset["id"]
    controls.append(right)
    if asset["kind"] == "figure":
        zoom = tag(soup, "button", "zoom-button", text="放大")
        zoom["type"] = "button"
        zoom["data-figure"] = asset["id"]
        controls.append(zoom)
        if asset.get("study"):
            study = tag(soup, "button", "figure-study-button", text="图表精读")
            study["type"] = "button"
            study["data-figure"] = asset["id"]
            controls.append(study)
    return controls


def figure_card(soup: BeautifulSoup, asset: dict) -> Tag:
    card = tag(soup, "figure", "figure-card collapsed")
    card["id"] = asset["id"]
    heading = tag(soup, "div", "figure-heading")
    title_wrap = tag(soup, "div")
    title_wrap.append(tag(soup, "b", text=asset["title_en"]))
    title_wrap.append(tag(soup, "div", "title-zh", text=asset["title_zh"]))
    heading.append(title_wrap)
    heading.append(asset_buttons(soup, asset))
    card.append(heading)

    content = tag(soup, "div", "figure-content")
    image = soup.new_tag("img")
    image["class"] = ["zoomable"]
    image["src"] = asset.get("image_src", "")
    image["alt"] = asset["title_en"]
    image["data-figure"] = asset["id"]
    content.append(image)
    captions = tag(soup, "div", "captions bilingual-caption")
    cap_en = tag(soup, "div", "caption caption-en")
    cap_en.append(tag(soup, "div", "label", text="English caption"))
    cap_en.append(tag(soup, "p", text=asset["caption_en"]))
    cap_zh = tag(soup, "div", "caption caption-zh")
    cap_zh.append(tag(soup, "div", "label", text="中文图注"))
    cap_zh.append(tag(soup, "p", text=asset["caption_zh"]))
    captions.append(cap_en)
    captions.append(cap_zh)
    content.append(captions)
    card.append(content)
    return card


def table_card(soup: BeautifulSoup, asset: dict) -> Tag:
    card = tag(soup, "section", "table-card collapsed")
    card["id"] = asset["id"]
    heading = tag(soup, "div", "figure-heading")
    title_wrap = tag(soup, "div")
    title_wrap.append(tag(soup, "b", text=asset["title_en"]))
    title_wrap.append(tag(soup, "div", "title-zh", text=asset["title_zh"]))
    heading.append(title_wrap)
    heading.append(asset_buttons(soup, asset))
    card.append(heading)
    content = tag(soup, "div", "figure-content")
    wrap = tag(soup, "div", "table-wrap")
    table_node = soup.new_tag("table")
    headers = (asset.get("table") or {}).get("headers") or []
    rows = (asset.get("table") or {}).get("rows") or []
    if headers:
        thead = soup.new_tag("thead")
        tr = soup.new_tag("tr")
        for value in headers:
            tr.append(tag(soup, "th", text=value))
        thead.append(tr)
        table_node.append(thead)
    tbody = soup.new_tag("tbody")
    for row in rows:
        tr = soup.new_tag("tr")
        for value in row:
            tr.append(tag(soup, "td", text=value))
        tbody.append(tr)
    table_node.append(tbody)
    wrap.append(table_node)
    content.append(wrap)
    captions = tag(soup, "div", "captions bilingual-caption")
    captions.append(tag(soup, "div", "caption caption-en", text=asset["caption_en"]))
    captions.append(tag(soup, "div", "caption caption-zh", text=asset["caption_zh"]))
    content.append(captions)
    card.append(content)
    return card


def overview_content(soup: BeautifulSoup, overview: dict, include_heading: bool = True) -> list[Tag]:
    nodes: list[Tag] = []
    if include_heading:
        nodes.append(tag(soup, "h2", text="一页概览"))
    grid = tag(soup, "div", "qa-grid")
    for item in overview["qa"]:
        qa = tag(soup, "div", "qa")
        qa.append(tag(soup, "h3", text=item["question"]))
        qa.append(tag(soup, "p", text=item["answer"]))
        grid.append(qa)
    nodes.append(grid)
    nodes.append(tag(soup, "div", "story", text=overview["story"]))
    return nodes


def build_figure_index(soup: BeautifulSoup, assets: list[dict]) -> Tag:
    details = tag(soup, "details", "figure-index")
    details["id"] = "figure-table-index"
    details.append(tag(soup, "summary", text="图表预览"))
    body = tag(soup, "div", "figure-index-content")
    groups: dict[str, list[dict]] = {}
    for asset in assets:
        groups.setdefault(asset.get("group") or "main", []).append(asset)
    for group, items in groups.items():
        section = tag(soup, "div", "figure-index-section")
        section.append(tag(soup, "a", "section-jump", text=group))
        buttons = tag(soup, "div", "figure-index-buttons")
        for asset in items:
            button = tag(soup, "button", "figure-ref", text=asset["title_en"])
            button["type"] = "button"
            button["data-figure"] = asset["id"]
            buttons.append(button)
        section.append(buttons)
        body.append(section)
    details.append(body)
    return details


def replace_const_expression(script: str, name: str, expression: str) -> str:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=", script)
    if not match:
        raise ValueError(f"missing JavaScript assignment for {name}")
    pos = match.end()
    quote = None
    escaped = False
    depth = 0
    i = pos
    while i < len(script):
        ch = script[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        else:
            if ch in "'\"`":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ";" and depth == 0:
                return script[:pos] + expression + script[i:]
        i += 1
    raise ValueError(f"unterminated JavaScript assignment for {name}")


def patch_dynamic_scripts(soup: BeautifulSoup, manifest: dict, assets: list[dict]) -> None:
    asset_briefs = [
        {"id": a["id"], "group": a.get("group", "main"), "title": a["title_en"], "zh": a["title_zh"], "intro": a["intro"]}
        for a in assets
    ]
    study_map = {a["id"]: a["study"] for a in assets if a.get("study") and a["kind"] == "figure"}
    study_ids = list(study_map)
    ontology = manifest.get("terms") or []

    v060 = soup.find("script", id="canvas-reader-v060-script")
    if v060:
        text = v060.get_text()
        text = replace_const_expression(text, "V6_ASSETS", json.dumps(asset_briefs, ensure_ascii=False, separators=(",", ":")))
        text = replace_const_expression(text, "V6_HOTSPOTS", "{}")
        text = replace_const_expression(text, "V6_STUDY", json.dumps(study_map, ensure_ascii=False, separators=(",", ":")))
        v060.string = text

    v061 = soup.find("script", id="canvas-reader-v061-script")
    if v061:
        text = v061.get_text()
        text = replace_const_expression(text, "TERM_DATA", json.dumps(ontology, ensure_ascii=False, separators=(",", ":")))
        text = text.replace("'paper-reader-canvas-v076'", "'paper-reader-'+document.body.dataset.paperKey+'-v076'")
        v061.string = text

    v082 = soup.find("script", id="canvas-v082-script")
    if v082:
        text = v082.get_text()
        text = replace_const_expression(text, "STUDY_IDS", "new Set(" + json.dumps(study_ids, ensure_ascii=False) + ")")
        text = replace_const_expression(text, "ONTOLOGY", json.dumps(ontology, ensure_ascii=False, separators=(",", ":")))
        v082.string = text


def update_review_manifest(soup: BeautifulSoup, assets: list[dict]) -> None:
    tag_node = soup.find("script", id="v080ReviewManifest")
    if not tag_node:
        return
    figure_ids = [a["id"] for a in assets if a["kind"] == "figure"]
    table_ids = [a["id"] for a in assets if a["kind"] == "table"]
    data = {
        "version": "0.8.2-locked",
        "base_version": "0.8.2-CANVAS",
        "content_hashes": {},
        "expected": {
            "figure_cards": len(figure_ids),
            "table_cards": len(table_ids),
            "study_buttons": sum(bool(a.get("study")) and a["kind"] == "figure" for a in assets),
            "figure_ids": figure_ids,
            "table_ids": table_ids,
        },
    }
    tag_node.string = json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def render(canonical: Path, manifest_path: Path, output: Path, schema: Path | None) -> dict:
    manifest = load_json(manifest_path)
    validate_manifest(manifest, schema)
    raw = canonical.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    paper = manifest["paper"]
    assets = manifest["assets"]
    asset_by_id = {a["id"]: a for a in assets}

    soup.title.string = f"{paper['title_en']} – V0.8.2 CANVAS Locked"
    soup.body["data-paper-key"] = paper["key"]
    soup.body["data-mode"] = "bilingual"
    brand = soup.select_one("#topbar .brand")
    if brand:
        brand.string = f"{paper['journal']} · {paper['title_en']}"

    hero = soup.select_one(".hero")
    if hero:
        h1 = hero.find("h1")
        if h1:
            h1.string = paper["title_en"]
        zh = hero.select_one(".zh-title")
        if zh:
            zh.string = paper["title_zh"]
        byline = hero.select_one(".paper-byline")
        if byline:
            byline.string = ", ".join(paper["authors"])
        info = hero.select_one(".paper-info")
        if info:
            summary = info.find("summary")
            summary_copy = copy.copy(summary) if summary else tag(soup, "summary", text="论文信息")
            info.clear()
            info.append(summary_copy)
            metadata = tag(soup, "div", "metadata")
            fixed = [
                ("期刊", paper["journal"]),
                ("年份", str(paper["year"])),
                ("DOI", paper["doi"]),
                ("PDF", f"{paper['pages']} 页"),
            ]
            fixed.extend((x["label"], x["value"]) for x in paper.get("metadata") or [])
            for label, value in fixed:
                item = tag(soup, "div")
                item.append(tag(soup, "span", text=label))
                item.append(NavigableString(value))
                metadata.append(item)
            info.append(metadata)
            authors = tag(soup, "div", "author-list")
            for author in paper["authors"]:
                authors.append(tag(soup, "span", "author-tag", text=author))
            info.append(authors)

    quick = soup.select_one("#quick-pane")
    if quick:
        overview = quick.select_one("#overview")
        if overview:
            overview.clear()
            for node in overview_content(soup, manifest["overview"]):
                overview.append(node)
        scope = quick.select_one(".reader-scope-note")
        if scope:
            scope.string = manifest["overview"].get("scope_note", "本文阅读器按原文段落、图表和参考文献完整生成。")

    bilingual = soup.select_one("#bilingual-pane")
    if not bilingual:
        raise SystemExit("canonical template missing #bilingual-pane")
    bilingual.clear()
    folded = tag(soup, "details", "overview-folded")
    folded["id"] = "overview-bilingual-folded"
    folded.append(tag(soup, "summary", text="一页概览与方法流程概括"))
    folded_body = tag(soup, "div", "card")
    for node in overview_content(soup, manifest["overview"]):
        folded_body.append(node)
    folded.append(folded_body)
    bilingual.append(folded)
    bilingual.append(build_figure_index(soup, assets))

    for section_data in manifest["sections"]:
        section = tag(soup, "section", "paper-section")
        section["id"] = section_data["id"]
        section.append(tag(soup, "h2", text=f"{section_data['title_en']}（{section_data['title_zh']}）"))
        for block in section_data["blocks"]:
            if block["type"] == "paragraph":
                section.append(paragraph_block(soup, block))
            else:
                asset = asset_by_id[block["asset_id"]]
                section.append(figure_card(soup, asset) if asset["kind"] == "figure" else table_card(soup, asset))
        bilingual.append(section)

    references = tag(soup, "section", "paper-section")
    references["id"] = "references"
    references.append(tag(soup, "h2", text="References（参考文献）"))
    for ref in manifest["references"]:
        item = tag(soup, "div", "reference-item")
        item["id"] = "ref-" + ref["id"]
        item["data-ref"] = ref["id"]
        item.append(tag(soup, "b", text=ref["id"] + ". "))
        if ref.get("url"):
            link = tag(soup, "a", text=ref["text"])
            link["href"] = ref["url"]
            link["target"] = "_blank"
            link["rel"] = "noopener"
            item.append(link)
        else:
            item.append(NavigableString(ref["text"]))
        references.append(item)
    bilingual.append(references)

    patch_dynamic_scripts(soup, manifest, assets)
    update_review_manifest(soup, assets)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(str(soup), "utf-8")
    return {
        "output": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sections": len(manifest["sections"]),
        "paragraphs": sum(sum(b["type"] == "paragraph" for b in s["blocks"]) for s in manifest["sections"]),
        "assets": len(assets),
        "references": len(manifest["references"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render paper data into the immutable V0.8.2 CANVAS reader shell")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    args = parser.parse_args()
    report = render(args.canonical, args.manifest, args.output, args.schema)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
