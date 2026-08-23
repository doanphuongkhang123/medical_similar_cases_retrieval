#!/usr/bin/env python3
"""Select complete recent SMB event windows that fit 3,300 tokens."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.smb import (
    SMB_FIX_MISTRAL_REGEX,
    SMB_MAX_SEQUENCE_LENGTH,
)
from ehr_foundation_encoders.windowing import build_smb_window_selection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common-root", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--token-audit-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=SMB_MAX_SEQUENCE_LENGTH)
    parser.add_argument("--max-targets", type=int)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        from smb_utils import process_ehr_info
    except ImportError as error:
        raise SystemExit(
            "smb_utils is unavailable; run install_smb_utils_server.sh first"
        ) from error
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_root,
        local_files_only=True,
        trust_remote_code=False,
        fix_mistral_regex=SMB_FIX_MISTRAL_REGEX,
    )
    events = pd.read_parquet(args.common_root / "events.parquet")
    targets = pd.read_parquet(args.common_root / "targets.parquet")
    token_audit = pd.read_parquet(
        args.token_audit_root / "token_length_audit.parquet"
    )
    manifest = build_smb_window_selection(
        events=events,
        targets=targets,
        token_audit=token_audit,
        tokenizer=tokenizer,
        formatter=process_ehr_info,
        output_root=args.output_root,
        tokenizer_root=args.tokenizer_root,
        common_root=args.common_root,
        token_audit_root=args.token_audit_root,
        max_length=args.max_length,
        overwrite=args.overwrite,
        max_targets=args.max_targets,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
