#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from context_clues_pipeline.data import build_concept_map_template


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export local EHR concepts for explicit OMOP mapping."
    )
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--existing-map", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = build_concept_map_template(
        input_root=args.input_root,
        output_path=args.output,
        existing_map=args.existing_map,
        overwrite=args.overwrite,
    )
    print(f"Wrote {len(frame):,} local concepts to {args.output}")
    print("Fill target_code and set mapping_status=approved only after clinical/code review.")


if __name__ == "__main__":
    main()
