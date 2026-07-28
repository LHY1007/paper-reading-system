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
import render_v082_canvas_component_locked as base


def set_text(node: Tag | None, value: str) -> None:
    if node is None:
        return
    node.clear()
    node.append(NavigableString(value))


def fill_hero(soup: BeautifulSoup, hero: Tag, paper: dict[str, Any]) -> None:
    set_text(hero.find("h1", recursive=False), paper["title_en"])
    set_text(hero.select_one(":scope > .zh-title"), paper["title_zh"])
    set_text(hero.select_one(":scope > .paper-byline"), ", ".join(paper["authors"]))
    info = hero.select_one(":scope > .paper-info")
    if not info:
        return

    metadata = info.select_one(":scope > .metadata")
    if metadata:
        exemplar = metadata.find("div", recursive=False)
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
            row = copy.deepcopy(exemplar)
            row.clear()
            lab = soup.new_tag("span")
            lab.append(NavigableString(label))
            row.append(lab)
            if bold:
                val = soup.new_tag("b")
                val.append(NavigableString(value))
                row.append(val)
            else:
                row.append(NavigableString(value))
            metadata.append(row)

    authors = info.select_one(":scope > .author-list")
    if authors:
        head = copy.deepcopy(authors.find("h3", recursive=False))
        exemplar = authors.find("div", recursive=False)
        authors.clear()
        set_text(head, "Authors and affiliations")
        authors.append(head)
        for author in paper["authors"]:
            row = copy.deepcopy(exemplar)
            row.clear()
            b = soup.new_tag("b")
            b.append(NavigableString(author))
            row.append(b)
            authors.append(row)
        if paper.get("affiliations"):
            authors.append(soup.new_tag("hr"))
            for index, affiliation in enumerate(paper["affiliations"], 1):
                row = soup.new_tag("div")
                sup = soup.new_tag("sup")
                sup.append(NavigableString(str(index)))
                row.append(sup)
                row.append(NavigableString(" " + affiliation))
                authors.append(row)
        for label, value in [
            ("Correspondence", paper.get("correspondence")),
            ("Lead contact", paper.get("lead_contact")),
            ("Article link", paper.get("article_url")),
        ]:
            if value:
                p = soup.new_tag("p")
                b = soup.new_tag("b")
                b.append(NavigableString(label + ": "))
                p.append(b)
                p.append(NavigableString(value))
                authors.append(p)


def ensure_table_caption_module(template: Tag, soup: BeautifulSoup) -> Tag:
    adapted = copy.deepcopy(template)
    content = adapted.select_one(":scope > .figure-content")
    if content and not content.select_one(":scope > .captions.bilingual-caption"):
        captions = soup.new_tag("div")
        captions["class"] = ["captions", "bilingual-caption"]
        captions["data-required-module"] = "bilingual-caption"
        for side, label in (("en", "English caption"), ("zh", "中文表注")):
            box = soup.new_tag("div")
            box["class"] = ["caption", f"caption-{side}"] + (["translation-content"] if side == "zh" else [])
            box["data-required-field"] = f"caption_{side}"
            p = soup.new_tag("p")
            p.append(NavigableString(label))
            box.append(p)
            captions.append(box)
        content.append(captions)
    return adapted


def term_triples(manifest: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for term in manifest.get("terms", []):
        label = term.get("label", "")
        definition = term.get("definition_zh", "")
        category = term.get("category", "术语")
        seen: set[str] = set()
        for alias in [label, *(term.get("aliases") or [])]:
            alias = str(alias).strip()
            if alias and alias not in seen:
                rows.append([alias, definition, category])
                seen.add(alias)
    return rows


def replace_const_if_present(text: str, name: str, expression: str) -> str:
    try:
        return base.replace_const_expression(text, name, expression)
    except ValueError:
        return text


def patch_script(soup: BeautifulSoup, script_id: str, transform) -> None:
    node = soup.find("script", id=script_id)
    if node:
        node.string = transform(node.get_text() or "")


def postprocess_paper_isolation(output: Path, manifest: dict[str, Any]) -> None:
    soup = BeautifulSoup(output.read_text("utf-8"), "html.parser")
    paper_key = manifest["paper"]["key"]
    study_ids = [a["id"] for a in manifest.get("assets", []) if a.get("kind") == "figure" and a.get("study")]
    study_json = json.dumps(study_ids, ensure_ascii=False, separators=(",", ":"))
    terms_json = json.dumps(term_triples(manifest), ensure_ascii=False, separators=(",", ":"))

    # The reference popover data is a paper-content store, not part of the UI shell.
    reference_data = soup.find("script", id="referenceData")
    if reference_data:
        reference_data["type"] = "application/json"
        reference_data.string = json.dumps(
            {
                str(ref["id"]): {k: v for k, v in {"text": ref["text"], "url": ref.get("url")}.items() if v}
                for ref in manifest.get("references", [])
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    # CANVAS kept a hidden STAR Methods preview store outside the bilingual pane.
    # It must never leak into another paper. Main-section jumps work directly; a
    # later PDF-native builder may repopulate this store with paper-specific extras.
    preview_store = soup.select_one("#crossRefPreviewStore")
    if preview_store:
        preview_store.clear()
        preview_store["data-paper-key"] = paper_key

    def patch_v062(text: str) -> str:
        text = replace_const_if_present(text, "KEY", "'paper-reader-'+document.body.dataset.paperKey+'-v082'")
        return replace_const_if_present(text, "supported", "new Set(" + study_json + ")")

    def patch_v073(text: str) -> str:
        return replace_const_if_present(text, "STORE", "'paper-reader-'+document.body.dataset.paperKey+'-v082-study'")

    def patch_v077(text: str) -> str:
        return replace_const_if_present(text, "STUDY_IDS", "new Set(" + study_json + ")")

    def patch_v078(text: str) -> str:
        return replace_const_if_present(text, "TERMS", terms_json)

    def patch_v081(text: str) -> str:
        text = replace_const_if_present(text, "EXTRA_TERMS", terms_json)
        text = re.sub(r"\|\|\s*\[[^\]]*\]\.includes\(id\)", "||" + study_json + ".includes(id)", text, count=1)
        return text

    patch_script(soup, "canvas-reader-v062-script", patch_v062)
    patch_script(soup, "canvas-v073-script", patch_v073)
    patch_script(soup, "canvas-v077-script", patch_v077)
    patch_script(soup, "canvas-v078-final-script", patch_v078)
    patch_script(soup, "canvas-v081-script", patch_v081)

    output.write_text(str(soup), "utf-8")


def render(canonical: Path, manifest_path: Path, output: Path, schema: Path | None) -> dict[str, Any]:
    manifest = base.load_json(manifest_path)
    original_hero = base.fill_hero
    original_table = base.fill_table

    def owned_fill(hero: Tag, paper: dict[str, Any]) -> None:
        fill_hero(BeautifulSoup("", "html.parser"), hero, paper)

    def normalized_table(template: Tag, soup: BeautifulSoup, asset: dict[str, Any]) -> Tag:
        return original_table(ensure_table_caption_module(template, soup), soup, asset)

    base.fill_hero = owned_fill
    base.fill_table = normalized_table
    try:
        report = base.render(canonical, manifest_path, output, schema)
    finally:
        base.fill_hero = original_hero
        base.fill_table = original_table

    postprocess_paper_isolation(output, manifest)
    report["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    report["paper_isolation_postprocessed"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Render exact V0.8.2 CANVAS components with paper-specific stores isolated")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.canonical, args.manifest, args.output, args.schema), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
