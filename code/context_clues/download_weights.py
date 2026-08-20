#!/usr/bin/env python3
"""Download Context Clues artifacts without importing torch or touching a GPU."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import GatedRepoError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="StanfordShahLab/gpt-base-4096-clmbr",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--revision")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    info = api.model_info(args.model, revision=args.revision)
    revision = args.revision or info.sha
    try:
        snapshot_download(
            repo_id=args.model,
            revision=revision,
            local_dir=args.output_root,
            # Prefer safetensors and avoid downloading the duplicate PyTorch
            # .bin checkpoint. This repository has a complete safetensors file.
            allow_patterns=[
                "README.md",
                "*.json",
                "*.safetensors",
                "*.safetensors.index.json",
            ],
        )
    except GatedRepoError as error:
        raise RuntimeError(
            f"Hugging Face account has no approved access to {args.model}. "
            "Request manual access on the model page, then rerun this CPU-only downloader."
        ) from error

    files = []
    for path in sorted(args.output_root.rglob("*")):
        if not path.is_file() or ".cache" in path.parts or path.name == "weights_manifest.json":
            continue
        files.append(
            {
                "path": str(path.relative_to(args.output_root)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    required = {"config.json", "tokenizer_config.json"}
    present = {item["path"] for item in files}
    if not required.issubset(present) or not any(
        item["path"].endswith(".safetensors") for item in files
    ):
        raise RuntimeError(f"Incomplete model snapshot; downloaded files: {sorted(present)}")
    manifest = {
        "model": args.model,
        "revision": info.sha,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "gpu_used": False,
        "torch_imported": False,
        "files": files,
        "total_bytes": sum(item["bytes"] for item in files),
    }
    (args.output_root / "weights_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
