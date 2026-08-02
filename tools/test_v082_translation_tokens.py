#!/usr/bin/env python3
from __future__ import annotations

import json

import generate_v082_reader_manifest_with_copilot_sdk_v17 as v17


def test_hyphenated_abbreviation_boundary() -> None:
    source = "This challenges distinct subgroups toward a TME-determined risk continuum."
    accepted = v17.component_translation_issues(
        "paragraph/abstract/p-0001",
        source,
        "这一结果将离散亚组模型修正为由TME决定的风险连续谱。",
    )
    assert not any("abbreviations not preserved" in issue for issue in accepted), accepted

    rejected = v17.component_translation_issues(
        "paragraph/abstract/p-0001",
        source,
        "这一结果将离散亚组模型修正为由微环境决定的风险连续谱。",
    )
    assert any("TME" in issue for issue in rejected), rejected
    assert not any("TME-" in issue for issue in rejected), rejected


def test_internal_hyphenated_marker() -> None:
    source = "PD-1 and CD8 were measured."
    accepted = v17.component_translation_issues(
        "paragraph/results/p-0002",
        source,
        "检测了PD-1和CD8。",
    )
    assert not any("abbreviations not preserved" in issue for issue in accepted), accepted


def test_flattened_reference_ids_are_not_scientific_numbers() -> None:
    source = (
        "Machine learning (ML) transformed DNA methylation diagnostics1. "
        "In 2021, WHO grade 3 criteria were updated (ref. 3). "
        "Several systems were proposed4–12, including immune enrichment6,9 "
        "and the model shown in Fig. 1a)13, followed by subclasses7."
    )
    chinese = (
        "机器学习（ML）改变了DNA甲基化诊断。2021年更新了WHO 3级标准。"
        "已有多种分类系统，其中包括免疫富集以及图1a所示模型，随后又划分了亚类。"
    )
    issues = v17.component_translation_issues(
        "paragraph/introduction/p-0002", source, chinese
    )
    assert not any(issue.startswith("number not preserved:") for issue in issues), issues


def test_reference_id_after_sentence_period() -> None:
    source = (
        "RNA data were processed as reported by Paramasivam et al.62. "
        "Genes with an FDR below 0.05 were retained."
    )
    chinese = "RNA数据按Paramasivam等人的方法处理，保留FDR低于0.05的基因。"
    issues = v17.component_translation_issues(
        "paragraph/bulk-rna-seq-data-analysis/p-0037", source, chinese
    )
    assert "number not preserved: 62" not in issues, issues
    assert "number not preserved: 0.05" not in issues, issues


def test_scientific_numbers_still_fail_closed() -> None:
    source = (
        "In 2021, WHO grade 3 tumors were identified in 26 cases "
        "(20.5%; P = 0.03) and are shown in Fig. 1a."
    )
    chinese = (
        "2021年发现WHO 3级肿瘤，占20.5%（P = 0.03），结果见图1a。"
    )
    issues = v17.component_translation_issues(
        "paragraph/results/p-0003", source, chinese
    )
    assert "number not preserved: 26" in issues, issues
    assert "number not preserved: 2021" not in issues, issues
    assert "number not preserved: 3" not in issues, issues
    assert "number not preserved: 20.5%" not in issues, issues
    assert "number not preserved: 0.03" not in issues, issues
    assert "number not preserved: 1" not in issues, issues


if __name__ == "__main__":
    test_hyphenated_abbreviation_boundary()
    test_internal_hyphenated_marker()
    test_flattened_reference_ids_are_not_scientific_numbers()
    test_reference_id_after_sentence_period()
    test_scientific_numbers_still_fail_closed()
    print(json.dumps({"translation_token_contracts": 5, "passed": True}, indent=2))
