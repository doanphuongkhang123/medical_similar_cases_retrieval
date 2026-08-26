#!/usr/bin/env python3
"""Audit official SMB serialization without saving clinical serialized text."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.smb import audit_smb_serialization


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-targets", type=int)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        from smb_utils import process_ehr_info
    except ImportError as error:
        raise SystemExit(
            "smb_utils is unavailable; run install_smb_utils_server.sh or add its pinned src directory to PYTHONPATH"
        ) from error
    events = pd.read_parquet(args.common_root / "events.parquet")
    targets = pd.read_parquet(args.common_root / "targets.parquet")
    manifest = audit_smb_serialization(
        events=events,
        targets=targets,
        formatter=process_ehr_info,
        output_root=args.output_root,
        overwrite=args.overwrite,
        max_targets=args.max_targets,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
