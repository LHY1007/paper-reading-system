#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

SOURCE_SHA256 = "84c37e235f40e782c79de6625ddd9369cba64095f28bff75ae702fb5893f6ff1"

MODE_STYLE = """
#readerModeSwitch{display:flex;align-items:center;gap:5px;flex:0 0 auto}
#readerModeSwitch .mode-btn{min-width:74px;white-space:nowrap}
#readerModeSwitch .mode-btn.active{color:#fff;background:linear-gradient(135deg,var(--ui-accent),var(--ui-accent-2));border-color:transparent}
@media(max-width:980px){#readerModeSwitch{order:1;width:100%}#readerModeSwitch .mode-btn{flex:1}}
""".strip()

MODE_SCRIPT = """
(function(){
'use strict';
const buttons=[...document.querySelectorAll('#readerModeSwitch .mode-btn[data-mode]')];
function sync(){const mode=document.body.dataset.mode||'bilingual';buttons.forEach(b=>{const active=b.dataset.mode===mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
buttons.forEach(b=>b.addEventListener('click',()=>requestAnimationFrame(sync)));
new MutationObserver(sync).observe(document.body,{attributes:true,attributeFilter:['data-mode']});
sync();
})();
""".strip()

TERM_COMPAT_SCRIPT = """
(function(){
'use strict';
// V0.7.1 formerly created #canvas-term-tooltip and intercepted term clicks in
// capture phase. V0.8 already owns the canonical #termTooltip implementation.
// Keeping two handlers made the visible tooltip diverge from the component
// contract, so the legacy patch is intentionally retired in the normalized master.
const duplicate=document.getElementById('canvas-term-tooltip');
if(duplicate)duplicate.remove();
})();
""".strip()


def text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def ensure_mode_switch(soup: BeautifulSoup) -> bool:
    topbar = soup.select_one("#topbar")
    brand = soup.select_one("#topbar .brand")
    if not topbar or not brand:
        raise RuntimeError("canonical CANVAS missing topbar/brand")
    existing = soup.select_one("#readerModeSwitch")
    if existing:
        return False
    switch = soup.new_tag("div")
    switch["id"] = "readerModeSwitch"
    switch["class"] = ["reader-mode-switch"]
    switch["role"] = "group"
    switch["aria-label"] = "阅读模式"
    for mode, label in (("quick", "快速了解"), ("bilingual", "双语精读")):
        button = soup.new_tag("button")
        button["type"] = "button"
        button["class"] = ["mode-btn"] + (["active"] if mode == "bilingual" else [])
        button["data-mode"] = mode
        button["aria-pressed"] = "true" if mode == "bilingual" else "false"
        button.append(NavigableString(label))
        switch.append(button)
    brand.insert_after(switch)
    return True


def ensure_mode_assets(soup: BeautifulSoup) -> tuple[bool, bool]:
    style_added = False
    script_added = False
    style = soup.find("style", id="canvas-v082-normalized-mode-style")
    if not style:
        style = soup.new_tag("style")
        style["id"] = "canvas-v082-normalized-mode-style"
        style.string = MODE_STYLE
        soup.head.append(style)
        style_added = True
    script = soup.find("script", id="canvas-v082-normalized-mode-script")
    if not script:
        script = soup.new_tag("script")
        script["id"] = "canvas-v082-normalized-mode-script"
        script.string = MODE_SCRIPT
        soup.body.append(script)
        script_added = True
    return style_added, script_added


def retire_duplicate_term_tooltip(soup: BeautifulSoup) -> bool:
    script = soup.find("script", id="canvas-v071-patch-script")
    if not script:
        return False
    script["data-normalized-reason"] = "duplicate-term-tooltip-retired"
    script.string = TERM_COMPAT_SCRIPT
    duplicate = soup.select_one("#canvas-term-tooltip")
    if duplicate:
        duplicate.decompose()
    return True


def normalize_figure_images(soup: BeautifulSoup) -> int:
    changed = 0
    for card in soup.select("#bilingual-pane .figure-card:not(.table-card)"):
        image = card.select_one(":scope > .figure-content > img.zoomable")
        if not image:
            continue
        source_page = image.get("data-source-page") or card.get("data-source-page") or ""
        defaults = {
            "loading": "lazy",
            "draggable": "false",
            "data-source-page": source_page,
            "data-complete-page": source_page,
            "data-hires": image.get("data-hires") or "true",
            "data-lossless": image.get("data-lossless") or "webp",
            "data-source-render": image.get("data-source-render") or "pdf-region",
        }
        for key, value in defaults.items():
            if image.get(key) is None:
                image[key] = value
                changed += 1
    return changed


def p_with_text(soup: BeautifulSoup, value: str) -> Tag:
    node = soup.new_tag("p")
    node.append(NavigableString(value))
    return node


def normalize_table_captions(soup: BeautifulSoup) -> int:
    changed = 0
    for card in soup.select("#bilingual-pane .table-card"):
        content = card.select_one(":scope > .figure-content")
        if not content:
            continue
        captions = content.select_one(":scope > .captions")
        if not captions:
            captions = soup.new_tag("div")
            content.append(captions)
        existing = captions.find_all(recursive=False)
        en_text = text(captions.select_one(".caption-en")) or (text(existing[0]) if existing else "")
        zh_text = text(captions.select_one(".caption-zh")) or (text(existing[1]) if len(existing) > 1 else "")
        captions.clear()
        captions["class"] = ["captions", "bilingual-caption"]
        captions["data-required-module"] = "bilingual-caption"
        en = soup.new_tag("div")
        en["class"] = ["caption", "caption-en"]
        en["data-required-field"] = "caption_en"
        en.append(p_with_text(soup, en_text))
        zh = soup.new_tag("div")
        zh["class"] = ["caption", "caption-zh", "translation-content"]
        zh["data-required-field"] = "caption_zh"
        zh.append(p_with_text(soup, zh_text))
        captions.append(en)
        captions.append(zh)
        changed += 1
    return changed


def normalize_sections(soup: BeautifulSoup) -> int:
    changed = 0
    for section in soup.select("#bilingual-pane > section.paper-section"):
        heading = section.find("h2", recursive=False)
        if section.get("data-level") is None:
            section["data-level"] = "2"
            changed += 1
        if section.get("data-title") is None:
            section["data-title"] = text(heading) or section.get("id", "section")
            changed += 1
        if heading:
            if heading.get("data-toc-en") is None:
                heading["data-toc-en"] = text(heading)
                changed += 1
            if heading.get("data-toc-zh") is None:
                heading["data-toc-zh"] = text(heading)
                changed += 1
    return changed


def normalize(source: Path, output: Path) -> dict[str, Any]:
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_sha != SOURCE_SHA256:
        raise SystemExit(f"unexpected canonical source SHA256: {source_sha}")
    soup = BeautifulSoup(source.read_text("utf-8"), "html.parser")
    soup.html["data-v082-canonical"] = "normalized-master"
    marker = soup.find("meta", attrs={"name": "v082-canonical-normalized"})
    if not marker:
        marker = soup.new_tag("meta")
        marker["name"] = "v082-canonical-normalized"
        marker["content"] = "1"
        soup.head.append(marker)
    mode_added = ensure_mode_switch(soup)
    style_added, script_added = ensure_mode_assets(soup)
    duplicate_term_handler_retired = retire_duplicate_term_tooltip(soup)
    image_attrs = normalize_figure_images(soup)
    table_cards = normalize_table_captions(soup)
    section_attrs = normalize_sections(soup)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(str(soup), "utf-8")
    return {
        "source": source.name,
        "output": output.name,
        "source_sha256": source_sha,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "mode_switch_added": mode_added,
        "mode_style_added": style_added,
        "mode_script_added": script_added,
        "duplicate_term_handler_retired": duplicate_term_handler_retired,
        "figure_image_attributes_added": image_attrs,
        "table_cards_normalized": table_cards,
        "section_attributes_added": section_attrs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the deterministic normalized V0.8.2 CANVAS master")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = normalize(args.source, args.output)
    out = json.dumps(report, ensure_ascii=False, indent=2)
    print(out)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(out + "\n", "utf-8")


if __name__ == "__main__":
    main()
