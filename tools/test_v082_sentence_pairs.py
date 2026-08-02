#!/usr/bin/env python3
from __future__ import annotations

import unittest

import v082_sentence_pairs as pairs


class SentencePairContractTests(unittest.TestCase):
    def test_merges_supplementary_note_and_detached_figure_continuations(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "id": "p1",
                "english": [{"text": "Proteomic pathways largely corresponded to RNA pathways (details in Supplementary"}],
                "source_fragments": ["p1"],
            },
            {
                "type": "paragraph",
                "id": "p2",
                "english": [{"text": "Note). Specificity was imperfect (Extended Data Fig. 3)."}],
                "source_fragments": ["p2"],
            },
            {
                "type": "paragraph",
                "id": "p3",
                "english": [{"text": "(Fig. 4a,g). Multiple interactions were present."}],
                "source_fragments": ["p3"],
            },
        ]
        merged = pairs.merge_paragraph_blocks(blocks)
        self.assertEqual(len(merged), 1)
        text = pairs.paragraph_text(merged[0])
        self.assertIn("Supplementary Note).", text)
        self.assertIn("(Fig. 4a,g).", text)

    def test_merges_numeric_list_split_by_pdf_layout(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "id": "p1",
                "english": [{"text": "Neighborhood sizes were 50, 100, 200,"}],
                "source_fragments": ["p1"],
            },
            {
                "type": "paragraph",
                "id": "p2",
                "english": [{"text": "300, 400 and 500 µm. Z-scores were computed."}],
                "source_fragments": ["p2"],
            },
        ]
        merged = pairs.merge_paragraph_blocks(blocks)
        self.assertEqual(len(merged), 1)
        self.assertIn("200, 300", pairs.paragraph_text(merged[0]))

    def test_does_not_merge_real_lowercase_scientific_paragraph(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "id": "p1",
                "english": [{"text": "The first analysis was completed."}],
                "source_fragments": ["p1"],
            },
            {
                "type": "paragraph",
                "id": "p2",
                "english": [{"text": "snRNA-seq was then performed on frozen tissue."}],
                "source_fragments": ["p2"],
            },
        ]
        self.assertEqual(len(pairs.merge_paragraph_blocks(blocks)), 2)

    def test_scientific_sentence_splitter_preserves_versions_and_abbreviations(self) -> None:
        text = "CRAWDAD67 (v.1.0.1) was used at 10 µm intervals. Extended Data Fig. 3 shows the result. Smith et al. confirmed it."
        self.assertEqual(
            pairs.split_sentences(text),
            [
                "CRAWDAD67 (v.1.0.1) was used at 10 µm intervals.",
                "Extended Data Fig. 3 shows the result.",
                "Smith et al. confirmed it.",
            ],
        )

    def test_embedded_citations_are_extracted_only_from_parser_ids(self) -> None:
        items = [{"text": "Taxonomies predict behavior2–4.", "citation_ids": ["2", "3", "4"]}]
        groups = pairs.sentence_inline_groups({"english": items})
        self.assertEqual(len(groups), 1)
        self.assertEqual(pairs.citation_set(groups[0]), {"2", "3", "4"})
        self.assertEqual(pairs.norm(pairs.inline_text(groups[0])), "Taxonomies predict behavior.")

    def test_chinese_embedded_citations_are_extracted(self) -> None:
        english = [{"text": "Evidence", "citation_ids": ["16", "17", "18"]}]
        chinese = pairs.translation_inline_items("其他研究16–18支持这一结果。", english)
        self.assertEqual(pairs.citation_set(chinese), {"16", "17", "18"})
        self.assertEqual(pairs.norm(pairs.inline_text(chinese)), "其他研究支持这一结果。")


if __name__ == "__main__":
    unittest.main()
