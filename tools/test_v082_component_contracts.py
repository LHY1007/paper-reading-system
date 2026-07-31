#!/usr/bin/env python3
from __future__ import annotations

import copy

import generate_v082_reader_manifest_with_copilot_sdk_v15 as v15
import generate_v082_reader_manifest_with_copilot_sdk_v16 as v16
import generate_v082_reader_manifest_with_copilot_sdk_v17 as v17
import generate_v082_reader_manifest_with_copilot_sdk_v18 as v18
import normalize_v082_paper_tables as table_normalizer
import validate_v082_reader_semantics_v4 as semantics
import validate_v082_strong_ai_review as strong_review


def test_table_upgrade_contract() -> None:
    source = {
        "id": "extended-data-table-1",
        "kind": "figure",
        "title_en": "Extended Data Table 1 | Model comparison",
        "caption_en": "Performance comparison across methods.",
        "source_page": 21,
        "image_src": "data:image/png;base64,QUJDRA==",
    }
    target = {
        **source,
        "kind": "table",
        "source_render": (
            "ai-verified-structured-table-transcription-v1;"
            "source-page=21;source-image-retained"
        ),
        "table": {
            "headers": ["Method（方法）", "PSNR"],
            "rows": [["HistoPlexer", "14.206 ± 0.029"]],
        },
    }
    passed, errors = semantics.allowed_table_upgrade(target, source)
    assert passed, errors

    invalid = copy.deepcopy(target)
    invalid["source_render"] = "hard-coded fallback"
    passed, errors = semantics.allowed_table_upgrade(invalid, source)
    assert not passed and errors


def test_normalizer_never_rewrites_reviewed_tables() -> None:
    table = {
        "id": "extended-data-table-1",
        "kind": "table",
        "image_src": "data:image/png;base64,QUJDRA==",
        "source_render": (
            "ai-verified-structured-table-transcription-v1;"
            "source-page=21;source-image-retained"
        ),
        "table": {
            "headers": ["Method（方法）", "PSNR"],
            "rows": [["HistoPlexer", "14.206 ± 0.029"]],
        },
    }
    manifest = {
        "paper": {"key": "andani-2025"},
        "assets": [
            table,
            *[
                {
                    **copy.deepcopy(table),
                    "id": f"extended-data-table-{index}",
                }
                for index in (2, 3, 4)
            ],
        ],
    }
    before = copy.deepcopy(manifest)
    after = table_normalizer.normalize_manifest(manifest)
    assert after == before, "normalizer altered independently reviewed table content"


def valid_study(explanation: str) -> dict:
    return {
        "intro": "该图在全文中用于建立免疫细胞空间分布与模型输出之间的证据联系。",
        "overview": "阅读时先识别分组、坐标和颜色编码，再比较不同面板中的直接测量结果与模型预测结果。",
        "panels": [{
            "label": "A",
            "title": "CD8细胞比例与模型预测性能",
            "explanation": explanation,
        }],
        "conclusion": "该面板把具体的细胞标志物和定量结果连接到论文的主要模型验证结论。",
        "boundary": "这里报告的是测量和预测的一致性，不等同于已经证明临床因果效应。",
    }


def test_panel_grounding_contract() -> None:
    v15._CURRENT_PAYLOAD = {
        "source_panels": [{
            "label": "A",
            "source_text": "CD8 abundance reached 42% and was compared with HistoPlexer predictions.",
        }],
        "caption_en": "Panel A compares CD8 abundance and HistoPlexer output.",
        "nearby_body_evidence": [],
    }
    generic = valid_study(
        "该面板对不同组别进行了比较，并用于支持全文中的主要结论；结果需要结合图例和相邻面板理解。"
    )
    issues = v15.study_issues_grounded(generic, ["A"])
    assert any("source-traceable" in issue for issue in issues), issues

    grounded = valid_study(
        "面板A显示CD8细胞丰度达到42%，并将这一直接测量结果与HistoPlexer的预测输出进行比较；两者的一致趋势构成模型在该细胞标志物上的验证证据。"
    )
    issues = v15.study_issues_grounded(grounded, ["A"])
    assert not any("source-traceable" in issue for issue in issues), issues
    assert not any("direct observed" in issue for issue in issues), issues


def test_visual_panel_inventory_normalization() -> None:
    assert v16.normalize_labels(["A-D"]) == ["A", "B", "C", "D"]
    assert v16.normalize_labels(["panel a", "B", "B"]) == ["A", "B"]
    assert v16.normalize_labels([]) == ["整图"]


def test_component_specific_translation_completeness() -> None:
    title_issues = v17.component_translation_issues(
        "section-title/abstract", "Abstract", "摘要"
    )
    assert "translation implausibly short" not in title_issues, title_issues

    asset_title_issues = v17.component_translation_issues(
        "asset-title/figure-1", "Results", "结果"
    )
    assert "translation implausibly short" not in asset_title_issues, asset_title_issues

    body_issues = v17.component_translation_issues(
        "paragraph/results/p-0001",
        "The complete paragraph contains substantially more scientific information than this translation.",
        "结果",
    )
    assert "translation implausibly short" in body_issues, body_issues


def test_explicit_reviewer_acceptance_contract() -> None:
    for category in v18.REVIEW_RESPONSES:
        v18.REVIEW_RESPONSES[category].clear()
    v18.REVIEW_RESPONSES["translation"]["paragraph/results/p-0001"] = {"passed": True}
    v18.REVIEW_RESPONSES["panel_inventory"]["figure-1"] = {"passed": True}
    v18.REVIEW_RESPONSES["figure"]["figure-1"] = {"passed": True}
    v18.REVIEW_RESPONSES["table"]["extended-data-table-1"] = {"passed": True}
    v18.REVIEW_RESPONSES["overview"]["paper"] = {"passed": True}
    review_log = {
        "translation": [{"id": "paragraph/results/p-0001"}],
        "figures": [{"id": "figure-1", "panel_inventory": {"passed": True}}],
        "tables": [{"id": "extended-data-table-1"}],
        "overview": {},
    }
    errors = v18.enforce_independent_reviewer_acceptance(review_log)
    assert not errors, errors
    assert review_log["translation"][0]["independent_reviewer_accepted"] is True
    assert review_log["figures"][0]["independent_reviewer_accepted"] is True
    assert review_log["figures"][0]["panel_inventory"]["independent_reviewer_accepted"] is True
    assert review_log["tables"][0]["independent_reviewer_accepted"] is True
    assert review_log["overview"]["independent_reviewer_accepted"] is True

    v18.REVIEW_RESPONSES["figure"]["figure-1"] = {"passed": False}
    rejected = {
        "translation": [{"id": "paragraph/results/p-0001"}],
        "figures": [{"id": "figure-1", "panel_inventory": {"passed": True}}],
        "tables": [{"id": "extended-data-table-1"}],
        "overview": {},
    }
    errors = v18.enforce_independent_reviewer_acceptance(rejected)
    assert any(item["component"] == "figure" for item in errors), errors


def reviewed_figure(asset_id: str, labels: list[str]) -> dict:
    return {
        "id": asset_id,
        "passed": True,
        "source_image_present": True,
        "independent_reviewer_accepted": True,
        "panel_labels": labels,
        "panel_inventory": {
            "passed": True,
            "source_image_present": True,
            "visual_labels": labels,
            "independent_reviewer_accepted": True,
        },
    }


def test_review_asset_order_and_exact_coverage_contract() -> None:
    manifest = {
        "paper": {"key": "andani-2025"},
        "overview": {},
        "sections": [{
            "id": "results",
            "blocks": [{"type": "paragraph", "id": "p-0001"}],
        }],
        "terms": [],
        "references": [],
        "assets": [
            {"id": "figure-1", "kind": "figure", "caption_en": "Figure one caption."},
            {
                "id": "extended-data-table-1",
                "kind": "table",
                "caption_en": "Extended table caption.",
                "source_render": "ai-verified-structured-table-transcription-v1",
                "table": {
                    "headers": ["Method（方法）", "PSNR"],
                    "rows": [["HistoPlexer（HistoPlexer）", "14.206 ± 0.029"]],
                },
            },
            {"id": "figure-2", "kind": "figure", "caption_en": "Figure two caption."},
        ],
    }
    required_translations = [
        "paragraph/results/p-0001",
        "asset-caption/figure-1",
        "asset-caption/extended-data-table-1",
        "asset-caption/figure-2",
        "table/extended-data-table-1/h/0",
        "table/extended-data-table-1/h/1",
        "table/extended-data-table-1/r/0/0",
    ]
    review = {
        "version": "v082-strong-ai-component-review-1",
        "paper_key": "andani-2025",
        "passed": True,
        "independent_reviewer_acceptance_passed": True,
        "models": {"primary": "gpt-5.4", "reviewer": "gpt-5.4", "vision": "gpt-5.4"},
        "translation": [
            {"id": item, "passed": True, "independent_reviewer_accepted": True}
            for item in required_translations
        ],
        "figures": [
            reviewed_figure("figure-1", ["A"]),
            reviewed_figure("extended-data-table-1", ["整图"]),
            reviewed_figure("figure-2", ["A", "B"]),
        ],
        "tables": [
            {"id": "extended-data-table-1", "passed": True, "source_image_present": True, "independent_reviewer_accepted": True},
        ],
        "overview": {"passed": True, "independent_reviewer_accepted": True},
        "terms": {"passed": True, "accepted_count": 0},
        "references": {"passed": True, "total": 0},
    }
    result = strong_review.validate(manifest, review)
    assert result["passed"], result["errors"]

    invalid_order = copy.deepcopy(review)
    invalid_order["figures"] = [
        invalid_order["figures"][0],
        invalid_order["figures"][2],
        invalid_order["figures"][1],
    ]
    result = strong_review.validate(manifest, invalid_order)
    assert not result["passed"], "review order mismatch was not rejected"

    missing_paragraph = copy.deepcopy(review)
    missing_paragraph["translation"] = missing_paragraph["translation"][1:]
    result = strong_review.validate(manifest, missing_paragraph)
    assert not result["passed"], "missing paragraph review was not rejected"

    wrong_panel_inventory = copy.deepcopy(review)
    wrong_panel_inventory["figures"][2]["panel_inventory"]["visual_labels"] = ["A"]
    result = strong_review.validate(manifest, wrong_panel_inventory)
    assert not result["passed"], "panel inventory mismatch was not rejected"


if __name__ == "__main__":
    test_table_upgrade_contract()
    test_normalizer_never_rewrites_reviewed_tables()
    test_panel_grounding_contract()
    test_visual_panel_inventory_normalization()
    test_component_specific_translation_completeness()
    test_explicit_reviewer_acceptance_contract()
    test_review_asset_order_and_exact_coverage_contract()
    print("V0.8.2 component contracts passed")
