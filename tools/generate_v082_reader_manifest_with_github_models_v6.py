#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_github_models_v5 as grounded
import validate_v082_reader_semantics_v3 as semantic_gate


_original_digest = grounded.collect_evidence_digest
_original_overview = grounded.generate_overview
_original_studies = grounded.generate_grounded_studies
_original_translate = grounded.base.translate_records


def cache_compatible_translate(
    records: list[dict[str, str]], *, token: str, model: str, cache_dir: Path,
    cache_prefix: str, context: str,
) -> dict[str, str]:
    compatible_prefix = cache_prefix[:-3] if cache_prefix.endswith("-v5") else cache_prefix
    return _original_translate(
        records,
        token=token,
        model=model,
        cache_dir=cache_dir,
        cache_prefix=compatible_prefix,
        context=context,
    )


def plan_first_overview(
    evidence: dict[str, Any], plan: dict[str, Any], *, token: str, model: str,
    cache_dir: Path, cache_prefix: str,
) -> dict[str, Any]:
    source = copy.deepcopy(plan.get("overview") or {})
    candidate = {
        "qa": [
            {
                "question": grounded.norm(item.get("question")),
                "answer": grounded.norm(item.get("answer")),
            }
            for item in source.get("qa") or []
            if isinstance(item, dict)
        ],
        "method_heading": "方法流程概括",
        "method": grounded.norm(source.get("method")),
        "story_label": "整体结论",
        "story": grounded.norm(source.get("story")),
        "scope_note": "正文与图注严格保留来源证据；中文按自然段翻译；图表精读仅解释图中及正文明确支持的结果。",
    }
    if not grounded.overview_issues(candidate):
        return candidate
    return _original_overview(
        evidence,
        plan,
        token=token,
        model=model,
        cache_dir=cache_dir,
        cache_prefix=cache_prefix,
    )


def compact_digest(evidence: dict[str, Any], max_chars: int = 9000) -> dict[str, Any]:
    digest = _original_digest(evidence, max_chars=min(max_chars, 9000))
    digest["figures"] = [
        {
            **item,
            "caption": grounded.norm(item.get("caption"))[:1000],
        }
        for item in (digest.get("figures") or [])[:4]
    ]
    return digest


def compact_studies(
    figures: list[dict[str, Any]], evidence: dict[str, Any], plan: dict[str, Any], *,
    token: str, model: str, cache_dir: Path, cache_prefix: str, paper_context: str,
) -> dict[str, dict[str, Any]]:
    compact_figures = copy.deepcopy(figures)
    for figure in compact_figures:
        figure["caption_en"] = grounded.norm(figure.get("caption_en"))[:6000]
        study = figure.get("study") or {}
        for panel in study.get("panels") or []:
            for field in ("source_text", "explanation", "title"):
                if field in panel:
                    panel[field] = grounded.norm(panel.get(field))[:1200]

    compact_evidence = copy.deepcopy(evidence)
    for section in compact_evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            figure_ids = [
                str(value)
                for item in block.get("english") or []
                for value in item.get("figure_ids") or []
            ]
            if not figure_ids:
                continue
            text = grounded.paragraph_text(block)[:900]
            block["english"] = [{"text": text, "figure_ids": list(dict.fromkeys(figure_ids))}]

    return _original_studies(
        compact_figures,
        compact_evidence,
        plan,
        token=token,
        model=model,
        cache_dir=cache_dir,
        cache_prefix=cache_prefix,
        paper_context=paper_context,
    )


def cli_paths(argv: list[str]) -> tuple[Path, Path]:
    if len(argv) < 4:
        raise SystemExit("usage: generator evidence.json plan.json output.json [options]")
    return Path(argv[1]), Path(argv[3])


def main() -> None:
    evidence_path, output_path = cli_paths(sys.argv)
    grounded.base.translate_records = cache_compatible_translate
    grounded.generate_overview = plan_first_overview
    grounded.collect_evidence_digest = compact_digest
    grounded.generate_grounded_studies = compact_studies
    grounded.main()

    evidence = json.loads(evidence_path.read_text("utf-8"))
    manifest = json.loads(output_path.read_text("utf-8"))
    report = semantic_gate.validate(manifest, evidence)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("passed"):
        output_path.unlink(missing_ok=True)
        sample = json.dumps((report.get("errors") or [])[:20], ensure_ascii=False)
        raise SystemExit(f"source-grounded semantic gate failed; manifest removed: {sample}")


if __name__ == "__main__":
    main()
