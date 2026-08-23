#!/usr/bin/env python3
"""Prepare shared structured EHR and SMB MEDS artifacts from the raw workbook."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.raw_workbook import prepare_smb_raw_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--ehr-preprocessing-root",
        type=Path,
        default=ROOT.parent / "ehr_graph_embedding" / "preprocessing",
        help="Raw XLSX parser code root; no derived data is consumed.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = prepare_smb_raw_dataset(
        workbook_path=args.workbook,
        output_root=args.output_root,
        preprocessing_root=args.ehr_preprocessing_root,
        overwrite=args.overwrite,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
