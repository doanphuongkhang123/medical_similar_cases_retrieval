#!/usr/bin/env python3
"""Generate resumable, one-per-visit SMB embeddings in atomic shards."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.common import sha256_file, write_json
from ehr_foundation_encoders.smb import (
    SMB_FIX_MISTRAL_REGEX,
    SMB_MAX_SEQUENCE_LENGTH,
    SMB_MODEL_ID,
    SMB_MODEL_REVISION,
    SMB_MODEL_SOURCE_SHA256,
    SMB_MODEL_WEIGHTS_SHA256,
    build_target_meds,
    group_events_by_patient,
)
from smoke_smb_inference import package_version, require_file, serialize_selected_window


EMBEDDING_DIMENSION = 2048


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common-root", type=Path, required=True)
    parser.add_argument("--window-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-size", type=int, default=25)
    return parser.parse_args()


def shard_groups(plan: pd.DataFrame, shard_size: int) -> Iterator[tuple[int, pd.DataFrame]]:
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    for start in range(0, len(plan), shard_size):
        yield start, plan.iloc[start : start + shard_size]


def shard_path(root: Path, start: int, count: int) -> Path:
    return root / f"shard_{start:05d}_{start + count - 1:05d}.npz"


def write_shard_atomic(
    path: Path,
    target_orders: np.ndarray,
    embeddings: np.ndarray,
    raw_norms: np.ndarray,
    token_counts: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            target_order=target_orders.astype(np.int64, copy=False),
            embedding=embeddings.astype(np.float32, copy=False),
            raw_norm=raw_norms.astype(np.float32, copy=False),
            selected_token_count=token_counts.astype(np.int32, copy=False),
        )
    os.replace(temporary, path)


def load_shard(path: Path, expected_orders: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as stored:
        orders = stored["target_order"].astype(np.int64, copy=False)
        embeddings = stored["embedding"].astype(np.float32, copy=False)
        raw_norms = stored["raw_norm"].astype(np.float32, copy=False)
        token_counts = stored["selected_token_count"].astype(np.int32, copy=False)
    if not np.array_equal(orders, expected_orders.astype(np.int64, copy=False)):
        raise ValueError(f"Shard target order mismatch: {path}")
    expected_shape = (len(expected_orders), EMBEDDING_DIMENSION)
    if embeddings.shape != expected_shape:
        raise ValueError(f"Shard embedding shape mismatch: {path}: {embeddings.shape}")
    if raw_norms.shape != (len(expected_orders),) or token_counts.shape != (
        len(expected_orders),
    ):
        raise ValueError(f"Shard audit shape mismatch: {path}")
    if not np.isfinite(embeddings).all() or not np.isfinite(raw_norms).all():
        raise ValueError(f"Shard contains non-finite values: {path}")
    normalized_norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(normalized_norms, 1.0, atol=1e-5):
        raise ValueError(f"Shard embeddings are not L2-normalized: {path}")
    if (raw_norms <= 0).any() or (token_counts <= 0).any():
        raise ValueError(f"Shard contains invalid audit values: {path}")
    return embeddings, raw_norms


def atomic_npy(path: Path, matrix: np.ndarray) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("wb") as stream:
        np.save(stream, matrix, allow_pickle=False)
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    frame.to_parquet(temporary, index=False, engine="pyarrow")
    os.replace(temporary, path)


def main() -> None:
    args = parse_args()
    if args.shard_size <= 0:
        raise ValueError("shard-size must be positive")
    final_manifest_path = args.output_root / "manifest.json"
    final_matrix_path = args.output_root / "visit_embeddings.npy"
    final_index_path = args.output_root / "visit_embedding_index.parquet"
    if final_manifest_path.is_file():
        if not final_matrix_path.is_file() or not final_index_path.is_file():
            raise ValueError("Final manifest exists but final artifacts are incomplete")
        print(f"Full SMB artifact already complete: {args.output_root}")
        return

    try:
        from smb_utils import process_ehr_info
    except ImportError as error:
        raise SystemExit("smb_utils is unavailable") from error

    common_manifest = require_file(args.common_root / "manifest.json")
    events_path = require_file(args.common_root / "events.parquet")
    targets_path = require_file(args.common_root / "targets.parquet")
    window_manifest = require_file(args.window_root / "manifest.json")
    window_plan_path = require_file(args.window_root / "window_selection.parquet")
    checkpoint_manifest = require_file(args.checkpoint_root / "checkpoint_manifest.json")
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
    targets = pd.read_parquet(targets_path).sort_values("target_order").reset_index(drop=True)
    plan = pd.read_parquet(window_plan_path).sort_values("target_order").reset_index(drop=True)
    if len(plan) != len(targets) or len(plan) != 3500:
        raise ValueError(f"Expected 3,500 targets, got plan={len(plan)}, targets={len(targets)}")
    if not np.array_equal(plan["target_order"].to_numpy(), targets["target_order"].to_numpy()):
        raise ValueError("Window plan and targets have different target order")
    if targets["visit_id"].astype(str).duplicated().any():
        raise ValueError("visit_id must be unique")

    args.output_root.mkdir(parents=True, exist_ok=True)
    run_config_path = args.output_root / "run_config.json"
    run_config = {
        "schema_version": 1,
        "model": SMB_MODEL_ID,
        "model_revision": SMB_MODEL_REVISION,
        "max_length": SMB_MAX_SEQUENCE_LENGTH,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "pooling": "last non-padding token from final decoder hidden state",
        "l2_normalized": True,
        "batch_size": 1,
        "shard_size": args.shard_size,
        "common_manifest_sha256": sha256_file(common_manifest),
        "window_manifest_sha256": sha256_file(window_manifest),
        "window_plan_sha256": sha256_file(window_plan_path),
        "checkpoint_manifest_sha256": sha256_file(checkpoint_manifest),
    }
    if run_config_path.is_file():
        existing_config = json.loads(run_config_path.read_text(encoding="utf-8"))
        if existing_config != run_config:
            raise ValueError("Existing resumable run configuration does not match")
    else:
        temporary_config = run_config_path.with_suffix(".json.tmp")
        write_json(temporary_config, run_config)
        os.replace(temporary_config, run_config_path)
    shards_root = args.output_root / "shards"
    shards_root.mkdir(parents=True, exist_ok=True)
    groups = list(shard_groups(plan, args.shard_size))
    missing: list[tuple[int, pd.DataFrame, Path]] = []
    for start, group in groups:
        path = shard_path(shards_root, start, len(group))
        expected = group["target_order"].to_numpy(dtype=np.int64)
        if path.is_file():
            load_shard(path, expected)
            print(f"resume: verified {path.name}", flush=True)
        else:
            missing.append((start, group, path))

    peak_memory = 0
    session_started = time.monotonic()
    if missing:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for SMB embedding inference")
        if not torch.cuda.is_bf16_supported():
            raise RuntimeError("This runner requires a CUDA device supporting bfloat16")
        tokenizer = AutoTokenizer.from_pretrained(
            args.checkpoint_root,
            local_files_only=True,
            trust_remote_code=False,
            fix_mistral_regex=SMB_FIX_MISTRAL_REGEX,
        )
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
        patient_events = group_events_by_patient(events)
        target_by_order = targets.set_index("target_order", drop=False)
        empty = events.iloc[0:0]

        with torch.inference_mode():
            for shard_number, (start, group, path) in enumerate(missing, start=1):
                vectors: list[np.ndarray] = []
                raw_norms: list[float] = []
                token_counts: list[int] = []
                for selection in group.to_dict(orient="records"):
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
                        raise ValueError(f"Token count mismatch at target_order={target_order}")
                    inputs = {name: tensor.to(device) for name, tensor in encoded.items()}
                    output = decoder(
                        input_ids=inputs["input_ids"],
                        attention_mask=inputs.get("attention_mask"),
                        use_cache=False,
                        return_dict=True,
                    )
                    last_index = int(inputs["attention_mask"].sum().item()) - 1
                    raw = output.last_hidden_state[0, last_index].float()
                    raw_norm = torch.linalg.vector_norm(raw)
                    vector = torch.nn.functional.normalize(raw, p=2, dim=0)
                    if not torch.isfinite(vector).all() or not torch.isfinite(raw_norm):
                        raise ValueError(f"Non-finite embedding at target_order={target_order}")
                    vectors.append(vector.cpu().numpy().astype(np.float32, copy=False))
                    raw_norms.append(float(raw_norm.item()))
                    token_counts.append(token_count)
                    del inputs, output, raw, raw_norm, vector

                matrix = np.stack(vectors).astype(np.float32, copy=False)
                write_shard_atomic(
                    path,
                    group["target_order"].to_numpy(dtype=np.int64),
                    matrix,
                    np.asarray(raw_norms, dtype=np.float32),
                    np.asarray(token_counts, dtype=np.int32),
                )
                load_shard(path, group["target_order"].to_numpy(dtype=np.int64))
                peak_memory = max(peak_memory, int(torch.cuda.max_memory_allocated(device)))
                print(
                    f"wrote {path.name} ({shard_number}/{len(missing)} missing shards)",
                    flush=True,
                )

        del decoder, model
        torch.cuda.empty_cache()

    matrices: list[np.ndarray] = []
    raw_norm_parts: list[np.ndarray] = []
    shard_entries: list[dict[str, Any]] = []
    for start, group in groups:
        path = shard_path(shards_root, start, len(group))
        matrix, raw_norms = load_shard(
            path, group["target_order"].to_numpy(dtype=np.int64)
        )
        matrices.append(matrix)
        raw_norm_parts.append(raw_norms)
        shard_entries.append(
            {"path": path.name, "rows": int(len(group)), "sha256": sha256_file(path)}
        )
    full_matrix = np.concatenate(matrices, axis=0).astype(np.float32, copy=False)
    raw_norm_array = np.concatenate(raw_norm_parts).astype(np.float32, copy=False)
    if full_matrix.shape != (3500, EMBEDDING_DIMENSION):
        raise ValueError(f"Unexpected final embedding shape: {full_matrix.shape}")
    final_norms = np.linalg.norm(full_matrix, axis=1)
    if not np.isfinite(full_matrix).all() or not np.allclose(final_norms, 1.0, atol=1e-5):
        raise ValueError("Final embedding matrix failed finite/L2 checks")

    index = targets[["patient_id", "visit_id", "target_order"]].copy()
    index.insert(0, "row_index", np.arange(len(index), dtype=np.int64))
    index["selected_token_count"] = plan["selected_token_count"].astype(np.int32)
    index["selection_applied"] = plan["selection_applied"].astype(bool)
    index["raw_embedding_norm"] = raw_norm_array
    atomic_npy(final_matrix_path, full_matrix)
    atomic_parquet(final_index_path, index)

    manifest = {
        "schema_version": 1,
        "stage": "smb_full_visit_embedding_inference",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model": SMB_MODEL_ID,
        "model_revision": SMB_MODEL_REVISION,
        "max_length": SMB_MAX_SEQUENCE_LENGTH,
        "visits": 3500,
        "patients": int(index["patient_id"].astype(str).nunique()),
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_dtype": "float32",
        "pooling": "last non-padding token from final decoder hidden state",
        "l2_normalized": True,
        "batch_size": 1,
        "shard_size": args.shard_size,
        "resume_policy": "verify and skip complete atomic NPZ shards",
        "outputs": {
            "matrix": final_matrix_path.name,
            "index": final_index_path.name,
            "matrix_sha256": sha256_file(final_matrix_path),
            "index_sha256": sha256_file(final_index_path),
        },
        "checks": {
            "one_row_per_visit": True,
            "visit_ids_unique": True,
            "all_embeddings_finite": True,
            "all_embeddings_l2_normalized": True,
            "norm_min": float(final_norms.min()),
            "norm_max": float(final_norms.max()),
            "raw_norm_min": float(raw_norm_array.min()),
            "raw_norm_max": float(raw_norm_array.max()),
        },
        "privacy": {
            "serialized_text_persisted": False,
            "token_ids_persisted": False,
            "clinical_events_duplicated": False,
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
        "shards": shard_entries,
        "runtime": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "transformers": package_version("transformers"),
            "safetensors": package_version("safetensors"),
            "dtype": "bfloat16",
            "attention_implementation": "eager",
            "current_session_cuda_peak_memory_bytes": peak_memory,
            "current_session_elapsed_seconds": time.monotonic() - session_started,
        },
    }
    temporary_manifest = final_manifest_path.with_suffix(".json.tmp")
    write_json(temporary_manifest, manifest)
    os.replace(temporary_manifest, final_manifest_path)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
