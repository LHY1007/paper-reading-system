#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag
from render_v082_canvas_locked import load_json, patch_dynamic_scripts, update_review_manifest, validate_manifest


def clone(node: Tag) -> Tag:
    return copy.deepcopy(node)


def set_text(node: Tag | None, value: str) -> None:
    if node is None:
        return
    node.clear()
    node.append(NavigableString(value))


def term_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {x["id"]: x for x in manifest.get("terms", [])}


def sentence(soup: BeautifulSoup, text: str, group: str, index: int) -> Tag:
    n = soup.new_tag("span")
    n["class"] = ["sentence-piece"]
    n["data-sentence-group"] = group
    n["data-sentence-index"] = str(index)
    n.append(NavigableString(text))
    return n


def append_inline(soup: BeautifulSoup, parent: Tag, items: list[dict[str, Any]], unit: str, prefix: str, terms: dict[str, dict[str, Any]]) -> None:
    parent.clear()
    for i, item in enumerate(items):
        text = item.get("text", "")
        group = f"sp-{prefix}-{unit}-{i}"
        if item.get("figure_ids"):
            ids = item["figure_ids"]
            for j, asset_id in enumerate(ids):
                if j:
                    parent.append(NavigableString("、"))
                b = soup.new_tag("button")
                b["class"] = ["figure-ref"]
                b["type"] = "button"
                b["data-target"] = asset_id
                b.append(NavigableString(text if len(ids) == 1 else asset_id))
                parent.append(b)
        elif item.get("section_id"):
            b = soup.new_tag("button")
            b["class"] = ["section-ref"]
            b["type"] = "button"
            b["data-target"] = item["section_id"]
            b.append(NavigableString(text))
            parent.append(b)
        elif item.get("term_id"):
            td = terms.get(item["term_id"], {})
            outer = soup.new_tag("span")
            outer["class"] = ["term-pop"]
            outer["data-term-id"] = item["term_id"]
            outer["data-term-level"] = str(td.get("level", item.get("level", 2)))
            outer["data-tip"] = td.get("definition_zh", item.get("definition_zh", ""))
            category = td.get("category", item.get("category"))
            if category:
                outer["data-term-category"] = category
            outer["role"] = "button"
            outer["tabindex"] = "0"
            outer.append(sentence(soup, text, group, i))
            parent.append(outer)
        else:
            parent.append(sentence(soup, text, group, i))
        for ref_id in item.get("citation_ids", []):
            sup = soup.new_tag("sup")
            sup["class"] = ["citation"]
            sup["data-ref"] = str(ref_id)
            sup.append(NavigableString(str(ref_id)))
            parent.append(sup)


def fill_overview(card: Tag, overview: dict[str, Any]) -> None:
    set_text(card.find("h2", recursive=False), "一页概览")
    h2 = card.find("h2", recursive=False)
    if h2:
        h2["data-toc-en"] = "Overview"
        h2["data-toc-zh"] = "一页概览"
    grid = card.select_one(":scope > .qa-grid")
    if grid:
        exemplar = grid.select_one(":scope > .qa")
        grid.clear()
        for item in overview["qa"]:
            qa = clone(exemplar)
            set_text(qa.find("h3"), item["question"])
            set_text(qa.find("p"), item["answer"])
            qa.find("h3")["data-toc-ignore"] = "1"
            grid.append(qa)
    direct = card.find_all(recursive=False)
    method_h = next((x for x in direct if x.name == "h3"), None)
    method_p = next((x for x in direct if x.name == "p"), None)
    story = card.select_one(":scope > .story")
    if method_h:
        method_h["data-toc-ignore"] = "1"
        set_text(method_h, overview.get("method_heading", "方法流程概括"))
    set_text(method_p, overview.get("method", overview["story"]))
    if story:
        set_text(story.find("b"), overview.get("story_label", "整体结论"))
        set_text(story.find("p"), overview["story"])


def fill_hero(hero: Tag, paper: dict[str, Any]) -> None:
    set_text(hero.find("h1", recursive=False), paper["title_en"])
    set_text(hero.select_one(":scope > .zh-title"), paper["title_zh"])
    set_text(hero.select_one(":scope > .paper-byline"), ", ".join(paper["authors"]))
    info = hero.select_one(":scope > .paper-info")
    if not info:
        return
    metadata = info.select_one(":scope > .metadata")
    if metadata:
        ex = metadata.find("div", recursive=False)
        metadata.clear()
        rows = [
            ("Journal", paper["journal"], True),
            ("Publisher", paper.get("publisher", ""), True),
            ("DOI", paper["doi"], True),
            ("Article type", paper.get("article_type", "Article"), True),
            ("Publication timeline", paper.get("publication_timeline", str(paper["year"])), True),
            ("Volume, issue and pages", paper.get("citation", f"PDF {paper['pages']} pages"), True),
        ]
        rows += [(x["label"], x["value"], bool(x.get("bold"))) for x in paper.get("metadata", [])]
        for label, value, bold in rows:
            row = clone(ex)
            row.clear()
            lab = info.new_tag("span")
            lab.append(NavigableString(label))
            row.append(lab)
            if bold:
                val = info.new_tag("b")
                val.append(NavigableString(value))
                row.append(val)
            else:
                row.append(NavigableString(value))
            metadata.append(row)
    authors = info.select_one(":scope > .author-list")
    if authors:
        head = clone(authors.find("h3", recursive=False))
        ex = authors.find("div", recursive=False)
        authors.clear()
        set_text(head, "Authors and affiliations")
        authors.append(head)
        for author in paper["authors"]:
            row = clone(ex)
            row.clear()
            b = info.new_tag("b")
            b.append(NavigableString(author))
            row.append(b)
            authors.append(row)
        if paper.get("affiliations"):
            authors.append(info.new_tag("hr"))
            for i, affiliation in enumerate(paper["affiliations"], 1):
                row = info.new_tag("div")
                sup = info.new_tag("sup")
                sup.append(NavigableString(str(i)))
                row.append(sup)
                row.append(NavigableString(" " + affiliation))
                authors.append(row)
        for label, value in [("Correspondence", paper.get("correspondence")), ("Lead contact", paper.get("lead_contact")), ("Article link", paper.get("article_url"))]:
            if value:
                p = info.new_tag("p")
                b = info.new_tag("b")
                b.append(NavigableString(label + ": "))
                p.append(b)
                p.append(NavigableString(value))
                authors.append(p)


def fill_index(details: Tag, sections: list[dict[str, Any]], assets: dict[str, dict[str, Any]]) -> None:
    set_text(details.find("summary", recursive=False), "图表索引")
    body = details.select_one(":scope > .figure-index-content")
    if not body:
        return
    intro = clone(body.find("p", recursive=False))
    sec_ex = body.select_one(":scope > .figure-index-section")
    body.clear()
    set_text(intro, "按论文小节列出相关图表。小节标题用于跳转正文，图表按钮用于在右侧查看。")
    body.append(intro)
    for section in sections:
        ids = [b["asset_id"] for b in section["blocks"] if b["type"] == "asset"]
        if not ids:
            continue
        sec = clone(sec_ex)
        link = sec.select_one(":scope > .section-jump")
        link["href"] = "#" + section["id"]
        set_text(link, f"{section['title_en']}（{section['title_zh']}）")
        buttons = sec.select_one(":scope > .figure-index-buttons")
        b_ex = buttons.select_one(":scope > .figure-ref")
        buttons.clear()
        for asset_id in ids:
            a = assets[asset_id]
            b = clone(b_ex)
            b["data-target"] = asset_id
            b.attrs.pop("data-figure", None)
            set_text(b, f"{a['title_en']}（{a['title_zh']}）")
            buttons.append(b)
        body.append(sec)


def fill_unit(template: Tag, soup: BeautifulSoup, block: dict[str, Any], terms: dict[str, dict[str, Any]]) -> Tag:
    node = clone(template)
    uid = block["id"]
    node["id"] = "unit-" + uid
    node["data-unit-id"] = uid
    node["data-paragraph-id"] = uid
    node["data-source-pages"] = str(block.get("source_pages", ""))
    en = node.select_one(":scope > .source-block > p")
    zh_block = node.select_one(":scope > .translation-block")
    zh = zh_block.find("p", recursive=False)
    en["data-annotation-block"] = "source-" + uid
    zh_block["class"] = ["translation-block", "translation-content"]
    zh["data-annotation-block"] = "translation-" + uid
    append_inline(soup, en, block["english"], uid, "body", terms)
    append_inline(soup, zh, block["chinese"], uid, "body", terms)
    src = node.select_one(":scope > script.source-fragments")
    src["type"] = "application/json"
    src.string = json.dumps(block["source_fragments"], ensure_ascii=False)
    for extra in node.select(":scope > .tip, :scope > .term-note"):
        extra.decompose()
    for cls, value in [("tip", block.get("tip")), ("term-note", block.get("term_note"))]:
        if value:
            x = soup.new_tag("div")
            x["class"] = [cls]
            x.append(NavigableString(value))
            node.append(x)
    return node


def fill_figure(template: Tag, soup: BeautifulSoup, asset: dict[str, Any], terms: dict[str, dict[str, Any]]) -> Tag:
    node = clone(template)
    aid = asset["id"]
    node["id"] = aid
    node["data-card-kind"] = "figure"
    node["data-source-page"] = str(asset.get("source_page", ""))
    node["data-title"] = f"{asset['title_en']}（{asset['title_zh']}）"
    head = node.select_one(":scope > .figure-heading")
    head["aria-label"] = "打开或关闭该图"
    head["role"] = "button"
    head["tabindex"] = "0"
    spans = head.find("div", recursive=False).find_all("span", recursive=False)
    set_text(spans[0], asset["title_en"])
    spans[1]["class"] = ["title-zh", "translation-content"]
    set_text(spans[1], f"（{asset['title_zh']}）")
    toggle = head.select_one(".card-toggle")
    toggle["data-card"] = aid
    toggle["aria-expanded"] = "false"
    set_text(toggle, "下方展开")
    viewer = head.select_one(".open-in-viewer")
    viewer["data-target"] = aid
    viewer.attrs.pop("data-figure", None)
    set_text(viewer, "右侧展开")
    study = head.select_one(".figure-study-button")
    if asset.get("study"):
        study["data-figure-id"] = aid
        study.attrs.pop("data-figure", None)
        set_text(study, "图表精读")
    else:
        study.decompose()
    content = node.select_one(":scope > .figure-content")
    content["hidden"] = ""
    image = content.find("img", recursive=False)
    image["src"] = asset.get("image_src", "")
    image["alt"] = asset["title_en"]
    image["loading"] = "lazy"
    image["draggable"] = "false"
    image["data-source-page"] = str(asset.get("source_page", ""))
    image["data-complete-page"] = str(asset.get("source_page", ""))
    image["data-hires"] = str(bool(asset.get("hires", True))).lower()
    image["data-lossless"] = asset.get("image_format", "webp")
    image["data-source-render"] = asset.get("source_render", "pdf-region")
    image.attrs.pop("data-figure", None)
    caps = content.select_one(":scope > .captions.bilingual-caption")
    caps["data-required-module"] = "bilingual-caption"
    for side, text in [("en", asset["caption_en"]), ("zh", asset["caption_zh"])]:
        box = caps.select_one(f":scope > .caption-{side}")
        box["data-required-field"] = f"caption_{side}"
        if side == "zh":
            box["class"] = ["caption", "caption-zh", "translation-content"]
        p = box.find("p")
        p["data-annotation-block"] = f"caption-{side}-{aid}"
        append_inline(soup, p, [{"text": text}], aid, "caption", terms)
    return node


def fill_table(template: Tag, soup: BeautifulSoup, asset: dict[str, Any]) -> Tag:
    node = clone(template)
    aid = asset["id"]
    node["id"] = aid
    node["class"] = ["figure-card", "table-card", "collapsed"]
    node["data-card-kind"] = "table"
    node["data-source-page"] = str(asset.get("source_page", ""))
    node["data-title"] = f"{asset['title_en']}（{asset['title_zh']}）"
    head = node.select_one(":scope > .figure-heading")
    head["aria-label"] = "打开或关闭该表格"
    head["role"] = "button"
    head["tabindex"] = "0"
    spans = head.find("div", recursive=False).find_all("span", recursive=False)
    set_text(spans[0], asset["title_en"])
    spans[1]["class"] = ["title-zh", "translation-content"]
    set_text(spans[1], f"（{asset['title_zh']}）")
    toggle = head.select_one(".card-toggle")
    toggle["data-card"] = aid
    toggle["aria-expanded"] = "false"
    set_text(toggle, "下方展开")
    viewer = head.select_one(".open-in-viewer")
    viewer["data-target"] = aid
    viewer.attrs.pop("data-figure", None)
    set_text(viewer, "右侧展开")
    for x in head.select(".zoom-button,.figure-study-button"):
        x.decompose()
    content = node.select_one(":scope > .figure-content")
    content["hidden"] = ""
    table = content.select_one(".table-wrap table")
    table.clear()
    data = asset.get("table") or {}
    if data.get("headers"):
        thead = soup.new_tag("thead")
        tr = soup.new_tag("tr")
        for value in data["headers"]:
            th = soup.new_tag("th")
            th.append(NavigableString(str(value)))
            tr.append(th)
        thead.append(tr)
        table.append(thead)
    tbody = soup.new_tag("tbody")
    for row in data.get("rows", []):
        tr = soup.new_tag("tr")
        for value in row:
            td = soup.new_tag("td")
            td.append(NavigableString(str(value)))
            tr.append(td)
        tbody.append(tr)
    table.append(tbody)
    caps = content.select_one(":scope > .captions.bilingual-caption")
    caps["data-required-module"] = "bilingual-caption"
    for side, text in [("en", asset["caption_en"]), ("zh", asset["caption_zh"])]:
        box = caps.select_one(f":scope > .caption-{side}")
        box["data-required-field"] = f"caption_{side}"
        if side == "zh":
            box["class"] = ["caption", "caption-zh", "translation-content"]
        p = box.find("p")
        p["data-annotation-block"] = f"caption-{side}-{aid}"
        set_text(p, text)
    return node


def fill_reference(template: Tag, soup: BeautifulSoup, ref: dict[str, Any]) -> Tag:
    node = clone(template)
    rid = str(ref["id"])
    node["id"] = "reference-" + rid
    node["data-annotation-block"] = "reference-" + rid
    node.clear()
    b = soup.new_tag("b")
    b.append(NavigableString(rid + "."))
    node.append(b)
    node.append(NavigableString(" "))
    if ref.get("url"):
        a = soup.new_tag("a")
        a["href"] = ref["url"]
        a["rel"] = "noopener"
        a["target"] = "_blank"
        a.append(NavigableString(ref["text"]))
        node.append(a)
    else:
        node.append(NavigableString(ref["text"]))
    return node


def render(canonical: Path, manifest_path: Path, output: Path, schema: Path | None) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    validate_manifest(manifest, schema)
    soup = BeautifulSoup(canonical.read_text("utf-8"), "html.parser")
    paper, assets = manifest["paper"], manifest["assets"]
    assets_by_id, terms = {a["id"]: a for a in assets}, term_map(manifest)
    section_ex = soup.select_one("section.paper-section")
    unit_ex = soup.select_one(".bilingual-unit")
    figure_ex = soup.select_one(".figure-card:not(.table-card)")
    table_ex = soup.select_one(".table-card")
    ref_ex = soup.select_one(".reference-item")
    if not all([section_ex, unit_ex, figure_ex, table_ex, ref_ex]):
        raise SystemExit("canonical CANVAS lacks component exemplars")

    soup.title.string = f"{paper['title_en']} – V0.8.2 CANVAS"
    soup.body["data-paper-key"] = paper["key"]
    soup.body["data-mode"] = "bilingual"
    set_text(soup.select_one("#topbar .brand"), f"{paper['journal']} · {paper['title_en']}")
    fill_hero(soup.select_one(".hero"), paper)
    fill_overview(soup.select_one("#quick-pane #overview"), manifest["overview"])
    set_text(soup.select_one("#quick-pane .reader-scope-note"), manifest["overview"].get("scope_note", "本文阅读器按原文段落、图表和参考文献完整生成。"))

    bilingual = soup.select_one("#bilingual-pane")
    folded = clone(soup.select_one("#overview-bilingual-folded"))
    index = clone(soup.select_one("#figure-table-index"))
    bilingual.clear()
    fill_overview(folded.select_one(":scope > .card"), manifest["overview"])
    bilingual.append(folded)
    fill_index(index, manifest["sections"], assets_by_id)
    bilingual.append(index)

    for sd in manifest["sections"]:
        section = clone(section_ex)
        section["id"] = sd["id"]
        section["data-level"] = str(sd.get("level", 2))
        section["data-title"] = f"{sd['title_zh']}（{sd['title_en']}）"
        h2 = section.find("h2", recursive=False)
        h2["data-toc-en"] = sd["title_en"]
        h2["data-toc-zh"] = sd["title_zh"]
        set_text(h2, f"{sd['title_zh']}（{sd['title_en']}）")
        for child in list(section.find_all(recursive=False)):
            if child is not h2:
                child.decompose()
        for block in sd["blocks"]:
            if block["type"] == "paragraph":
                section.append(fill_unit(unit_ex, soup, block, terms))
            else:
                asset = assets_by_id[block["asset_id"]]
                section.append(fill_figure(figure_ex, soup, asset, terms) if asset["kind"] == "figure" else fill_table(table_ex, soup, asset))
        bilingual.append(section)

    refs = clone(section_ex)
    refs["id"] = "references"
    refs["data-level"] = "2"
    refs["data-title"] = "参考文献（REFERENCES）"
    h2 = refs.find("h2", recursive=False)
    h2["data-toc-en"], h2["data-toc-zh"] = "REFERENCES", "参考文献"
    set_text(h2, "参考文献（REFERENCES）")
    for child in list(refs.find_all(recursive=False)):
        if child is not h2:
            child.decompose()
    for ref in manifest["references"]:
        refs.append(fill_reference(ref_ex, soup, ref))
    bilingual.append(refs)

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
    p = argparse.ArgumentParser(description="Render structured paper data by cloning exact V0.8.2 CANVAS components")
    p.add_argument("manifest", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--canonical", type=Path, required=True)
    p.add_argument("--schema", type=Path)
    a = p.parse_args()
    print(json.dumps(render(a.canonical, a.manifest, a.output, a.schema), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
