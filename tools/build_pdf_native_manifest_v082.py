#!/usr/bin/env python3
"""Canonical entry point for the V0.8.2 PDF-native evidence builder.

Parser v16 preserves the page-aware body reconstruction from v15 and adds
layout-ordered references, complete source authors and affiliations, descriptive
figure titles, panel evidence, Science publication metadata, and high-confidence
formula filtering. Reader-facing Chinese content remains a separate fail-closed stage.
"""

from build_pdf_native_manifest_v082_v16 import main


if __name__ == "__main__":
    main()
