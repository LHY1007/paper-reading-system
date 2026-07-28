#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
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


def render(canonical: Path, manifest_path: Path, output: Path, schema: Path | None) -> dict[str, Any]:
    original = base.fill_hero
    base.fill_hero = lambda hero, paper: fill_hero(base.BeautifulSoup(str(hero), "html.parser"), hero, paper)
    try:
        # The lambda above cannot create tags owned by the canonical soup. Replace render's global
        # function with a closure that derives the owning BeautifulSoup builder from the Tag.
        def owned_fill(hero: Tag, paper: dict[str, Any]) -> None:
            soup = BeautifulSoup("", "html.parser")
            fill_hero(soup, hero, paper)
        base.fill_hero = owned_fill
        return base.render(canonical, manifest_path, output, schema)
    finally:
        base.fill_hero = original


def main() -> None:
    parser = argparse.ArgumentParser(description="Render exact V0.8.2 CANVAS components with corrected hero construction")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.canonical, args.manifest, args.output, args.schema), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
