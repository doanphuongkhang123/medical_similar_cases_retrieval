#!/usr/bin/env python3
"""Generate one frozen Context Clues embedding for every visit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from context_clues_pipeline.embedding import (
    infer_embeddings,
    load_prepared_timelines,
    summarize_tokenization,
    tokenization_audit_frame,
    tokenize_visit_timelines,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--model",
        default="StanfordShahLab/gpt-base-4096-clmbr",
    )
    parser.add_argument("--revision")
    parser.add_argument("--timeline-mode", choices=("history", "visit_only"), default="history")
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-tokens-per-batch", type=int, default=16384)
    parser.add_argument("--device", choices=("auto", "cuda", "mps", "cpu"), default="auto")
    parser.add_argument("--dtype", choices=("auto", "float32", "float16", "bfloat16"), default="auto")
    parser.add_argument("--min-mapping-coverage", type=float, default=0.50)
    parser.add_argument("--min-tokenization-coverage", type=float, default=0.90)
    parser.add_argument("--allow-low-coverage", action="store_true")
    parser.add_argument("--allow-empty-current-visit", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _select_device(torch: Any, requested: str) -> Any:
    if requested == "auto":
        if torch.cuda.is_available():
            requested = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            requested = "mps"
        else:
            requested = "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    if requested == "mps" and not (
        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    ):
        raise RuntimeError("MPS was requested but is not available")
    return torch.device(requested)


def _select_dtype(torch: Any, requested: str, device: Any) -> Any:
    if requested == "auto":
        return torch.float16 if device.type == "cuda" else torch.float32
    return {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }[requested]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_coverage(
    prepared_manifest: dict[str, Any],
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    failures: list[str] = []
    mapping_coverage = float(prepared_manifest.get("event_mapping_coverage", 0.0))
    if mapping_coverage < args.min_mapping_coverage:
        failures.append(
            f"mapping coverage {mapping_coverage:.3f} < {args.min_mapping_coverage:.3f}"
        )
    token_coverage = float(summary["event_tokenization_coverage"])
    if token_coverage < args.min_tokenization_coverage:
        failures.append(
            f"tokenization coverage {token_coverage:.3f} < {args.min_tokenization_coverage:.3f}"
        )
    empty_visits = int(summary["visits_without_current_clinical_token"])
    if empty_visits and not args.allow_empty_current_visit:
        failures.append(f"{empty_visits} visits have no tokenized current-visit clinical event")
    return failures


def main() -> None:
    args = parse_args()
    embedding_path = args.output_root / "visit_embeddings.parquet"
    if embedding_path.exists() and not args.overwrite and not args.audit_only:
        raise FileExistsError(f"Refusing to overwrite {embedding_path}")
    args.output_root.mkdir(parents=True, exist_ok=True)

    # Lazy imports keep preprocessing/tests independent from the large model stack.
    import torch
    from hf_ehr.config import Event
    from hf_ehr.data.tokenization import CLMBRTokenizer
    from transformers import AutoModelForCausalLM

    timelines, prepared_manifest = load_prepared_timelines(
        args.prepared_root, args.timeline_mode
    )
    expected_visits = int(prepared_manifest.get("counts", {}).get("visits", len(timelines)))
    if len(timelines) != expected_visits:
        raise ValueError(f"Prepared manifest expects {expected_visits} visits, found {len(timelines)}")

    tokenizer = CLMBRTokenizer.from_pretrained(args.model)
    items = tokenize_visit_timelines(
        timelines=timelines,
        tokenizer=tokenizer,
        event_class=Event,
        max_length=args.max_length,
        numeric_fallback_to_code=True,
    )
    audit = tokenization_audit_frame(items)
    summary = summarize_tokenization(audit)
    summary["prepared_event_mapping_coverage"] = float(
        prepared_manifest.get("event_mapping_coverage", 0.0)
    )
    summary["model"] = args.model
    summary["timeline_mode"] = args.timeline_mode
    summary["max_length"] = args.max_length
    audit.to_parquet(args.output_root / "tokenization_audit.parquet", index=False)
    _write_json(args.output_root / "tokenization_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    failures = _validate_coverage(prepared_manifest, summary, args)
    if failures and not args.allow_low_coverage:
        joined = "; ".join(failures)
        raise RuntimeError(
            f"Coverage gate failed: {joined}. Review tokenization_audit.parquet and the "
            "concept map; use --allow-low-coverage only for an explicit diagnostic run."
        )
    if args.audit_only:
        return

    device = _select_device(torch, args.device)
    dtype = _select_dtype(torch, args.dtype, device)
    model_kwargs: dict[str, Any] = {"torch_dtype": dtype}
    if args.revision:
        model_kwargs["revision"] = args.revision
    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)
    model.to(device)

    matrix = infer_embeddings(
        items=items,
        model=model,
        pad_token_id=int(tokenizer.pad_token_id),
        device=device,
        batch_size=args.batch_size,
        max_tokens_per_batch=args.max_tokens_per_batch,
        l2_normalize=not args.no_normalize,
    )
    if matrix.shape[0] != len(items):
        raise RuntimeError("Embedding count does not match visit count")

    ordered_items = sorted(items, key=lambda value: value.ordinal)
    output = audit.copy()
    output["embedding"] = matrix.tolist()
    output.to_parquet(embedding_path, index=False)
    np.save(args.output_root / "visit_embeddings.npy", matrix, allow_pickle=False)
    pd.DataFrame(
        {
            "row_index": np.arange(len(ordered_items), dtype=np.int64),
            "patient_id": [item.patient_id for item in ordered_items],
            "visit_id": [item.visit_id for item in ordered_items],
        }
    ).to_parquet(args.output_root / "visit_embedding_index.parquet", index=False)

    norms = np.linalg.norm(matrix, axis=1)
    manifest = {
        "schema_version": 1,
        "model": args.model,
        "model_revision": getattr(model.config, "_commit_hash", None),
        "timeline_mode": args.timeline_mode,
        "embedding_strategy": "last hidden state of last non-padding token",
        "l2_normalized": not args.no_normalize,
        "embedding_dimension": int(matrix.shape[1]),
        "visits": int(matrix.shape[0]),
        "max_length": args.max_length,
        "dtype": str(dtype).removeprefix("torch."),
        "device": str(device),
        "norm_min": float(norms.min()),
        "norm_max": float(norms.max()),
        "tokenization_summary": summary,
        "prepared_manifest": prepared_manifest,
        "contains_clinical_text": False,
    }
    _write_json(args.output_root / "manifest.json", manifest)
    print(f"Wrote {matrix.shape[0]:,} visit embeddings ({matrix.shape[1]}D) to {embedding_path}")


if __name__ == "__main__":
    main()
