#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

import generate_v082_reader_manifest_with_github_models_v2 as constrained

base = constrained.base


def translate_records_with_repairs(
    records: list[dict[str, str]], *, token: str, model: str, cache_dir: Path,
    cache_prefix: str, context: str,
) -> dict[str, str]:
    translations: dict[str, str] = {}
    source_by_id = {str(item["id"]): base.norm(item.get("text")) for item in records}
    system = f"""You are producing a publication-grade bilingual biomedical paper reader. Translate every English item into accurate, fluent Simplified Chinese. Preserve all numbers, gene/protein names, abbreviations, statistical symbols, comparison directions, citation numbers and uncertainty. Use consistent terminology across items. Do not summarize, omit, add interpretation, or output English as the translation. If an item is a formula, variable definition, code-like expression or statistical notation, preserve the expression and add a Chinese sentence stating what it defines or computes; every zh value must contain Chinese characters. Context: {context}\nReturn JSON only: {{\"items\":[{{\"id\":\"...\",\"zh\":\"...\"}}]}}. Include every input id exactly once."""
    repair_system = f"""Translate the supplied biomedical technical text into Simplified Chinese. The previous answer failed because it contained no Chinese. Preserve every formula, variable, number and symbol exactly, but add a precise Chinese explanation of what the expression or definition means. Do not omit content. Context: {context}. Return JSON only: {{\"items\":[{{\"id\":\"...\",\"zh\":\"...\"}}]}}."""
    for index, batch in enumerate(base.batches(records)):
        result = base.call_model_json(
            token=token, model=model, system=system,
            user_payload={"items": batch}, cache_dir=cache_dir,
            cache_name=f"{cache_prefix}-translate-{index:03d}",
        )
        items = result.get("items") if isinstance(result, dict) else result
        returned = {
            str(item.get("id")): base.norm(item.get("zh"))
            for item in items or [] if isinstance(item, dict)
        }
        expected = [str(item["id"]) for item in batch]
        repair_ids = [item_id for item_id in expected if item_id not in returned or not base.CJK.search(returned[item_id])]
        if repair_ids:
            repaired = base.call_model_json(
                token=token,
                model=model,
                system=repair_system,
                user_payload={"items": [{"id": item_id, "text": source_by_id[item_id]} for item_id in repair_ids]},
                cache_dir=cache_dir,
                cache_name=f"{cache_prefix}-repair-{index:03d}",
                max_tokens=8000,
            )
            repaired_items = repaired.get("items") if isinstance(repaired, dict) else repaired
            for item in repaired_items or []:
                if isinstance(item, dict):
                    returned[str(item.get("id"))] = base.norm(item.get("zh"))
        missing = [item_id for item_id in expected if item_id not in returned]
        if missing:
            raise RuntimeError(f"translation response missing ids after repair: {missing[:20]}")
        for item_id in expected:
            value = returned[item_id]
            if not base.CJK.search(value):
                raise RuntimeError(f"translation for {item_id} still has no Chinese text after dedicated repair")
            translations[item_id] = value
    return translations


base.translate_records = translate_records_with_repairs


if __name__ == "__main__":
    runpy.run_module("generate_v082_reader_manifest_with_github_models_v6", run_name="__main__")
