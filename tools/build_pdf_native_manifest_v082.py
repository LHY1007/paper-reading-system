#!/usr/bin/env python3
"""Canonical entry point for the V0.8.2 PDF-native manifest builder.

The implementation is deliberately kept in reviewable source files:
- build_pdf_native_manifest_v082_unpacked.py: layout-aware extraction core
- build_pdf_native_manifest_v082_final.py: cross-column and release gates
- build_pdf_native_manifest_v082_v3.py: high-confidence standalone formula detection
"""

from build_pdf_native_manifest_v082_v3 import main


if __name__ == "__main__":
    main()
