#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag


def clean_text(node: Tag | None) -> str:
    if not node:
        return ""
    clone = BeautifulSoup(str(node), "html.parser")
    for sup in clone.select("sup.citation"):
        sup.replace_with(sup.get_text("", strip=True))
    return " ".join(clone.get_text(" ", strip=True).split())


def html_text(value: str, prefer_p: bool = False) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    if prefer_p and soup.find("p"):
        return " ".join(" ".join(p.get_text(" ", strip=True).split()) for p in soup.find_all("p"))
    return " ".join(soup.get_text(" ", strip=True).split())


def extract_window_json(text: str, name: str, next_name: str | None = None) -> dict[str, Any]:
    end = rf";window\.{re.escape(next_name)}=" if next_name else r";</script>"
    match = re.search(rf"window\.{re.escape(name)}=(\{{.*?\}}){end}", text, re.S)
    if not match:
        return {}
    return json.loads(match.group(1))


def parse_metadata(soup: BeautifulSoup) -> dict[str, Any]:
    hero = soup.select_one(".hero")
    title_en = clean_text(hero.find("h1") if hero else soup.find("h1"))
    title_zh = clean_text(hero.find("h2") if hero else None) or title_en
    values = [clean_text(x) for x in hero.select(".metadata span")] if hero else []
    journal, year, doi, pages = "Unknown journal", 2026, "unknown", 1
    authors = [values[0]] if values else ["Unknown authors"]
    for value in values:
        m = re.search(r"(.+?)\s*[·|]\s*((?:19|20)\d{2})", value)
        if m:
            journal, year = m.group(1).strip(), int(m.group(2))
        m = re.search(r"DOI\s+(.+)", value, re.I)
        if m:
            doi = m.group(1).strip()
        m = re.search(r"PDF\s+(\d+)\s*页", value, re.I)
        if m:
            pages = int(m.group(1))
    return {
        "key": re.sub(r"[^a-z0-9]+", "-", title_en.lower()).strip("-")[:80] or "legacy-paper",
        "title_en": title_en,
        "title_zh": title_zh,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "pages": pages,
        "article_type": "Article",
        "metadata": [
            {"label": "来源", "value": "V0.8.2 legacy batch migration", "bold": False},
            {"label": "状态", "value": "仅用于模板和内容门禁对照，不作为正式阅读器", "bold": False},
        ],
    }


def parse_overview(soup: BeautifulSoup) -> dict[str, Any]:
    values: dict[str, str] = {}
    for card in soup.select(".overview-grid .overview-card"):
        inner = card.select_one(":scope > .overview-card") or card
        h = clean_text(inner.find("h3"))
        if not h or h in values:
            continue
        p = clean_text(inner.find("p"))
        if not p:
            p = "；".join(clean_text(li) for li in inner.find_all("li"))
        values[h] = p
    findings = values.get("主要发现", "当前旧批量文件未提供可靠的主要发现概括。")
    boundary = values.get("证据边界", "当前旧批量文件未提供充分的证据边界说明。")
    return {
        "qa": [
            {"question": "研究解决什么问题？", "answer": values.get("研究主题", "旧批量文件未提供。")},
            {"question": "核心数据是什么？", "answer": values.get("数据规模", "旧批量文件未提供。")},
            {"question": "模型输入与输出是什么？", "answer": values.get("输入与输出", "旧批量文件未提供。")},
            {"question": "主要生物学发现是什么？", "answer": findings},
            {"question": "主要临床结果是什么？", "answer": findings},
            {"question": "最重要的限制是什么？", "answer": boundary},
        ],
        "method": values.get("输入与输出", "旧批量文件未提供完整方法流程。"),
        "story": findings,
        "scope_note": "本文件把旧批量内容迁移进固定 CANVAS 骨架，仅用于定位内容缺失；未通过 PDF 完整性门禁。",
    }


def parse_assets(raw: str) -> list[dict[str, Any]]:
    data = extract_window_json(raw, "READER_ASSETS", "READER_ONTOLOGY")
    out = []
    for index, (asset_id, item) in enumerate(data.items(), 1):
        title = item.get("title") or f"Figure {index}"
        page_match = re.search(r"第\s*(\d+)\s*页", title)
        src = item.get("src", "")
        image_format = "png" if src.startswith("data:image/png") else "jpeg" if src.startswith("data:image/jpeg") else "webp"
        study_text = html_text(item.get("study", ""))
        out.append({
            "id": asset_id,
            "kind": item.get("kind", "figure"),
            "group": "图表",
            "title_en": title,
            "title_zh": title,
            "intro": html_text(item.get("captionZh", ""), True)[:320] or title,
            "image_src": src,
            "source_page": int(page_match.group(1)) if page_match else 0,
            "image_format": image_format,
            "caption_en": html_text(item.get("captionEn", ""), True),
            "caption_zh": html_text(item.get("captionZh", ""), True),
            "study": {
                "overview": study_text,
                "panels": [],
                "conclusion": study_text,
                "boundary": "该精读内容继承自旧批量文件，需重新依据原图和原文审核。",
            } if study_text and item.get("kind", "figure") == "figure" else None,
        })
    for item in out:
        if item.get("study") is None:
            item.pop("study", None)
    return out


def parse_paragraphs(soup: BeautifulSoup) -> list[dict[str, Any]]:
    blocks = []
    for index, card in enumerate(soup.select(".para-card"), 1):
        uid = f"legacy-p{index}"
        head = clean_text(card.select_one(".para-head"))
        page_match = re.search(r"p\.(\d+)", head, re.I)
        en = clean_text(card.select_one(".lang.en p"))
        zh = clean_text(card.select_one(".lang.zh p"))
        blocks.append({
            "type": "paragraph",
            "id": uid,
            "source_pages": page_match.group(1) if page_match else "",
            "english": [{"text": en}],
            "chinese": [{"text": zh}],
            "source_fragments": [en],
            "tip": "该段继承自旧批量文件；PDF 覆盖率和段落边界由独立内容门禁审核。",
        })
    return blocks


def convert(source: Path) -> dict[str, Any]:
    raw = source.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    assets = parse_assets(raw)
    blocks = parse_paragraphs(soup)
    blocks += [{"type": "asset", "asset_id": a["id"]} for a in assets]
    return {
        "schema_version": "0.8.2",
        "paper": parse_metadata(soup),
        "overview": parse_overview(soup),
        "sections": [{
            "id": "legacy-migrated-content",
            "title_en": "Legacy migrated content",
            "title_zh": "旧批量内容迁移",
            "blocks": blocks,
        }],
        "assets": assets,
        "terms": [],
        "references": [],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Migrate a legacy V0.8.2 batch HTML into the locked structured manifest")
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    data = convert(a.source)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"output": str(a.output), "paragraphs": len(data["sections"][0]["blocks"]), "assets": len(data["assets"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
