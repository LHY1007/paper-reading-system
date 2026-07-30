#!/usr/bin/env python3
"""Canonical entry point for the V0.8.2 PDF-native evidence builder.

The v15 implementation preserves the verified author, figure, table and reference
repairs from v10 and reconstructs natural body paragraphs from page geometry with
per-page coverage diagnostics. Reader-facing Chinese content remains a separate,
fail-closed manifest stage.
"""

from build_pdf_native_manifest_v082_v15 import main


if __name__ == "__main__":
    main()
