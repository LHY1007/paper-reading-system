#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import generate_v082_reader_manifest_with_google_translate_v8 as v8
import generate_v082_reader_manifest_with_google_translate_v9 as v9


_original_first_clause = v8.first_clause


def specific_chinese_first_clause(text: str, limit: int = 42) -> str:
    value = _original_first_clause(text, limit=limit)
    if not v8.CJK.search(value) or len(v8.norm(value)) < 4:
        return "研究对象、比较方式与直接结果"
    return value


v8.first_clause = specific_chinese_first_clause
v8.translate_piece = v9.lenient_translate_piece
v8.v7.translate_all = v8.google_translate_all
v8.v7.generate_figure_studies = v8.deterministic_figure_studies

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).name)
    v8.v7.main()
