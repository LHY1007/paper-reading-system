#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import build_pdf_native_manifest_v082_v4 as v4


base = v4.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
MAIN_CAPTION_TITLE = re.compile(
    r"^(?:Fig\.|Figure)\s*\d+\s*\|\s*(.+?)(?=\s+[a-z],\s)",
    re.I | re.S,
)
UPPER_PANEL = re.compile(r"\(([A-Z])(?:\s*[–-]\s*([A-Z]))?(?:,\s*[^)]*)?\)")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def expand_labels(first: str, last: str | None) -> list[str]:
    if last is None:
        return [first]
    start = ord(first)
    end = ord(last)
    if start > end or end - start > 20:
        return [first]
    return [chr(value) for value in range(start, end + 1)]


def panel_evidence_from_caption(caption: str) -> list[dict[str, str]]:
    evidence: dict[str, str] = {}
    for sentence in SENTENCE.split(norm(caption)):
        matches = list(UPPER_PANEL.finditer(sentence))
        for match in matches:
            for label in expand_labels(match.group(1), match.group(2)):
                evidence.setdefault(label, sentence)
    return [
        {
            "label": label,
            "title": "Source caption evidence",
            "explanation": text,
            "source_text": text,
        }
        for label, text in sorted(evidence.items())
    ]


def build_manifest_v5(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    titles_extended = 0
    upper_panel_blocks = 0
    for asset in manifest.get("assets", []):
        caption = norm(asset.get("caption_en"))
        title = norm(asset.get("title_en"))
        match = MAIN_CAPTION_TITLE.match(caption)
        if match:
            caption_title = norm(match.group(1)).rstrip(".")
            prefix_match = re.match(r"^(Figure\s+\d+\.)", title, re.I)
            if prefix_match and len(caption_title) > len(title.removeprefix(prefix_match.group(1)).strip()):
                asset["title_en"] = norm(f"{prefix_match.group(1)} {caption_title}")
                titles_extended += 1
        study = asset.get("study") or {}
        panels = study.get("panels") or []
        if not panels:
            panels = panel_evidence_from_caption(caption)
            upper_panel_blocks += len(panels)
            study["panels"] = panels
            asset["study"] = study
        else:
            for panel in panels:
                source_text = norm(panel.get("source_text"))
                if source_text:
                    panel.setdefault("title", "Source caption evidence")
                    panel.setdefault("explanation", source_text)
    repairs = manifest.get("evidence_repairs") or {}
    repairs["parser"] = "v082-final-5"
    repairs["titles_extended_from_caption"] = titles_extended
    repairs["uppercase_panel_evidence_blocks"] = upper_panel_blocks
    repairs["caption_panel_evidence_blocks"] = sum(
        len((asset.get("study") or {}).get("panels") or []) for asset in manifest.get("assets", [])
    )
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v5(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-5"
    result["titles_extended_from_caption"] = repairs.get("titles_extended_from_caption")
    result["uppercase_panel_evidence_blocks"] = repairs.get("uppercase_panel_evidence_blocks")
    result["caption_panel_evidence_blocks"] = repairs.get("caption_panel_evidence_blocks")
    return result


base.base.build_manifest = build_manifest_v5
base.augment_audit = augment_audit_v5


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
