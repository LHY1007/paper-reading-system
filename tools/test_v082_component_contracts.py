#!/usr/bin/env python3
from __future__ import annotations

import copy

import generate_v082_reader_manifest_with_copilot_sdk_v15 as v15
import generate_v082_reader_manifest_with_copilot_sdk_v16 as v16
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


def test_review_asset_order_contract() -> None:
    manifest = {
        "paper": {"key": "andani-2025"},
        "overview": {},
        "sections": [],
        "terms": [],
        "references": [],
        "assets": [
            {"id": "figure-1", "kind": "figure"},
            {
                "id": "extended-data-table-1",
                "kind": "table",
                "source_render": "ai-verified-structured-table-transcription-v1",
            },
            {"id": "figure-2", "kind": "figure"},
        ],
    }
    review = {
        "version": "v082-strong-ai-component-review-1",
        "paper_key": "andani-2025",
        "passed": True,
        "translation": [],
        "figures": [
            {"id": "figure-1", "passed": True, "source_image_present": True},
            {"id": "extended-data-table-1", "passed": True, "source_image_present": True},
            {"id": "figure-2", "passed": True, "source_image_present": True},
        ],
        "tables": [
            {"id": "extended-data-table-1", "passed": True, "source_image_present": True},
        ],
        "overview": {"passed": True},
        "terms": {"passed": True, "accepted_count": 0},
        "references": {"passed": True, "total": 0},
    }
    result = strong_review.validate(manifest, review)
    assert result["passed"], result["errors"]

    invalid = copy.deepcopy(review)
    invalid["figures"] = [invalid["figures"][0], invalid["figures"][2], invalid["figures"][1]]
    result = strong_review.validate(manifest, invalid)
    assert not result["passed"], "review order mismatch was not rejected"


if __name__ == "__main__":
    test_table_upgrade_contract()
    test_normalizer_never_rewrites_reviewed_tables()
    test_panel_grounding_contract()
    test_visual_panel_inventory_normalization()
    test_review_asset_order_contract()
    print("V0.8.2 component contracts passed")
