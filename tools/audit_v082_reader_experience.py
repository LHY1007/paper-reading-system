#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

CJK = re.compile(r"[\u3400-\u9fff]")
BAD_OVERVIEW = [
    "the source pdf contains",
    "extracted natural text blocks",
    "source pdf sha",
    "pdf-native",
    "interpretation is limited",
    "ethics statement",
    "nuclei isolation",
    "check for updates",
]
BAD_SECTION_EXACT = {
    "front matter",
    "article",
    "authors",
    "authors and affiliations",
    "check for updates",
    "received",
    "accepted",
    "published online",
    "online content",
}
RUNNING_HEADER = re.compile(
    r"^(?:Nature Genetics|Nature Medicine|Nature Machine Intelligence|Nature Communications|Cell\s+\d+|Article\s+https?://|OPEN ACCESS)",
    re.I,
)
GENERIC_FIG = re.compile(r"^(?:Fig\.?|Figure\.?|Extended Data Fig\.?)$", re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def same_text(left: str, right: str) -> bool:
    left_key = re.sub(r"\W+", "", norm(left)).lower()
    right_key = re.sub(r"\W+", "", norm(right)).lower()
    return bool(left_key and left_key == right_key)


def parse_js_json(soup: BeautifulSoup, variable: str) -> Any:
    marker = f"const {variable}="
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        index = text.find(marker)
        if index < 0:
            continue
        raw = text[index + len(marker) :].lstrip()
        try:
            return decoder.raw_decode(raw)[0]
        except Exception:
            continue
    return None


def extract_reader(path: Path) -> dict[str, Any]:
    soup = BeautifulSoup(path.read_text("utf-8", errors="ignore"), "lxml")
    hero = soup.select_one("section.hero")
    heading = hero.find("h1") if hero else soup.find("h1")
    chinese_heading = hero.select_one(".zh-title") if hero else None
    byline = hero.select_one(".paper-byline") if hero else None
    paper_info = hero.select_one("details.paper-info") if hero else None

    metadata: dict[str, str] = {}
    if paper_info:
        metadata_box = paper_info.select_one(".metadata")
        if metadata_box:
            known_labels = [
                "Volume, issue and pages",
                "Publication timeline",
                "Source PDF SHA256",
                "Journal scope",
                "Article type",
                "Publisher",
                "Extraction",
                "领域定位",
                "Journal",
                "DOI",
            ]
            for row in metadata_box.find_all("div", recursive=False):
                children = row.find_all(recursive=False)
                if len(children) >= 2:
                    label = norm(children[0].get_text(" ", strip=True))
                    value = norm(children[1].get_text(" ", strip=True))
                else:
                    text = norm(row.get_text(" ", strip=True))
                    label = ""
                    value = ""
                    for candidate in known_labels:
                        if text.startswith(candidate):
                            label = candidate
                            value = norm(text[len(candidate) :])
                            break
                if label:
                    metadata[label] = value

    authors: list[str] = []
    affiliations: list[str] = []
    if paper_info:
        author_box = paper_info.select_one(".author-list")
        if author_box:
            for row in author_box.find_all("div", recursive=False):
                text = norm(row.get_text(" ", strip=True))
                if not text:
                    continue
                if re.match(r"^\d+\s", text):
                    affiliations.append(text)
                elif text.lower() != "authors and affiliations":
                    authors.append(text)
    if not authors and byline:
        authors = [part.strip() for part in norm(byline.get_text(" ", strip=True)).split(",") if part.strip()]

    overview_qa: list[dict[str, str]] = []
    for card in soup.select(".qa")[:6]:
        question_node = card.find(["h3", "b", "strong"])
        question = norm(question_node.get_text(" ", strip=True)) if question_node else ""
        answer = norm(card.get_text(" ", strip=True))
        if question and answer.startswith(question):
            answer = norm(answer[len(question) :])
        overview_qa.append({"question": question, "answer": answer})

    section_titles: list[str] = []
    for section in soup.select(".paper-section"):
        title_node = section.find(["h2", "h3"])
        if title_node:
            section_titles.append(norm(title_node.get_text(" ", strip=True)))

    units: list[dict[str, str]] = []
    for unit in soup.select(".bilingual-unit"):
        source_node = unit.select_one(".source-block") or unit
        translation_node = unit.select_one(".translation-block")
        units.append(
            {
                "english": norm(source_node.get_text(" ", strip=True)),
                "chinese": norm(translation_node.get_text(" ", strip=True)) if translation_node else "",
            }
        )

    figures: list[dict[str, Any]] = []
    for figure in soup.select(".figure-card"):
        heading_node = figure.select_one(".figure-heading")
        heading_wrapper = heading_node.find("div") if heading_node else None
        title_dom = norm(
            heading_wrapper.get_text(" ", strip=True)
            if heading_wrapper
            else heading_node.get_text(" ", strip=True) if heading_node else ""
        )
        caption_en_node = figure.select_one(".caption-en")
        caption_zh_node = figure.select_one(".caption-zh")
        figures.append(
            {
                "id": figure.get("id"),
                "title_dom": title_dom,
                "caption_en": norm(caption_en_node.get_text(" ", strip=True)) if caption_en_node else "",
                "caption_zh": norm(caption_zh_node.get_text(" ", strip=True)) if caption_zh_node else "",
            }
        )

    assets = parse_js_json(soup, "V6_ASSETS") or []
    studies = parse_js_json(soup, "V6_STUDY") or {}
    asset_map = {str(item.get("id")): item for item in assets if isinstance(item, dict)}
    for figure in figures:
        asset = asset_map.get(str(figure["id"]), {})
        study = studies.get(str(figure["id"]), {}) if isinstance(studies, dict) else {}
        figure.update(
            {
                "title": norm(asset.get("title") or figure["title_dom"]),
                "title_zh": norm(asset.get("zh")),
                "intro": norm(asset.get("intro")),
                "study_overview": norm(study.get("overview")) if isinstance(study, dict) else "",
                "study_conclusion": norm(study.get("conclusion")) if isinstance(study, dict) else "",
                "panel_count": len(study.get("panels") or []) if isinstance(study, dict) else 0,
            }
        )

    references = [norm(item.get_text(" ", strip=True)) for item in soup.select(".reference-item")]

    suspicious_sections: list[str] = []
    for title in section_titles:
        english_title = title.split("（", 1)[0].strip()
        lowered = english_title.lower().strip(" :")
        if (
            lowered in BAD_SECTION_EXACT
            or len(english_title) > 180
            or english_title.startswith("•")
            or re.search(r"https?://|check for updates", english_title, re.I)
        ):
            suspicious_sections.append(title)

    bad_qa: list[dict[str, Any]] = []
    for index, item in enumerate(overview_qa):
        lowered = item["answer"].lower()
        hits = [pattern for pattern in BAD_OVERVIEW if pattern in lowered]
        if hits or not CJK.search(item["answer"]):
            bad_qa.append({"index": index, "patterns": hits, "answer": item["answer"][:400]})

    identity_translations = sum(1 for item in units if same_text(item["english"], item["chinese"]))
    missing_chinese = sum(1 for item in units if not CJK.search(item["chinese"]))
    short_units = sum(1 for item in units if len(item["english"]) < 80)
    running_headers = sum(1 for item in units if RUNNING_HEADER.match(item["english"]))

    generic_titles = [
        item["id"]
        for item in figures
        if GENERIC_FIG.fullmatch(item["title"])
        or GENERIC_FIG.fullmatch(item["title_dom"].split("（", 1)[0].strip())
    ]
    untranslated_captions = [
        item["id"]
        for item in figures
        if same_text(item["caption_en"], item["caption_zh"]) or not CJK.search(item["caption_zh"])
    ]
    empty_intros = [item["id"] for item in figures if len(item["intro"]) < 25]
    incomplete_studies = [
        item["id"]
        for item in figures
        if len(item["study_overview"]) < 50
        or item["panel_count"] == 0
        or len(item["study_conclusion"]) < 30
    ]
    contaminated_captions = [
        item["id"]
        for item in figures
        if len(item["caption_en"]) > 4000
        or re.search(
            r"Cellular composition of the tumor-microenvironment|Nature Genetics \| Volume|Article https?://",
            item["caption_en"],
        )
    ]

    required_metadata = [
        "Journal",
        "Publisher",
        "DOI",
        "Article type",
        "Publication timeline",
        "Volume, issue and pages",
        "Journal scope",
        "领域定位",
    ]
    missing_metadata = [label for label in required_metadata if not metadata.get(label)]
    machine_metadata = [label for label in metadata if "SHA" in label or label == "Extraction"]

    title_en = norm(heading.get_text(" ", strip=True) if heading else "")
    title_zh = norm(chinese_heading.get_text(" ", strip=True) if chinese_heading else "")

    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "hero": {
            "title_en": title_en,
            "title_zh": title_zh,
            "byline": norm(byline.get_text(" ", strip=True) if byline else ""),
            "author_count": len(authors),
            "affiliation_count": len(affiliations),
            "metadata": metadata,
            "missing_metadata": missing_metadata,
            "machine_metadata": machine_metadata,
            "title_zh_valid": bool(CJK.search(title_zh)) and not same_text(title_en, title_zh),
        },
        "overview": {"qa": overview_qa, "bad_qa": bad_qa, "bad_count": len(bad_qa)},
        "sections": {
            "count": len(section_titles),
            "titles": section_titles,
            "suspicious": suspicious_sections,
            "suspicious_count": len(suspicious_sections),
        },
        "body": {
            "unit_count": len(units),
            "identity_translation_count": identity_translations,
            "identity_translation_ratio": round(identity_translations / max(1, len(units)), 4),
            "missing_chinese_count": missing_chinese,
            "short_english_units": short_units,
            "running_header_units": running_headers,
        },
        "figures": {
            "count": len(figures),
            "generic_title_count": len(generic_titles),
            "generic_title_ids": generic_titles,
            "untranslated_caption_count": len(untranslated_captions),
            "untranslated_caption_ids": untranslated_captions,
            "empty_intro_count": len(empty_intros),
            "empty_intro_ids": empty_intros,
            "incomplete_study_count": len(incomplete_studies),
            "incomplete_study_ids": incomplete_studies,
            "contaminated_caption_count": len(contaminated_captions),
            "contaminated_caption_ids": contaminated_captions,
            "items": figures,
        },
        "tables": {"count": len(soup.select(".table-card"))},
        "references": {"count": len(references), "first": references[:2], "last": references[-2:]},
        "buttons": len(soup.find_all("button")),
    }


def score_reader(reader: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    modules: dict[str, float] = {}
    hero = reader["hero"]
    modules["paper_header"] = 5 - min(
        5,
        (0 if hero["title_zh_valid"] else 1)
        + len(hero["missing_metadata"])
        + (1 if hero["author_count"] < 2 else 0)
        + (1 if hero["affiliation_count"] == 0 else 0)
        + (1 if hero["machine_metadata"] else 0),
    )
    modules["one_page_overview"] = (
        5
        if reader["overview"]["bad_count"] == 0 and len(reader["overview"]["qa"]) == 6
        else max(0, 5 - reader["overview"]["bad_count"])
    )
    modules["section_map"] = max(0, 5 - min(5, reader["sections"]["suspicious_count"]))
    body_penalty = (
        reader["body"]["identity_translation_ratio"] * 5
        + min(2, reader["body"]["running_header_units"])
        + (1 if reader["body"]["short_english_units"] > reader["body"]["unit_count"] * 0.25 else 0)
    )
    modules["bilingual_body"] = max(0, round(5 - body_penalty, 1))

    figures = reader["figures"]
    denominator = max(1, figures["count"])
    figure_penalty = (
        figures["generic_title_count"]
        + figures["untranslated_caption_count"]
        + figures["empty_intro_count"]
        + figures["incomplete_study_count"]
        + figures["contaminated_caption_count"]
    ) / (denominator * 5)
    modules["figures"] = max(0, round(5 * (1 - figure_penalty), 1))

    if baseline is None or reader["tables"]["count"] >= baseline["tables"]["count"]:
        modules["tables"] = 5
    else:
        modules["tables"] = max(
            0,
            round(5 * reader["tables"]["count"] / max(1, baseline["tables"]["count"]), 1),
        )
    if baseline is None or reader["references"]["count"] == baseline["references"]["count"]:
        modules["references"] = 5
    else:
        modules["references"] = max(
            0,
            round(5 * reader["references"]["count"] / max(1, baseline["references"]["count"]), 1),
        )
    return {"modules": modules, "total": round(sum(modules.values()), 1), "max": 35}


def render_markdown(reports: list[dict[str, Any]]) -> str:
    baseline = reports[0]
    for report in reports:
        report["reader_score"] = score_reader(report, baseline if report is not baseline else None)

    lines = [
        "# V0.8.2 读者体验实测对照",
        "",
        "该报告检查读者真正看到的论文信息、概览、目录、双语正文、图表、表格和参考文献，不把 DOM 或按钮存在等同于阅读质量。",
        "",
        "| 文件 | 标题信息 | 一页概览 | 目录 | 双语正文 | 图表 | 表格 | 参考文献 | 总分 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        modules = report["reader_score"]["modules"]
        lines.append(
            f"| {report['file']} | {modules['paper_header']} | {modules['one_page_overview']} | "
            f"{modules['section_map']} | {modules['bilingual_body']} | {modules['figures']} | "
            f"{modules['tables']} | {modules['references']} | "
            f"{report['reader_score']['total']}/{report['reader_score']['max']} |"
        )
    lines.append("")

    for report in reports:
        hero = report["hero"]
        body = report["body"]
        figures = report["figures"]
        lines.extend(
            [
                f"## {report['file']}",
                "",
                f"标题区：中文标题有效={hero['title_zh_valid']}；作者 {hero['author_count']} 人；单位 {hero['affiliation_count']} 条；"
                f"缺少元数据 {', '.join(hero['missing_metadata']) or '无'}；机器审计字段 {', '.join(hero['machine_metadata']) or '无'}。",
                f"一页概览：{report['overview']['bad_count']}/6 个回答不具备读者可用性。",
                f"目录：{report['sections']['count']} 个章节，其中 {report['sections']['suspicious_count']} 个明显是首页残片、句子或非章节标题。",
                f"正文：{body['unit_count']} 个双语单元；同文翻译 {body['identity_translation_count']} 个，占 {body['identity_translation_ratio']:.1%}；"
                f"缺少中文 {body['missing_chinese_count']} 个；短碎片 {body['short_english_units']} 个；页眉泄漏 {body['running_header_units']} 个。",
                f"图表：{figures['count']} 个图卡；通用图名 {figures['generic_title_count']}；未翻译图注 {figures['untranslated_caption_count']}；"
                f"简介缺失 {figures['empty_intro_count']}；图表精读不完整 {figures['incomplete_study_count']}；图注污染 {figures['contaminated_caption_count']}。",
                f"表格：{report['tables']['count']} 个结构化表卡。参考文献：{report['references']['count']} 条。",
                "",
            ]
        )
        if report["overview"]["bad_qa"]:
            lines.append("概览错误示例：")
            for item in report["overview"]["bad_qa"][:3]:
                lines.append(f"- 第 {item['index'] + 1} 项：{item['answer'][:260]}")
            lines.append("")
        if report["sections"]["suspicious"]:
            lines.append("错误章节示例：" + "；".join(report["sections"]["suspicious"][:8]))
            lines.append("")
        if figures["items"]:
            first = figures["items"][0]
            lines.extend(
                [
                    "首个图卡：",
                    f"- 标题：{first['title']}",
                    f"- 中文标题：{first['title_zh']}",
                    f"- 简介：{first['intro'][:300]}",
                    f"- 图表精读子块：{first['panel_count']} 个",
                    f"- 英文图注长度：{len(first['caption_en'])}；中文图注长度：{len(first['caption_zh'])}",
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit reader-facing quality against a CANVAS baseline")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    parser.add_argument("--minimum-score", type=float)
    args = parser.parse_args()

    reports = [extract_reader(path) for path in args.files]
    baseline = reports[0]
    for report in reports:
        report["reader_score"] = score_reader(report, baseline if report is not baseline else None)

    payload = {"version": "v082-reader-experience-audit-1", "baseline": baseline["file"], "reports": reports}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(render_markdown(reports), "utf-8")

    summary = [{report["file"]: report["reader_score"]} for report in reports]
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.minimum_score is not None:
        failures = [
            report["file"]
            for report in reports[1:]
            if report["reader_score"]["total"] < args.minimum_score
        ]
        if failures:
            raise SystemExit(f"reader-experience score below {args.minimum_score}: {', '.join(failures)}")


if __name__ == "__main__":
    main()
