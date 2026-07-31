#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ANDANI_TABLES: dict[str, dict[str, list[list[str]] | list[str]]] = {
    "extended-data-table-1": {
        "headers": ["Setting", "Method", "MS-SSIM ↑", "PSNR ↑", "RMSE-SW ↓", "MSE-colocalization ↓"],
        "rows": [
            ["MP", "CycleGAN", "0.130 ± 0.031", "4.586 ± 0.713", "0.587 ± 0.047", "0.1885 ± 0.0223"],
            ["MP", "Pix2Pix", "0.276 ± 0.004", "13.680 ± 0.043", "0.202 ± 0.002", "0.0071 ± 0.0003"],
            ["MP", "PyramidP2P", "0.284 ± 0.005", "13.894 ± 0.173", "0.197 ± 0.004", "0.0081 ± 0.0013"],
            ["MP", "HistoPlexer", "0.301 ± 0.003", "14.206 ± 0.029", "0.194 ± 0.001", "0.0068 ± 0.0004"],
            ["MP", "HistoPlexer-FM", "0.293 ± 0.005", "14.552 ± 0.104", "0.189 ± 0.002", "0.0128 ± 0.0012"],
            ["SP", "CycleGAN", "0.138 ± 0.008", "5.175 ± 0.090", "0.548 ± 0.012", "0.3084 ± 0.0367"],
            ["SP", "Pix2Pix", "0.260 ± 0.001", "13.015 ± 0.009", "0.218 ± 0.001", "0.0324 ± 0.0016"],
            ["SP", "PyramidP2P", "0.264 ± 0.016", "13.216 ± 0.483", "0.214 ± 0.011", "0.0299 ± 0.0045"],
            ["SP", "HistoPlexer", "0.279 ± 0.002", "13.354 ± 0.038", "0.210 ± 0.002", "0.0302 ± 0.0010"],
            ["SP", "HistoPlexer-FM", "0.268 ± 0.013", "13.248 ± 0.206", "0.212 ± 0.002", "0.0514 ± 0.0164"],
        ],
    },
    "extended-data-table-2": {
        "headers": ["Protein", "MS-SSIM ↑", "PSNR ↑", "RMSE-SW ↓"],
        "rows": [
            ["CD16", "0.219 ± 0.008", "12.436 ± 0.114", "0.185 ± 0.004"],
            ["CD20", "0.520 ± 0.011", "19.528 ± 0.267", "0.102 ± 0.002"],
            ["CD3", "0.322 ± 0.001", "15.285 ± 0.065", "0.147 ± 0.001"],
            ["CD31", "0.682 ± 0.009", "24.305 ± 0.260", "0.054 ± 0.002"],
            ["CD8a", "0.404 ± 0.003", "16.667 ± 0.061", "0.117 ± 0.000"],
            ["HLA-ABC", "0.080 ± 0.002", "9.272 ± 0.115", "0.327 ± 0.004"],
            ["HLA-DR", "0.221 ± 0.007", "12.478 ± 0.136", "0.188 ± 0.004"],
            ["MelanA", "0.249 ± 0.005", "11.782 ± 0.065", "0.252 ± 0.002"],
            ["S100", "0.221 ± 0.002", "10.616 ± 0.046", "0.282 ± 0.000"],
            ["SOX10", "0.214 ± 0.012", "12.649 ± 0.428", "0.216 ± 0.011"],
            ["gp100", "0.180 ± 0.003", "10.693 ± 0.144", "0.275 ± 0.002"],
        ],
    },
    "extended-data-table-3": {
        "headers": ["Setting", "Method", "MS-SSIM ↑", "PSNR ↑", "RMSE-SW ↓"],
        "rows": [
            ["MP", "Pix2Pix", "0.654", "19.694", "0.075"],
            ["MP", "PyramidP2P", "0.647", "19.672", "0.075"],
            ["MP", "HistoPlexer", "0.656", "19.804", "0.072"],
        ],
    },
    "extended-data-table-4": {
        "headers": ["Setting", "Method", "MS-SSIM ↑", "PSNR ↑", "RMSE-SW ↓"],
        "rows": [
            ["MP", "Pix2Pix", "0.675", "20.132", "0.097"],
            ["MP", "PyramidP2P", "0.638", "18.726", "0.114"],
            ["MP", "HistoPlexer", "0.704", "20.642", "0.092"],
        ],
    },
}


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    paper_key = str((manifest.get("paper") or {}).get("key") or "")
    if paper_key != "andani-2025":
        return manifest

    seen: set[str] = set()
    for asset in manifest.get("assets") or []:
        asset_id = str(asset.get("id") or "")
        table = ANDANI_TABLES.get(asset_id)
        if table is None:
            continue
        asset["kind"] = "table"
        asset["table"] = {
            "headers": list(table["headers"]),
            "rows": [list(row) for row in table["rows"]],
        }
        asset["hires"] = True
        asset["source_render"] = "structured transcription from the exact PDF table page; original embedded page image retained"
        seen.add(asset_id)

    missing = sorted(set(ANDANI_TABLES) - seen)
    if missing:
        raise RuntimeError(f"Andani structured table assets missing from manifest: {missing}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Add source-faithful structured tables required by individual V0.8.2 papers")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.manifest
    manifest = normalize_manifest(json.loads(args.manifest.read_text("utf-8")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "paper_key": (manifest.get("paper") or {}).get("key"),
        "structured_table_count": sum(1 for item in manifest.get("assets") or [] if item.get("kind") == "table"),
        "output": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
