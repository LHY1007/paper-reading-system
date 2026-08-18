# V0.8.3 Formal Release

V0.8.3 is the current production reader standard and the repository mainline.

## Canonical usage

- Default production branch: `main`
- Version-pinned branch: `v0.8.3`
- Stable alias branch: `latest`
- Version marker: `VERSION`
- Current standard contract: `config/latest_reader_standard.json`
- Release contract: `config/v083_release.json`

Other users should consume `main` by default. `main`, `v0.8.3` and `latest` are intentionally kept at the same production commit when V0.8.3 is the current release.

## Current acceptance reference

The current V0.8.3 acceptance reader is:

`Haviv_et_al_2024_COVET_ENVI_V0.8.3_FORMAT_LOCKED.html`

Paper: *The covariance environment defines cellular niches for spatial inference* (Haviv et al., Nature Biotechnology, 2024; DOI 10.1038/s41587-024-02193-4).

Reference SHA-256:

`b94592fa77f3168d8f41cb3a7c7a0047fd5c49de84db91a3657c8e29d095138a`

The acceptance record is stored at `releases/V0.8.3/reference/haviv-covet-envi-validation.json`. It verifies the fixed component hierarchy, sentence-pair structure, inline citations, inline figure/table links, terminology interaction, figure-study interaction, 16 main/Extended Data figure-study entries and 117 panel/logical-block explanations.

The acceptance reader is a behavior/layout reference. It does not weaken source-completeness gates for future papers.

## Fixed defects

### Terminology interaction

Terminology highlighting was visible but terminology explanations could fail to open when the term was clicked, especially inside dynamically rendered figure-study content. V0.8.3 fixes this by routing `.term-pop` activation through one capture-phase delegated handler shared by the bilingual body, right-side figure viewer, and full-screen figure-study document.

### Fixed text-component formatting

Paper-specific generators are no longer allowed to invent replacement markup for the hero metadata or one-page overview. The locked overview component is `#overview-bilingual-folded > section.card#overview-clone`, with six `.qa-grid > article.qa` blocks, one method `h3 + p`, and one `.story > b + p`. Hero metadata must use `.hero > .paper-info > .metadata` rows. Custom alternatives such as `.overview-grid`, `.overview-card`, `.method-flow` and `.paper-info-grid` fail release.

This prevents regressions where a paper introduces new classes with no frozen-shell CSS, causing headings, paragraph spacing and metadata typography to fall back to browser/global defaults.

## Locked behavior

- Clicking a highlighted term opens `#termTooltip` with the term title and its `data-tip` / `data-definition` explanation.
- Enter and Space activate a focused term.
- Clicking outside closes the explanation.
- A second click on the active term toggles the explanation closed.
- Dynamic term nodes inserted after page load work without event rebinding.
- Term activation is isolated from sentence-pair highlighting, annotation tools, figure-card actions, and other legacy click handlers.
- Hero metadata, one-page overview, method summary and overview conclusion use the fixed reader component hierarchy and frozen-shell typography.
- Sentence-level bilingual pairing, inline citations, inline figure/table references, terminology highlighting, figure preview, per-panel figure study, reference popups, annotation tools and reader settings are mandatory.
- If the final article cites supplementary figures/tables absent from the uploaded main PDF, the builder must retrieve the final published supplementary information and integrate the real assets rather than silently omit them.

## Formal contract and gates

- `config/v083_release.json`
- `config/latest_reader_standard.json`
- `tools/patch_v083_term_interaction.py`
- `tools/validate_v083_term_interaction.py`
- `tools/validate_v083_component_format.py`
- `tools/test_v083_component_format.py`
- `.github/workflows/v083_component_format_gate.yml`

Historical references remain recorded in `config/latest_reader_standard.json` for regression comparison, but the Haviv V0.8.3 FORMAT_LOCKED reader is the current acceptance reference.
