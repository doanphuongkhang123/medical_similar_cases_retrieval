#!/usr/bin/env python3
"""Run a small, privacy-preserving SMB embedding smoke test on real windows."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.common import sha256_file, write_json
from ehr_foundation_encoders.smb import (
    MEDS_COLUMNS,
    SMB_FIX_MISTRAL_REGEX,
    SMB_MAX_SEQUENCE_LENGTH,
    SMB_MODEL_ID,
    SMB_MODEL_REVISION,
    SMB_MODEL_SOURCE_SHA256,
    SMB_MODEL_WEIGHTS_SHA256,
    build_target_meds,
    group_events_by_patient,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common-root", type=Path, required=True)
    parser.add_argument("--window-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def select_smoke_rows(plan: pd.DataFrame) -> list[tuple[str, Any]]:
    """Select deterministic short, median-like, and longest windows."""
    ordered = plan.sort_values(["selected_token_count", "target_order"])
    median = float(ordered["selected_token_count"].median())
    candidates = [
        ("shortest", ordered.iloc[0]),
        (
            "median",
            ordered.assign(
                _distance=(ordered["selected_token_count"] - median).abs()
            )
            .sort_values(["_distance", "target_order"])
            .iloc[0],
        ),
        ("longest", ordered.iloc[-1]),
    ]
    selected: list[tuple[str, Any]] = []
    seen: set[int] = set()
    for slot, row in candidates:
        target_order = int(row["target_order"])
        if target_order not in seen:
            selected.append((slot, row))
            seen.add(target_order)
    if len(selected) != 3:
        raise ValueError("Smoke selection must contain three distinct targets")
    return selected


def serialize_selected_window(
    full: pd.DataFrame,
    target: Any,
    selection: Any,
    formatter: Any,
) -> str:
    first_order = int(selection["first_retained_event_order_within_patient"])
    retained = full[
        full["source_table"].eq("demographics")
        | (full["event_order_within_patient"].astype(int) >= first_order)
    ]
    if len(retained) != int(selection["selected_event_count"]):
        raise ValueError(
            f"Reconstructed event count mismatch for target_order={target.target_order}"
        )
    text = formatter(
        retained[list(MEDS_COLUMNS)],
        subject_id=str(target.patient_id),
        code_column="code",
        category_column="table",
        end_time=pd.Timestamp(target.cutoff_time),
        include_demographics=True,
    )
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Empty serialization for target_order={target.target_order}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != str(selection["selected_serialized_sha256"]):
        raise ValueError(
            f"Reconstructed serialization mismatch for target_order={target.target_order}"
        )
    return text


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def package_version(name: str) -> str:
    return importlib.metadata.version(name)


def main() -> None:
    args = parse_args()
    if args.output_root.exists():
        raise FileExistsError(f"Refusing existing smoke output: {args.output_root}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the SMB smoke inference")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("Selected CUDA device does not support bfloat16")

    try:
        from smb_utils import process_ehr_info
    except ImportError as error:
        raise SystemExit(
            "smb_utils is unavailable; run install_smb_utils_server.sh first"
        ) from error

    common_manifest = require_file(args.common_root / "manifest.json")
    events_path = require_file(args.common_root / "events.parquet")
    targets_path = require_file(args.common_root / "targets.parquet")
    window_manifest = require_file(args.window_root / "manifest.json")
    window_plan_path = require_file(args.window_root / "window_selection.parquet")
    checkpoint_manifest = require_file(
        args.checkpoint_root / "checkpoint_manifest.json"
    )
    source_path = require_file(args.checkpoint_root / "modeling_smb_unstructured.py")
    weights_path = require_file(args.checkpoint_root / "model.safetensors")
    if sha256_file(source_path) != SMB_MODEL_SOURCE_SHA256:
        raise ValueError("Pinned custom model source SHA-256 mismatch")
    if sha256_file(weights_path) != SMB_MODEL_WEIGHTS_SHA256:
        raise ValueError("Pinned SMB model weights SHA-256 mismatch")

    checkpoint_meta = json.loads(checkpoint_manifest.read_text(encoding="utf-8"))
    if checkpoint_meta.get("resolved_revision") != SMB_MODEL_REVISION:
        raise ValueError("Checkpoint manifest does not match the pinned revision")
    window_meta = json.loads(window_manifest.read_text(encoding="utf-8"))
    if int(window_meta.get("max_length", -1)) != SMB_MAX_SEQUENCE_LENGTH:
        raise ValueError("Window manifest does not use the 3,300-token contract")

    events = pd.read_parquet(events_path)
    targets = pd.read_parquet(targets_path).sort_values("target_order")
    plan = pd.read_parquet(window_plan_path)
    patient_events = group_events_by_patient(events)
    target_by_order = targets.set_index("target_order", drop=False)
    empty = events.iloc[0:0]

    tokenizer = AutoTokenizer.from_pretrained(
        args.checkpoint_root,
        local_files_only=True,
        trust_remote_code=False,
        fix_mistral_regex=SMB_FIX_MISTRAL_REGEX,
    )
    prepared: list[tuple[str, Any, dict[str, torch.Tensor]]] = []
    for slot, selection in select_smoke_rows(plan):
        target_order = int(selection["target_order"])
        target = target_by_order.loc[target_order]
        full = build_target_meds(
            patient_events.get(str(target.patient_id), empty), target
        )
        text = serialize_selected_window(
            full, target, selection, process_ehr_info
        )
        encoded = tokenizer(
            text,
            add_special_tokens=True,
            truncation=False,
            padding=False,
            return_tensors="pt",
        )
        token_count = int(encoded["input_ids"].shape[1])
        if token_count != int(selection["selected_token_count"]):
            raise ValueError(
                f"Token count mismatch for target_order={target_order}: {token_count}"
            )
        if token_count > SMB_MAX_SEQUENCE_LENGTH:
            raise ValueError(f"Smoke input exceeds {SMB_MAX_SEQUENCE_LENGTH} tokens")
        prepared.append((slot, selection, encoded))

    device = torch.device("cuda:0")
    torch.cuda.reset_peak_memory_stats(device)
    model = AutoModelForCausalLM.from_pretrained(
        args.checkpoint_root,
        trust_remote_code=True,
        local_files_only=True,
        dtype=torch.bfloat16,
        attn_implementation="eager",
    )
    model.eval().to(device)
    decoder = model.get_decoder()
    sample_results: list[dict[str, Any]] = []
    with torch.inference_mode():
        for slot, selection, encoded in prepared:
            inputs = {name: tensor.to(device) for name, tensor in encoded.items()}
            output = decoder(
                input_ids=inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
                use_cache=False,
                return_dict=True,
            )
            hidden = output.last_hidden_state
            last_index = int(inputs["attention_mask"].sum().item()) - 1
            embedding = hidden[0, last_index].float()
            finite = bool(torch.isfinite(embedding).all().item())
            norm = float(torch.linalg.vector_norm(embedding).item())
            if not finite or not np.isfinite(norm) or norm <= 0:
                raise ValueError(
                    f"Invalid embedding for target_order={int(selection['target_order'])}"
                )
            if int(embedding.numel()) != 2048:
                raise ValueError(f"Unexpected embedding dimension: {embedding.numel()}")
            sample_results.append(
                {
                    "sample_slot": slot,
                    "target_order": int(selection["target_order"]),
                    "selected_token_count": int(selection["selected_token_count"]),
                    "selection_applied": bool(selection["selection_applied"]),
                    "embedding_dimension": int(embedding.numel()),
                    "embedding_norm": norm,
                    "embedding_finite": finite,
                }
            )
            del inputs, output, hidden, embedding

    properties = torch.cuda.get_device_properties(device)
    manifest = {
        "schema_version": 1,
        "stage": "smb_embedding_smoke_inference",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model": SMB_MODEL_ID,
        "model_revision": SMB_MODEL_REVISION,
        "max_length": SMB_MAX_SEQUENCE_LENGTH,
        "pooling": "last non-padding token from final decoder hidden state",
        "decoder_only_forward": True,
        "samples": sample_results,
        "checks": {
            "window_serialization_hashes_match": True,
            "token_counts_match": True,
            "all_embeddings_finite": True,
            "embedding_dimension": 2048,
        },
        "privacy": {
            "serialized_text_persisted": False,
            "token_ids_persisted": False,
            "embeddings_persisted": False,
            "patient_ids_persisted": False,
            "visit_ids_persisted": False,
        },
        "inputs": {
            "common_manifest_sha256": sha256_file(common_manifest),
            "events_sha256": sha256_file(events_path),
            "targets_sha256": sha256_file(targets_path),
            "window_manifest_sha256": sha256_file(window_manifest),
            "window_plan_sha256": sha256_file(window_plan_path),
            "checkpoint_manifest_sha256": sha256_file(checkpoint_manifest),
            "model_source_sha256": SMB_MODEL_SOURCE_SHA256,
            "model_weights_sha256": SMB_MODEL_WEIGHTS_SHA256,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "transformers": package_version("transformers"),
            "safetensors": package_version("safetensors"),
            "cuda_device": properties.name,
            "cuda_total_memory_bytes": int(properties.total_memory),
            "cuda_peak_memory_bytes": int(torch.cuda.max_memory_allocated(device)),
            "dtype": "bfloat16",
            "attention_implementation": "eager",
            "gpu_used": True,
        },
    }
    args.output_root.mkdir(parents=True, exist_ok=False)
    write_json(args.output_root / "smoke_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
