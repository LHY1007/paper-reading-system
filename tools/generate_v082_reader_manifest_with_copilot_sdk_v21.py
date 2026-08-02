#!/usr/bin/env python3
from __future__ import annotations

"""Sentence-paired V0.8.2 generator.

The GPT-5.4 draft/review stack remains unchanged. Version 21 changes the
source unit from a whole PDF paragraph to repaired scientific sentences through
the V7 manifest builder and v082_sentence_pairs utility.
"""

import generate_v082_reader_manifest_with_copilot_sdk_v20 as v20


if __name__ == "__main__":
    v20.v13.main()
