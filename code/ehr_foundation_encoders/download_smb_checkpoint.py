#!/usr/bin/env python3
"""Download and validate the pinned SMB checkpoint without loading it."""
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
from ehr_foundation_encoders.smb import (
    SMB_MODEL_ID,
    SMB_MODEL_REVISION,
    SMB_MODEL_SOURCE_SHA256,
    SMB_MODEL_WEIGHTS_SHA256,
)


ALLOWED_FILES = (
    "README.md",
    "config.json",
    "model.safetensors",
    "modeling_smb_unstructured.py",
    "added_tokens.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json",
)


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
            f"Refusing to overwrite non-empty checkpoint directory: {args.output_root}"
        )
    staging_root = args.output_root.with_name(f"{args.output_root.name}.staging")
    if staging_root.exists() and any(staging_root.iterdir()):
        raise FileExistsError(
            f"Refusing to reuse non-empty checkpoint staging: {staging_root}"
        )
    info = HfApi().model_info(args.model, revision=args.revision)
    resolved_revision = str(info.sha)
    if resolved_revision != args.revision:
        raise RuntimeError(
            f"Resolved revision {resolved_revision} does not match pin {args.revision}"
        )
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
    required = set(ALLOWED_FILES)
    files = [
        path
        for path in staging_root.rglob("*")
        if path.is_file() and ".cache" not in path.parts
    ]
    relative_files = {str(path.relative_to(staging_root)) for path in files}
    missing = required - relative_files
    unexpected = relative_files - required
    if missing or unexpected:
        raise RuntimeError(
            "Checkpoint file set mismatch: "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    source_path = staging_root / "modeling_smb_unstructured.py"
    weights_path = staging_root / "model.safetensors"
    source_sha256 = sha256_file(source_path)
    weights_sha256 = sha256_file(weights_path)
    if source_sha256 != SMB_MODEL_SOURCE_SHA256:
        raise RuntimeError(
            f"Custom model source SHA-256 mismatch: {source_sha256}"
        )
    if weights_sha256 != SMB_MODEL_WEIGHTS_SHA256:
        raise RuntimeError(f"Model weights SHA-256 mismatch: {weights_sha256}")
    manifest = {
        "schema_version": 1,
        "stage": "smb_checkpoint_download",
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
        "custom_source_reviewed": True,
        "model_weights_downloaded": True,
        "model_loaded": False,
        "gpu_used": False,
    }
    write_json(staging_root / "checkpoint_manifest.json", manifest)
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
