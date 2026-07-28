#!/usr/bin/env python3
from __future__ import annotations

import validate_v082_canvas_shell_lock_core as core


core.DYNAMIC_SCRIPT_IDS.update({
    "referenceData",
    "canvas-reader-v060-script",
    "canvas-reader-v061-script",
    "canvas-reader-v062-script",
    "canvas-v073-script",
    "canvas-v077-script",
    "canvas-v078-final-script",
    "canvas-v081-script",
    "canvas-v082-script",
})
if "#crossRefPreviewStore" not in core.CONTENT_SELECTORS:
    core.CONTENT_SELECTORS.append("#crossRefPreviewStore")


if __name__ == "__main__":
    core.main()
