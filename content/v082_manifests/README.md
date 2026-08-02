# V0.8.2 reader-ready content manifests

This directory contains only completed bilingual paper manifests that are eligible for HTML rendering.

A PDF evidence manifest is not a completed reader manifest. Automatic machine translation of raw parser output is also not sufficient. Every file in this directory must be produced from the paper-specific task under `config/v082_reader_content_plans/` and must pass, in order:

1. `schemas/paper_content_manifest_v082.schema.json`
2. `tools/validate_v082_reader_content_quality.py`
3. `tools/validate_v082_final_manifest.py` with the source-native audit
4. `tools/validate_v082_manifest_code_boundary.py`

Only after those gates pass may `tools/render_v082_from_frozen_shell.py` create a reader HTML. A rendered reader must then pass `tools/audit_v082_reader_experience.py` against the original V0.8.2 CANVAS reader, in addition to shell, component, architecture and browser checks.

Do not commit parser diagnostics, identity translations, placeholder authors, generic figure titles, captions reused as figure-study prose, or silently renumbered incomplete references here.
