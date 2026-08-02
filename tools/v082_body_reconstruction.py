#!/usr/bin/env python3
from __future__ import annotations

from v082_body_reconstruction_core import *


def reconstruct_body(pdf: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    document, pages, body_size = extract_layout_pages(pdf)
    candidates = heading_candidates(manifest)
    corpus = nonbody_corpus(manifest)
    paper = manifest.get("paper") or {}
    authors = [norm(value) for value in paper.get("authors", [])]
    title = norm(paper.get("title_en"))
    stop_extended = extended_data_start(manifest)

    article_page_candidates = [
        item.page for item in candidates
        if item.page > 0 and heading_key(item.title) in {heading_key(title), "introduction", "summary", "abstract", "research article summary"}
    ]
    article_start = min(article_page_candidates) if article_page_candidates else 1

    events: list[dict[str, Any] | BodyEvent] = []
    current_section = "Front matter"
    current_level = 2
    abstract_emitted = False
    introduction_emitted = False
    candidate_page_chars: collections.Counter[int] = collections.Counter()
    accepted_page_chars: collections.Counter[int] = collections.Counter()
    accepted_page_paragraphs: collections.Counter[int] = collections.Counter()

    for page_number, blocks in enumerate(pages, 1):
        if stop_extended and page_number >= stop_extended:
            break
        if page_number < article_start:
            continue

        if page_number == article_start:
            abstract_blocks = [
                block for block in blocks
                if block.median_size >= body_size + 1.0
                and len(words(block.text)) >= 40
                and not META_RE.match(norm(block.text))
                and not author_like(block.text, authors)
                and title.lower() not in norm(block.text).lower()
            ]
            for block in abstract_blocks:
                text = norm(block.text)
                if represented_by_nonbody(text, corpus):
                    continue
                current_section = "Abstract"
                current_level = 2
                if not abstract_emitted:
                    events.append({"kind": "heading", "title": current_section, "page": page_number, "level": current_level})
                    abstract_emitted = True
                candidate_page_chars[page_number] += len(text)
                accepted_page_chars[page_number] += len(text)
                accepted_page_paragraphs[page_number] += 1
                events.append(BodyEvent(current_section, page_number, text, block, u.numeric_citations(block), [page_number]))

        for block in blocks:
            text = norm(block.text)
            if not text:
                continue
            if page_number == article_start and block.median_size >= body_size + 1.0 and len(words(text)) >= 40:
                continue
            if METHOD_TOC_RE.match(text) or (text.startswith("•") and text.count("•") >= 2):
                continue
            if title and title.lower() in text.lower() and len(text) <= len(title) + 300:
                continue
            if META_RE.match(text) or AFFILIATION_RE.match(text):
                continue

            bold_headings, bold_remainder = initial_bold_headings(block, candidates, body_size)
            if bold_headings:
                for heading in bold_headings:
                    current_section = normalize_heading_title(heading.title)
                    current_level = heading.level
                    events.append({"kind": "heading", "title": current_section, "page": page_number, "level": current_level})
                text = bold_remainder
            else:
                heading, remainder = split_heading_prefix(text, candidates)
                if heading is not None:
                    current_section = normalize_heading_title(heading.title)
                    current_level = heading.level
                    events.append({"kind": "heading", "title": current_section, "page": page_number, "level": current_level})
                    text = remainder
                elif page_number <= article_start + 1 and not introduction_emitted and current_section in {"Front matter", "Abstract", "Summary"} and block.median_size <= body_size + 0.8 and len(words(text)) >= 30:
                    current_section = "Introduction"
                    current_level = 2
                    events.append({"kind": "heading", "title": current_section, "page": page_number, "level": current_level})
                    introduction_emitted = True
            if heading_key(current_section) in ADMIN_HEADINGS:
                continue
            if not text:
                continue
            candidate = looks_like_prose(block, body_size, text) or base.is_formula_block(block)
            if not candidate:
                continue
            if author_like(text, authors):
                continue
            candidate_page_chars[page_number] += len(text)
            if represented_by_nonbody(text, corpus):
                continue
            accepted_page_chars[page_number] += len(text)
            accepted_page_paragraphs[page_number] += 1
            events.append(BodyEvent(current_section, page_number, text, block, u.numeric_citations(block), [page_number]))

    merged: list[dict[str, Any] | BodyEvent] = []
    for event in events:
        if not isinstance(event, BodyEvent):
            if merged and isinstance(merged[-1], dict) and merged[-1].get("kind") == "heading" and merged[-1].get("title") == event.get("title"):
                continue
            merged.append(event)
            continue
        if merged and isinstance(merged[-1], BodyEvent) and merged[-1].section == event.section:
            previous = merged[-1]
            same_page = event.page == previous.page
            previous_open = previous.text.endswith("-") or not u.TERMINAL_RE.search(previous.text)
            continuation_start = bool(re.match(r"^(?:[a-zα-ω]|\([a-z0-9]+\)|[,;:])", event.text.strip()))
            same_column = same_page and previous.block.column == event.block.column
            cross_column = (
                same_page
                and previous.block.column == "left"
                and event.block.column == "right"
                and event.block.bbox[1] <= previous.block.bbox[3] + 24
            )
            across_page = (
                event.page > previous.page
                and event.page <= previous.page + 4
                and previous_open
                and continuation_start
            )
            if previous_open and continuation_start and (same_column or cross_column or across_page):
                previous.text = norm(previous.text[:-1] + event.text) if previous.text.endswith("-") else norm(previous.text + " " + event.text)
                previous.citations = list(dict.fromkeys(previous.citations + event.citations))
                previous.source_pages = sorted(set(previous.source_pages + event.source_pages))
                previous.block.spans.extend(event.block.spans)
                continue
        merged.append(event)

    section_records: list[dict[str, Any]] = []
    section_by_key: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    paragraph_number = 0
    asset_ids = {str(asset.get("id")) for asset in manifest.get("assets", [])}

    for event in merged:
        if isinstance(event, dict):
            title_value = norm(event.get("title"))
            if heading_key(title_value) in ADMIN_HEADINGS:
                current = None
                continue
            key = heading_key(title_value)
            if not key:
                continue
            if key not in section_by_key:
                section = {
                    "id": u.slugify(title_value),
                    "title_en": title_value,
                    "title_zh": "",
                    "level": max(2, int(event.get("level") or 2)),
                    "blocks": [],
                    "source_start_page": int(event.get("page") or 1),
                    "source_order": len(section_records),
                }
                section_by_key[key] = section
                section_records.append(section)
            current = section_by_key[key]
            continue
        if current is None:
            key = heading_key(event.section or "Article body")
            if key not in section_by_key:
                section = {
                    "id": u.slugify(event.section or "Article body"),
                    "title_en": event.section or "Article body",
                    "title_zh": "",
                    "level": 2,
                    "blocks": [],
                    "source_start_page": event.page,
                    "source_order": len(section_records),
                }
                section_by_key[key] = section
                section_records.append(section)
            current = section_by_key[key]
        paragraph_number += 1
        source_pages = event.source_pages
        source_pages_value = str(source_pages[0]) if len(source_pages) == 1 else f"{source_pages[0]}-{source_pages[-1]}"
        block = {
            "type": "paragraph",
            "id": f"p-{paragraph_number:04d}",
            "source_pages": source_pages_value,
            "english": u.build_inline(event.text, event.citations, asset_ids),
            "chinese": [{"text": ""}],
            "source_fragments": [event.text],
        }
        had_paragraph = any(item.get("type") == "paragraph" for item in current["blocks"])
        current["blocks"].append(block)
        if not had_paragraph:
            current["source_start_page"] = min(source_pages)
        else:
            current["source_start_page"] = min(int(current.get("source_start_page") or event.page), min(source_pages))

    sections_by_page = sorted(
        [
            (int(section.get("source_start_page") or 1), index, section)
            for index, section in enumerate(section_records)
            if any(block.get("type") == "paragraph" for block in section.get("blocks", []))
        ],
        key=lambda item: (item[0], item[1]),
    )
    for asset in manifest.get("assets", []):
        asset_id = str(asset.get("id"))
        source_page = int(asset.get("source_page") or 1)
        if asset_id == "graphical-abstract":
            key = heading_key("Graphical abstract")
            if key not in section_by_key:
                section = {"id": "graphical-abstract", "title_en": "Graphical abstract", "title_zh": "", "level": 2, "blocks": [], "source_start_page": 1, "source_order": -1}
                section_by_key[key] = section
                section_records.insert(0, section)
            target = section_by_key[key]
        else:
            eligible = [record for record in sections_by_page if record[0] <= source_page]
            target = eligible[-1][2] if eligible else (section_records[0] if section_records else None)
        if target is not None and not any(block.get("type") == "asset" and block.get("asset_id") == asset_id for block in target["blocks"]):
            target["blocks"].append({"type": "asset", "asset_id": asset_id})

    section_records = [
        section
        for section in section_records
        if any(block.get("type") == "paragraph" for block in section.get("blocks", []))
        or section.get("id") == "graphical-abstract"
    ]

    def section_first_page(section: dict[str, Any]) -> int:
        source_pages: list[int] = []
        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue
            match = re.match(r"(\d+)", str(block.get("source_pages") or ""))
            if match:
                source_pages.append(int(match.group(1)))
        return min(source_pages) if source_pages else int(section.get("source_start_page") or 1)

    section_records.sort(key=lambda section: (section_first_page(section), int(section.get("source_order") or 0)))
    for section in section_records:
        section.pop("source_start_page", None)
        section.pop("source_order", None)

    manifest_source_chars = sum(
        len("".join(item.get("text", "") for item in block.get("english", [])))
        for section in section_records
        for block in section.get("blocks", [])
        if block.get("type") == "paragraph"
    )
    page_coverage = {
        str(page): round(accepted_page_chars[page] / max(1, candidate_page_chars[page]), 4)
        for page in sorted(candidate_page_chars)
    }
    diagnostics = {
        "version": "v082-body-reconstruction-5",
        "body_font_size": round(body_size, 3),
        "paragraphs": paragraph_number,
        "source_chars": manifest_source_chars,
        "candidate_source_chars": sum(candidate_page_chars.values()),
        "accepted_source_chars": sum(accepted_page_chars.values()),
        "page_candidate_chars": {str(page): chars for page, chars in sorted(candidate_page_chars.items())},
        "page_source_chars": {str(page): chars for page, chars in sorted(accepted_page_chars.items())},
        "page_paragraphs": {str(page): count for page, count in sorted(accepted_page_paragraphs.items())},
        "page_coverage": page_coverage,
        "low_coverage_pages": [int(page) for page, ratio in page_coverage.items() if candidate_page_chars[int(page)] >= 200 and ratio < 0.92],
        "extended_data_start_page": stop_extended,
        "sections": [section["title_en"] for section in section_records],
    }
    return section_records, diagnostics
