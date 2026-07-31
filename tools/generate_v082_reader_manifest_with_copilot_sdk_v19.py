#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_copilot_sdk_v18 as v18


v13 = v18.v13
v17 = v18.v17
DEFAULT_BATCH_ITEMS = max(1, int(os.environ.get("V082_TRANSLATION_BATCH_ITEMS", "6")))
DEFAULT_BATCH_CHARS = max(1000, int(os.environ.get("V082_TRANSLATION_BATCH_CHARS", "8500")))


def norm(value: Any) -> str:
    return v13.norm(value)


def stable_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def chunk_translation_records(
    records: list[dict[str, str]],
    *,
    max_items: int = DEFAULT_BATCH_ITEMS,
    max_chars: int = DEFAULT_BATCH_CHARS,
) -> list[list[dict[str, str]]]:
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_chars = 0
    for record in records:
        item = {"id": str(record.get("id") or ""), "text": norm(record.get("text"))}
        item_chars = len(item["text"])
        if current and (len(current) >= max_items or current_chars + item_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)
    return batches


def response_item_map(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = (
            payload.get("items")
            or payload.get("translations")
            or payload.get("results")
            or []
        )
    else:
        values = []
    output: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        item_id = str(value.get("id") or "")
        if item_id:
            output[item_id] = value
    return output


def draft_batch(
    batch: list[dict[str, str]],
    *,
    paper_title: str,
    token: str,
    primary_model: str,
    cache_dir: Path,
) -> dict[str, str]:
    payload_items = [
        {"id": item["id"], "source_en": item["text"]}
        for item in batch
    ]
    system = f"""你是生物医学论文的专业中英翻译编辑。论文题目：{paper_title}。
以下JSON包含多个彼此独立的论文内容单元。必须逐个单元完整翻译，不得把不同单元合并、互相补写或省略。
保持每个英文单元的全部信息、逻辑关系、不确定性、数字、单位、P值、置信区间、基因/蛋白符号、细胞状态、队列名称、缩写、图表编号和参考文献编号。
禁止总结、解释、扩写或改变结论强度。每个输入id必须在输出中恰好出现一次。
返回严格JSON：{{"items":[{{"id":"输入id","zh":"完整中文译文"}}]}}。"""
    cache_key = stable_name(json.dumps(payload_items, ensure_ascii=False, sort_keys=True))
    result = v13.base.call_model_json(
        token=token,
        model=primary_model,
        system=system,
        user_payload={"items": payload_items},
        cache_dir=cache_dir,
        cache_name=f"translation-batch-draft-{cache_key}",
        max_tokens=30000,
    )
    mapped = response_item_map(result)
    return {item["id"]: norm((mapped.get(item["id"]) or {}).get("zh")) for item in batch}


def review_batch(
    batch: list[dict[str, str]],
    drafts: dict[str, str],
    *,
    paper_title: str,
    token: str,
    reviewer_model: str,
    cache_dir: Path,
    cache_suffix: str,
    required_fixes: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    payload_items = []
    for item in batch:
        value: dict[str, Any] = {
            "id": item["id"],
            "source_en": item["text"],
            "candidate_zh": drafts.get(item["id"], ""),
        }
        if required_fixes and required_fixes.get(item["id"]):
            value["required_fixes"] = required_fixes[item["id"]]
        payload_items.append(value)
    system = f"""你是第二位独立的生物医学翻译审校者。论文题目：{paper_title}。
逐个核对JSON中的每个独立单元。检查遗漏、误译、方向反转、比较对象、否定词、数值、统计量、基因蛋白符号、缩写、图表编号和引用编号。
必须分别修订每个单元，禁止合并不同id的内容，禁止添加解释。只有修订后的zh_final完整准确时，该单元passed才可为true。
每个输入id必须在输出中恰好出现一次。返回严格JSON：
{{"passed":true,"items":[{{"id":"输入id","passed":true,"issues":[],"zh_final":"完整审校译文"}}]}}。"""
    cache_key = stable_name(json.dumps(payload_items, ensure_ascii=False, sort_keys=True))
    result = v13.base.call_model_json(
        token=token,
        model=reviewer_model,
        system=system,
        user_payload={"items": payload_items},
        cache_dir=cache_dir,
        cache_name=f"translation-batch-{cache_suffix}-{cache_key}",
        max_tokens=30000,
    )
    return response_item_map(result)


def batched_translate_all(
    records: list[dict[str, str]],
    *,
    token: str,
    model: str,
    cache_dir: Path,
    paper_title: str,
    cache_prefix: str,
) -> dict[str, str]:
    del model
    primary_model, reviewer_model, _ = v13.model_settings()
    output: dict[str, str] = {}
    strong_cache = cache_dir / "strong-ai-v19" / cache_prefix
    batches = chunk_translation_records(records)
    total = len(records)
    completed = 0

    for batch_index, batch in enumerate(batches, start=1):
        drafts = draft_batch(
            batch,
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            cache_dir=strong_cache,
        )
        reviewed = review_batch(
            batch,
            drafts,
            paper_title=paper_title,
            token=token,
            reviewer_model=reviewer_model,
            cache_dir=strong_cache,
            cache_suffix="review",
        )

        final_values: dict[str, str] = {}
        review_issues: dict[str, list[str]] = {}
        failed_ids: set[str] = set()
        required_fixes: dict[str, list[str]] = {}
        for item in batch:
            item_id = item["id"]
            response = reviewed.get(item_id) or {}
            final_zh = norm(response.get("zh_final"))
            issues = [norm(value) for value in response.get("issues", []) if norm(value)]
            local_issues = v17.component_translation_issues(item_id, item["text"], final_zh)
            final_values[item_id] = final_zh
            review_issues[item_id] = issues
            if response.get("passed") is not True or local_issues:
                failed_ids.add(item_id)
                required_fixes[item_id] = local_issues or ["independent reviewer did not explicitly accept this item"]

        for repair_attempt in range(1, 3):
            if not failed_ids:
                break
            repair_batch_items = [item for item in batch if item["id"] in failed_ids]
            repaired = review_batch(
                repair_batch_items,
                final_values,
                paper_title=paper_title,
                token=token,
                reviewer_model=reviewer_model,
                cache_dir=strong_cache,
                cache_suffix=f"repair-{repair_attempt}",
                required_fixes=required_fixes,
            )
            next_failed: set[str] = set()
            next_fixes: dict[str, list[str]] = {}
            for item in repair_batch_items:
                item_id = item["id"]
                response = repaired.get(item_id) or {}
                candidate = norm(response.get("zh_final"))
                if candidate:
                    final_values[item_id] = candidate
                review_issues[item_id].extend(
                    norm(value) for value in response.get("issues", []) if norm(value)
                )
                local_issues = v17.component_translation_issues(
                    item_id, item["text"], final_values.get(item_id, "")
                )
                if response.get("passed") is not True or local_issues:
                    next_failed.add(item_id)
                    next_fixes[item_id] = local_issues or [
                        "independent reviewer did not explicitly accept the repaired item"
                    ]
                else:
                    v18.REVIEW_RESPONSES["translation"][item_id] = response
            failed_ids = next_failed
            required_fixes = next_fixes

        for item in batch:
            item_id = item["id"]
            if item_id in failed_ids:
                # Fail closed but recover at single-component granularity. The
                # established per-item path retains all existing reviewer and
                # mechanical gates and is only used for unresolved batch items.
                output[item_id] = v13.translate_one(
                    item["text"],
                    item_id=item_id,
                    paper_title=paper_title,
                    token=token,
                    primary_model=primary_model,
                    reviewer_model=reviewer_model,
                    cache_dir=strong_cache / "single-fallback",
                )
            else:
                final_zh = final_values[item_id]
                local_issues = v17.component_translation_issues(item_id, item["text"], final_zh)
                if local_issues:
                    raise RuntimeError(f"batched translation validation failed for {item_id}: {local_issues}")
                response = reviewed.get(item_id) or v18.REVIEW_RESPONSES["translation"].get(item_id) or {}
                if response.get("passed") is not True:
                    # A repaired item may have been recorded directly above.
                    response = v18.REVIEW_RESPONSES["translation"].get(item_id) or response
                if response.get("passed") is not True:
                    raise RuntimeError(f"batched translation reviewer did not accept {item_id}")
                v18.REVIEW_RESPONSES["translation"][item_id] = response
                v13.REVIEW_LOG["translation"].append({
                    "id": item_id,
                    "source_sha256": hashlib.sha256(item["text"].encode("utf-8")).hexdigest(),
                    "draft_model": primary_model,
                    "review_model": reviewer_model,
                    "review_issues": review_issues[item_id],
                    "local_issues": [],
                    "batch_index": batch_index,
                    "passed": True,
                })
                output[item_id] = final_zh
            completed += 1
            print(json.dumps({
                "component": "translation",
                "completed": completed,
                "total": total,
                "batch": batch_index,
                "batches": len(batches),
                "id": item_id,
            }, ensure_ascii=False), flush=True)

    return output


v13.sequential_translate_all = batched_translate_all


if __name__ == "__main__":
    v13.main()
