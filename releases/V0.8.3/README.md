# V0.8.3 Formal Release

V0.8.3 is the current formal reader standard.

## Fixed defect

Terminology highlighting was visible but terminology explanations could fail to open when the term was clicked, especially inside dynamically rendered figure-study content. V0.8.3 fixes this by routing `.term-pop` activation through one capture-phase delegated handler shared by the bilingual body, right-side figure viewer, and full-screen figure-study document.

## Locked behavior

- Clicking a highlighted term opens `#termTooltip` with the term title and its `data-tip` / `data-definition` explanation.
- Enter and Space activate a focused term.
- Clicking outside closes the explanation.
- A second click on the active term toggles the explanation closed.
- Dynamic term nodes inserted after page load work without event rebinding.
- Term activation is isolated from sentence-pair highlighting, annotation tools, figure-card actions, and other legacy click handlers.
- V0.8.2 FINAL_VALIDATED2 content/interaction features remain mandatory: sentence-level bilingual pairing, inline citations, inline figure/table references, terminology highlighting, figure preview, per-panel figure study, reference popups, annotation tools, and reader settings.

## Formal contract and gates

- `config/v083_release.json`
- `tools/patch_v083_term_interaction.py`
- `tools/validate_v083_term_interaction.py`

The V0.8.2 reference reader SHA-256 remains `e66cc0fd7b2b7add744afd3db5f0d02106f3871bc954932f46053850e6ed5569`. The locally patched V0.8.3 formal reference reader SHA-256 is `c65aa3996657300180ba6c983c6145496f8efe221d1b1aeb58eb6e59037b0915`.
