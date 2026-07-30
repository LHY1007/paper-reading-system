#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

import v082_body_reconstruction as body

base = body.base
ORIGINAL_BUILD_MANIFEST = body.ORIGINAL_BUILD_MANIFEST
ORIGINAL_AUGMENT_AUDIT = body.ORIGINAL_AUGMENT_AUDIT


def build_manifest_v15(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    sections, diagnostics = body.reconstruct_body(pdf, manifest)
    manifest["sections"] = sections
    manifest["evidence_body_reconstruction"] = diagnostics
    repairs = manifest.get("evidence_repairs") or {}
    repairs["parser"] = "v082-final-15"
    repairs["body_reconstruction"] = diagnostics
    repairs["reference_count"] = len(manifest.get("references", []))
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v15(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    diagnostics = manifest.get("evidence_body_reconstruction") or {}
    paragraphs = sum(
        block.get("type") == "paragraph"
        for section in manifest.get("sections", [])
        for block in section.get("blocks", [])
    )
    source_chars = sum(
        len("".join(item.get("text", "") for item in block.get("english", [])))
        for section in manifest.get("sections", [])
        for block in section.get("blocks", [])
        if block.get("type") == "paragraph"
    )
    result.update({
        "strict_layout_parser": "v082-final-15",
        "paragraphs": paragraphs,
        "source_chars": source_chars,
        "body_reconstruction": diagnostics,
        "references": len(manifest.get("references", [])),
        "assets": len(manifest.get("assets", [])),
    })
    errors = [
        error for error in result.get("strict_errors", [])
        if not (isinstance(error, str) and error.startswith("source text coverage too low"))
    ]
    pages = int(manifest.get("paper", {}).get("pages", 0) or 0)
    if paragraphs < max(20, pages):
        errors.append(f"too few reconstructed natural paragraphs: {paragraphs} for {pages} pages")
    if source_chars < pages * 1200:
        errors.append(f"reconstructed source text coverage too low: {source_chars} characters for {pages} pages")
    result["strict_errors"] = errors
    result["passed"] = bool(result.get("passed")) and not errors
    return result


base.base.build_manifest = build_manifest_v15
base.augment_audit = augment_audit_v15


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
