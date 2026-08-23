#!/usr/bin/env python3
"""Download only SMB tokenizer/config files and record exact provenance."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.common import sha256_file, write_json
from ehr_foundation_encoders.smb import SMB_MODEL_ID, SMB_MODEL_REVISION


ALLOWED_FILES = (
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "tokenizer.json",
    "vocab.json",
    "merges.txt",
)
FORBIDDEN_SUFFIXES = {".safetensors", ".bin", ".pt", ".pth", ".ckpt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--model", default=SMB_MODEL_ID)
    parser.add_argument("--revision", default=SMB_MODEL_REVISION)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_root.exists() and any(args.output_root.iterdir()) and not args.overwrite:
        raise FileExistsError(
            f"Refusing to overwrite non-empty tokenizer directory: {args.output_root}"
        )
    staging_root = args.output_root.with_name(f"{args.output_root.name}.staging")
    info = HfApi().model_info(args.model, revision=args.revision)
    resolved_revision = str(info.sha)
    args.output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    args.cache_root.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=args.model,
        revision=resolved_revision,
        allow_patterns=list(ALLOWED_FILES),
        local_dir=staging_root,
        cache_dir=args.cache_root,
    )
    files = [
        path
        for path in staging_root.rglob("*")
        if path.is_file() and ".cache" not in path.parts
    ]
    forbidden = [path for path in files if path.suffix.casefold() in FORBIDDEN_SUFFIXES]
    if forbidden:
        raise RuntimeError(f"Tokenizer-only download contains weight files: {forbidden}")
    required = {"config.json", "tokenizer_config.json", "vocab.json", "merges.txt"}
    missing = required - {path.name for path in files}
    if missing:
        raise RuntimeError(f"Tokenizer-only download is missing files: {sorted(missing)}")
    model_config = json.loads((staging_root / "config.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "stage": "smb_tokenizer_config_download",
        "model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "gated": info.gated,
        "files": {
            str(path.relative_to(staging_root)): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(files)
        },
        "config_summary": {
            "model_type": model_config.get("model_type"),
            "hidden_size": model_config.get("hidden_size"),
            "max_position_embeddings": model_config.get("max_position_embeddings"),
            "vocab_size": model_config.get("vocab_size"),
        },
        "model_weights_downloaded": False,
        "gpu_used": False,
    }
    write_json(staging_root / "tokenizer_manifest.json", manifest)
    if args.output_root.exists():
        if not args.overwrite:
            raise FileExistsError(args.output_root)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_root = args.output_root.with_name(
            f"{args.output_root.name}.backup-{timestamp}"
        )
        args.output_root.rename(backup_root)
    staging_root.rename(args.output_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
