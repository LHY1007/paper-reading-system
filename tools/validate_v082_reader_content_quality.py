#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

CJK_RE = re.compile(r"[\u3400-\u9fff]")
PLACEHOLDER_AUTHORS = {"authors listed in the source pdf", "slides", "unknown", "author"}
BAD_OVERVIEW = [
    re.compile(r"https?://doi\.org/", re.I),
    re.compile(r"the source pdf contains", re.I),
    re.compile(r"extracted natural text blocks", re.I),
    re.compile(r"interpretation is limited", re.I),
    re.compile(r"\bethics statement\b", re.I),
    re.compile(r"\bnuclei isolation\b", re.I),
    re.compile(r"source pdf sha", re.I),
]
BAD_SECTION = re.compile(
    r"^(?:front matter|article|authors?(?: and affiliations)?|check for updates|received|accepted|published online)$",
    re.I,
)
GENERIC_FIGURE_TITLE = re.compile(r"^(?:fig\.?|figure(?:\s+[a-z]?\d+[a-z]?)?\.?)$", re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def has_cjk(value: Any) -> bool:
    return bool(CJK_RE.search(norm(value)))


def same_text(a: Any, b: Any) -> bool:
    x = re.sub(r"\W+", "", norm(a)).lower()
    y = re.sub(r"\W+", "", norm(b)).lower()
    return bool(x and x == y)


def add(errors: list[dict[str, Any]], path: str, issue: str, value: Any = None) -> None:
    item: dict[str, Any] = {"path": path, "issue": issue}
    if value is not None:
        item["value"] = norm(value)[:500]
    errors.append(item)


def validate(manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    paper = manifest.get("paper") or {}
    paper_title_en = norm(paper.get("title_en"))
    title_zh = norm(paper.get("title_zh"))
    title_en = paper_title_en
    if not has_cjk(title_zh) or same_text(title_en, title_zh):
        add(errors, "paper.title_zh", "must be a real Chinese scientific title", title_zh)
    authors = [norm(x) for x in paper.get("authors") or []]
    if not authors or any(x.lower() in PLACEHOLDER_AUTHORS for x in authors):
        add(errors, "paper.authors", "actual author names are required", authors)
    if not paper.get("affiliations"):
        add(errors, "paper.affiliations", "actual affiliations are required")
    for field in ("publisher", "publication_timeline", "citation", "correspondence", "article_url"):
        if not norm(paper.get(field)):
            add(errors, f"paper.{field}", "required reader-facing metadata is missing")
    if re.fullmatch(r"\d{4}", norm(paper.get("publication_timeline"))):
        add(errors, "paper.publication_timeline", "a bare year is not a publication timeline", paper.get("publication_timeline"))
    metadata = paper.get("metadata") or []
    labels = {norm(x.get("label")).lower(): norm(x.get("value")) for x in metadata if isinstance(x, dict)}
    for required in ("journal scope", "领域定位"):
        if required.lower() not in labels:
            add(errors, "paper.metadata", f"missing metadata card: {required}")
    for label, value in labels.items():
        if "sha" in label or "extraction" in label or "source-audited" in value.lower():
            add(errors, "paper.metadata", "machine audit information must not appear in the reader header", f"{label}: {value}")

    overview = manifest.get("overview") or {}
    qa = overview.get("qa") or []
    expected_questions = [
        "研究解决什么问题？", "核心数据是什么？", "模型或分析的输入与输出是什么？",
        "主要生物学发现是什么？", "主要临床结果是什么？", "最重要的限制是什么？",
    ]
    if [norm(x.get("question")) for x in qa] != expected_questions:
        add(errors, "overview.qa", "the six fixed reader questions must be present in order")
    for i, item in enumerate(qa):
        answer = norm(item.get("answer"))
        if not has_cjk(answer):
            add(errors, f"overview.qa[{i}].answer", "answer must be reader-ready Chinese", answer)
        if len(answer) < 20 or len(answer) > 300:
            add(errors, f"overview.qa[{i}].answer", "answer must be concise but specific", answer)
        for pattern in BAD_OVERVIEW:
            if pattern.search(answer):
                add(errors, f"overview.qa[{i}].answer", "raw parser or methods text was used as an overview answer", answer)
                break
    method = norm(overview.get("method"))
    if not has_cjk(method) or "→" not in method or len(method) > 500:
        add(errors, "overview.method", "method must be a concise Chinese arrow-linked workflow", method)
    story = norm(overview.get("story"))
    if not has_cjk(story) or len(story) < 40:
        add(errors, "overview.story", "overall conclusion must be a specific Chinese synthesis", story)

    sections = manifest.get("sections") or []
    seen_titles: set[str] = set()
    for si, section in enumerate(sections):
        en = norm(section.get("title_en"))
        zh = norm(section.get("title_zh"))
        low = en.lower().strip(" :")
        if BAD_SECTION.fullmatch(low) or en.startswith("•") or len(en) > 220:
            add(errors, f"sections[{si}].title_en", "PDF front matter or sentence fragment was misclassified as a section", en)
        if same_text(en, zh) or not has_cjk(zh):
            add(errors, f"sections[{si}].title_zh", "section heading requires a Chinese translation", zh)
        key = low
        if key in seen_titles and key == "references":
            add(errors, f"sections[{si}].title_en", "duplicate References section")
        seen_titles.add(key)
        for bi, block in enumerate(section.get("blocks") or []):
            if block.get("type") != "paragraph":
                continue
            en_text = norm("".join(x.get("text", "") for x in block.get("english") or []))
            zh_text = norm("".join(x.get("text", "") for x in block.get("chinese") or []))
            if same_text(en_text, zh_text) or not has_cjk(zh_text):
                add(errors, f"sections[{si}].blocks[{bi}].chinese", "identity or missing Chinese translation", zh_text)
            if re.match(r"^(?:nature genetics|article https?://|check for updates)", en_text, re.I):
                add(errors, f"sections[{si}].blocks[{bi}].english", "running header or front matter leaked into body", en_text)

    assets = manifest.get("assets") or []
    for ai, asset in enumerate(assets):
        kind = asset.get("kind")
        title_en = norm(asset.get("title_en"))
        title_zh = norm(asset.get("title_zh"))
        if kind == "figure":
            if GENERIC_FIGURE_TITLE.fullmatch(title_en) or (title_en.lower() == "graphical abstract" and len(norm(asset.get("intro"))) < 40):
                add(errors, f"assets[{ai}].title_en", "figure title must include its descriptive source title", title_en)
            if not has_cjk(title_zh) or same_text(title_en, title_zh):
                add(errors, f"assets[{ai}].title_zh", "figure title requires a Chinese translation", title_zh)
            intro = norm(asset.get("intro"))
            if len(intro) < 30 or intro == norm(asset.get("caption_en"))[:len(intro)]:
                add(errors, f"assets[{ai}].intro", "figure intro must explain the figure's role rather than copy the caption", intro)
            cap_en = norm(asset.get("caption_en")); cap_zh = norm(asset.get("caption_zh"))
            if not cap_en or not has_cjk(cap_zh) or same_text(cap_en, cap_zh):
                add(errors, f"assets[{ai}].caption_zh", "full Chinese caption is required", cap_zh)
            study = asset.get("study") or {}
            overview_text = norm(study.get("overview")); conclusion = norm(study.get("conclusion"))
            panels = study.get("panels") or []
            if not has_cjk(overview_text) or len(overview_text) < 60:
                add(errors, f"assets[{ai}].study.overview", "figure-study overview must teach the reader how to read the figure", overview_text)
            if not panels:
                add(errors, f"assets[{ai}].study.panels", "figure-study panel explanations are required")
            for pi, panel in enumerate(panels):
                text = norm(panel.get("explanation"))
                if not has_cjk(text) or len(text) < 80:
                    add(errors, f"assets[{ai}].study.panels[{pi}]", "panel explanation must be substantive Chinese interpretation", text)
            if not has_cjk(conclusion) or len(conclusion) < 40:
                add(errors, f"assets[{ai}].study.conclusion", "figure-level conclusion is required", conclusion)
        elif kind == "table":
            table = asset.get("table") or {}
            if not table.get("headers") or not table.get("rows"):
                add(errors, f"assets[{ai}].table", "table card requires structured headers and rows")
        else:
            add(errors, f"assets[{ai}].kind", "asset kind must be figure or table", kind)
        if title_en.lower().startswith("table") and kind != "table":
            add(errors, f"assets[{ai}].kind", "source table was incorrectly emitted as a figure", title_en)

    refs = manifest.get("references") or []
    ids = [int(x.get("id")) for x in refs if str(x.get("id", "")).isdigit()]
    if ids and ids != list(range(1, max(ids) + 1)):
        add(errors, "references", "reference numbering has gaps or was reordered", ids)

    return {
        "version": "v082-reader-content-quality-1",
        "paper": paper_title_en,
        "errors": errors,
        "error_count": len(errors),
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reject machine-complete but reader-useless V0.8.2 manifests")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(json.loads(args.manifest.read_text("utf-8")))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    print(text)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
