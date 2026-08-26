#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from context_clues_pipeline.data import prepare_context_clues_events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert mapped structured EHR tables into Context Clues events."
    )
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--concept-map", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--visit-code", default="Visit/IP")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = prepare_context_clues_events(
        input_root=args.input_root,
        concept_map_path=args.concept_map,
        output_root=args.output_root,
        visit_code=args.visit_code,
        overwrite=args.overwrite,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
