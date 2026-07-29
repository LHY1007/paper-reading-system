#!/usr/bin/env python3
"""Canonical entry point for the V0.8.2 PDF-native evidence builder.

The implementation is deliberately kept in reviewable source files:
- build_pdf_native_manifest_v082_unpacked.py: layout-aware extraction core
- build_pdf_native_manifest_v082_final.py: cross-column and release gates
- build_pdf_native_manifest_v082_v3.py: high-confidence standalone formula detection
- build_pdf_native_manifest_v082_v4.py: PDF-outline titles, caption boundaries and original reference numbering
- build_pdf_native_manifest_v082_v5.py: complete caption-derived titles and extended-figure panel evidence
- build_pdf_native_manifest_v082_v6.py: native table reconstruction and Cell caption-title recovery
- build_pdf_native_manifest_v082_v7.py: cross-page legend reconstruction and supplementary title boundaries
"""

from build_pdf_native_manifest_v082_v7 import main


if __name__ == "__main__":
    main()
