#!/usr/bin/env python3
"""Create visit-level Qwen3 clinical-note embeddings without persisting raw text."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F


DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_CONTEXT_LENGTH = 32768
EXPECTED_NATIVE_DIMENSION = 4096
OUTPUT_256_DIMENSION = 256
FORBIDDEN_OUTPUT_COLUMNS = {
    "clinical_note", "note_text", "text", "raw_text", "token_ids", "raw_model_hidden_states",
}
NOTE_COLUMNS = [
    "note_id", "patient_id", "visit_id", "note_type", "section_name", "note_text",
    "event_time", "source_sheet", "source_key", "source_row_count",
]
VISIT_COLUMNS = [
    "patient_id", "visit_id", "primary_key", "admission_time", "discharge_time", "department",
    "birth_year", "age_at_visit", "gender_code", "clinical_note", "diagnosis_count",
    "medicine_count", "procedure_count", "note_section_count", "observation_count",
    "has_diagnosis", "has_medicine", "has_procedure", "has_clinical_note",
]


def _json_default(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: Any) -> str | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-notes", type=Path, required=True)
    parser.add_argument("--input-visits", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default="main")
    parser.add_argument("--tokenizer-revision", default=None)
    parser.add_argument("--max-length", type=int, default=DEFAULT_CONTEXT_LENGTH)
    parser.add_argument("--max-batch-size", type=int, default=32)
    parser.add_argument("--shard-size", type=int, default=64)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--quantization", choices=("auto", "none", "8bit", "4bit"), default="auto")
    parser.add_argument("--precision", choices=("auto", "bf16", "fp16"), default="auto")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    return parser


def _read_inputs(notes_path: Path, visits_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    notes = pd.read_parquet(notes_path, columns=NOTE_COLUMNS)
    visits = pd.read_parquet(visits_path, columns=VISIT_COLUMNS)
    for frame, required, name in ((notes, NOTE_COLUMNS, "clinical_notes"), (visits, VISIT_COLUMNS, "visits")):
        missing = set(required).difference(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing columns: {sorted(missing)}")
    for frame, columns in (
        (notes, ["note_id", "patient_id", "visit_id", "note_text"]),
        (visits, ["patient_id", "visit_id", "clinical_note"]),
    ):
        for column in columns:
            frame[column] = frame[column].fillna("").astype(str)
            if column != "clinical_note":
                frame[column] = frame[column].str.strip()
    if notes["note_id"].eq("").any() or notes["visit_id"].eq("").any():
        raise ValueError("clinical_notes has empty note_id or visit_id")
    if visits["visit_id"].eq("").any() or visits["patient_id"].eq("").any():
        raise ValueError("visits has empty patient_id or visit_id")
    if notes["note_id"].duplicated().any():
        raise ValueError("note_id is not unique")
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id is not unique")
    if not set(notes["visit_id"]).issubset(set(visits["visit_id"])):
        raise ValueError("clinical_notes contains an orphan visit_id")
    missing_visits = set(visits["visit_id"]) - set(notes["visit_id"])
    if missing_visits:
        raise ValueError(f"visits without clinical notes: {len(missing_visits)}")
    return notes, visits


def _aggregate_note_text(group: pd.DataFrame) -> str:
    parts = [f"[{section}]\n{text}" for section, text in zip(group["section_name"], group["note_text"])]
    return "\n\n".join(parts)


def _prepare_visits(notes: pd.DataFrame, visits: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id is not unique")
    grouped = {visit_id: group for visit_id, group in notes.groupby("visit_id", sort=False)}
    rows: list[dict[str, Any]] = []
    visit_order: list[str] = []
    mismatches: list[str] = []
    for visit in visits.itertuples(index=False):
        visit_id = visit.visit_id
        group = grouped[visit_id]
        aggregate = _aggregate_note_text(group)
        if aggregate != visit.clinical_note:
            mismatches.append(visit_id)
        event_times = group["event_time"].dropna()
        note_types = [str(value) for value in group["note_type"]]
        sections = [str(value) for value in group["section_name"]]
        source_sheets = list(dict.fromkeys(str(value) for value in group["source_sheet"]))
        metadata = {column: getattr(visit, column) for column in VISIT_COLUMNS if column != "clinical_note"}
        metadata.update({
            "actual_note_row_count": int(len(group)),
            "note_type_counts": _json_dump(dict(sorted(Counter(note_types).items()))),
            "section_names": _json_dump(sections),
            "note_event_time_min": _timestamp(event_times.min()) if not event_times.empty else None,
            "note_event_time_max": _timestamp(event_times.max()) if not event_times.empty else None,
            "source_sheets": _json_dump(source_sheets),
            "source_row_count_total": int(group["source_row_count"].fillna(0).sum()),
            "token_count": None,
            "chunk_count": 1,
            "_text": aggregate,
        })
        rows.append(metadata)
        visit_order.append(visit_id)
    if mismatches:
        raise ValueError(
            "reconstructed clinical_note differs from visits.clinical_note for "
            f"{len(mismatches)} visits; sample visit_id values: {mismatches[:10]}"
        )
    result = pd.DataFrame(rows)
    if len(result) != len(visits) or result["visit_id"].duplicated().any():
        raise ValueError("prepared visit table is not one-row-per-visit")
    return result, visit_order


def _token_lengths(tokenizer: Any, texts: Sequence[str], batch_size: int = 32) -> list[int]:
    lengths: list[int] = []
    for start in range(0, len(texts), batch_size):
        encoded = tokenizer(
            list(texts[start : start + batch_size]),
            add_special_tokens=True,
            padding=False,
            truncation=False,
            return_attention_mask=False,
        )
        lengths.extend(len(ids) for ids in encoded["input_ids"])
    return lengths


def _percentile(values: Sequence[int], percentile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _token_statistics(visit_frame: pd.DataFrame, tokenizer: Any, context_length: int) -> dict[str, Any]:
    lengths = _token_lengths(tokenizer, visit_frame["_text"].tolist())
    if len(lengths) != len(visit_frame):
        raise ValueError("tokenizer returned an unexpected number of lengths")
    visit_frame["token_count"] = np.asarray(lengths, dtype=np.int64)
    over_ids = visit_frame.loc[visit_frame["token_count"] > context_length, "visit_id"].astype(str).tolist()
    return {
        "count": len(lengths),
        "min": int(min(lengths)),
        "median": _percentile(lengths, 50),
        "p90": _percentile(lengths, 90),
        "p99": _percentile(lengths, 99),
        "max": int(max(lengths)),
        "context_length": int(context_length),
        "over_context_count": len(over_ids),
        "over_context_visit_ids": over_ids,
    }


def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Qwen3-Embedding official last-token pooling implementation."""
    left_padding = bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item())
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[
        torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths
    ]


def _normalize(vectors: torch.Tensor) -> torch.Tensor:
    return F.normalize(vectors.float(), p=2, dim=-1)


def _device(value: str) -> torch.device:
    if value == "auto":
        value = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(value)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return device


def _dependency_versions() -> dict[str, str | None]:
    import importlib
    versions: dict[str, str | None] = {}
    for name in ["torch", "transformers", "pandas", "pyarrow", "numpy", "bitsandbytes", "safetensors", "accelerate"]:
        try:
            module = importlib.import_module(name)
            versions[name] = str(getattr(module, "__version__", "unknown"))
        except Exception:
            versions[name] = None
    return versions


def _gpu_info(device: torch.device) -> dict[str, Any]:
    if device.type != "cuda":
        return {"device": str(device)}
    index = device.index if device.index is not None else torch.cuda.current_device()
    props = torch.cuda.get_device_properties(index)
    return {"device": str(device), "name": props.name, "total_memory_bytes": int(props.total_memory), "index": int(index)}


def _memory_snapshot(device: torch.device) -> dict[str, int]:
    if device.type != "cuda":
        return {"allocated_bytes": 0, "reserved_bytes": 0, "max_allocated_bytes": 0, "max_reserved_bytes": 0}
    return {
        "allocated_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_bytes": int(torch.cuda.memory_reserved(device)),
        "max_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "max_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
    }


def _clear_model(model: Any, device: torch.device) -> None:
    del model
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def _load_tokenizer(model_id: str, revision: str, tokenizer_revision: str | None, cache_dir: Path | None) -> Any:
    from transformers import AutoTokenizer
    kwargs: dict[str, Any] = {"revision": tokenizer_revision or revision, "padding_side": "left"}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_id, **kwargs)
    tokenizer.padding_side = "left"
    if tokenizer.padding_side != "left":
        raise ValueError("Qwen3 tokenizer must use left padding")
    return tokenizer


def _quantization_configs(quantization: str, precision: str) -> list[tuple[str, str]]:
    if quantization != "auto":
        return [(precision if precision != "auto" else "bf16", quantization)]
    int8_precision = precision if precision != "auto" else "fp16"
    return [("bf16", "none"), (int8_precision, "8bit"), ("bf16", "4bit")]


def _load_model(model_id: str, revision: str, cache_dir: Path | None, device: torch.device, precision: str, quantization: str) -> Any:
    from transformers import AutoModel, BitsAndBytesConfig
    kwargs: dict[str, Any] = {"revision": revision, "low_cpu_mem_usage": True}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    if precision == "bf16":
        kwargs["dtype"] = torch.bfloat16
    elif precision == "fp16":
        kwargs["dtype"] = torch.float16
    if quantization == "8bit":
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
        kwargs["device_map"] = {"": device.index if device.index is not None else 0}
    elif quantization == "4bit":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        kwargs["device_map"] = {"": device.index if device.index is not None else 0}
    model = AutoModel.from_pretrained(model_id, **kwargs)
    if quantization == "none":
        model.to(device)
    model.eval()
    return model


def _forward(model: Any, tokenizer: Any, texts: Sequence[str], device: torch.device, max_length: int) -> torch.Tensor:
    tokens = tokenizer(list(texts), padding=True, truncation=False, return_tensors="pt")
    if int(tokens["input_ids"].shape[1]) > max_length:
        raise ValueError("a text exceeded max_length; refusing to truncate")
    tokens = {key: value.to(device) for key, value in tokens.items()}
    with torch.inference_mode():
        outputs = model(**tokens)
        pooled = last_token_pool(outputs.last_hidden_state, tokens["attention_mask"])
        vectors = _normalize(pooled)
    if vectors.shape[-1] != EXPECTED_NATIVE_DIMENSION:
        raise ValueError(f"expected {EXPECTED_NATIVE_DIMENSION}-D model output, got {vectors.shape[-1]}")
    if not torch.isfinite(vectors).all():
        raise ValueError("model output contains NaN or Inf")
    return vectors.float()


def _smoke_indices(visit_frame: pd.DataFrame) -> list[int]:
    lengths = visit_frame["token_count"].to_numpy()
    targets = [int(lengths.min()), int(np.median(lengths)), int(_percentile(lengths, 90)), int(lengths.max())]
    indices: list[int] = []
    for target in targets:
        index = int(np.abs(lengths - target).argmin())
        if index not in indices:
            indices.append(index)
    return indices


def _run_smoke(model: Any, tokenizer: Any, visit_frame: pd.DataFrame, device: torch.device, max_length: int, batch_size: int, smoke_indices: Sequence[int]) -> dict[str, Any]:
    texts = [str(visit_frame.iloc[index]["_text"]) for index in smoke_indices]
    if batch_size <= len(texts):
        batches: list[Sequence[str]] = [texts[start : start + batch_size] for start in range(0, len(texts), batch_size)]
    else:
        batches = [[texts[i % len(texts)] for i in range(batch_size)]]
    vectors = torch.cat([_forward(model, tokenizer, batch, device, max_length) for batch in batches], dim=0)
    norms = torch.linalg.vector_norm(vectors, dim=-1)
    if not torch.allclose(norms, torch.ones_like(norms), atol=1e-4, rtol=1e-4):
        raise ValueError("smoke embeddings are not L2-normalized")
    prefix = F.normalize(vectors[:, :OUTPUT_256_DIMENSION], p=2, dim=-1)
    if not torch.isfinite(prefix).all():
        raise ValueError("smoke 256-D embeddings contain NaN or Inf")
    return _memory_snapshot(device)


def _select_model_and_batch(args: argparse.Namespace, tokenizer: Any, visit_frame: pd.DataFrame, device: torch.device) -> tuple[Any, dict[str, Any], int, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    smoke_indices = _smoke_indices(visit_frame)
    selected_model: Any | None = None
    selected_config: dict[str, Any] | None = None
    selected_batch = 0
    for attempted_precision, attempted_quantization in _quantization_configs(args.quantization, args.precision):
        if device.type != "cuda" and attempted_quantization != "none":
            attempts.append({"precision": attempted_precision, "quantization": attempted_quantization, "status": "skipped_cpu"})
            continue
        started = datetime.now(timezone.utc).isoformat()
        model: Any | None = None
        try:
            if device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(device)
            model = _load_model(args.model, args.model_revision, args.cache_dir, device, attempted_precision, attempted_quantization)
            stable_batch = 0
            candidate = 1
            while candidate <= max(1, args.max_batch_size):
                try:
                    snapshot = _run_smoke(model, tokenizer, visit_frame, device, args.max_length, candidate, smoke_indices)
                    stable_batch = candidate
                    attempts.append({
                        "precision": attempted_precision, "quantization": attempted_quantization, "batch_size": candidate,
                        "maximum_length": args.max_length, "status": "ok", "peak_memory": snapshot, "started_utc": started,
                    })
                    candidate *= 2
                except (torch.cuda.OutOfMemoryError, RuntimeError) as exc:
                    is_oom = isinstance(exc, torch.cuda.OutOfMemoryError) or "out of memory" in str(exc).lower()
                    if not is_oom:
                        raise
                    attempts.append({
                        "precision": attempted_precision, "quantization": attempted_quantization, "batch_size": candidate,
                        "maximum_length": args.max_length, "status": "oom", "error": type(exc).__name__,
                        "peak_memory": _memory_snapshot(device), "started_utc": started,
                    })
                    if device.type == "cuda":
                        torch.cuda.empty_cache()
                    break
            if stable_batch < 1:
                raise RuntimeError("batch size 1 was not stable")
            selected_model = model
            selected_config = {"precision": attempted_precision, "quantization": attempted_quantization, "peak_memory": _memory_snapshot(device)}
            selected_batch = stable_batch
            break
        except Exception as exc:
            is_oom = isinstance(exc, torch.cuda.OutOfMemoryError) or "out of memory" in str(exc).lower()
            attempts.append({
                "precision": attempted_precision, "quantization": attempted_quantization, "batch_size": 1,
                "maximum_length": args.max_length, "status": "oom" if is_oom else "error", "error": type(exc).__name__,
                "message": str(exc)[:500], "peak_memory": _memory_snapshot(device), "started_utc": started,
            })
            if model is not None:
                _clear_model(model, device)
            if not is_oom and args.quantization != "auto":
                raise
    if selected_model is None or selected_config is None:
        raise RuntimeError("Qwen3-Embedding-8B could not run at batch size 1; see OOM attempts")
    return selected_model, selected_config, selected_batch, attempts


def _metadata_columns() -> list[str]:
    return [
        "patient_id", "visit_id", "primary_key", "admission_time", "discharge_time", "department",
        "birth_year", "age_at_visit", "gender_code", "diagnosis_count", "medicine_count", "procedure_count",
        "note_section_count", "observation_count", "has_diagnosis", "has_medicine", "has_procedure",
        "has_clinical_note", "actual_note_row_count", "note_type_counts", "section_names", "note_event_time_min",
        "note_event_time_max", "source_sheets", "source_row_count_total", "token_count", "chunk_count",
        "model_id", "model_revision", "native_dimension", "output_dimension", "normalized", "precision",
        "quantization", "max_length",
    ]


def _write_atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _part_paths(parts_dir: Path) -> list[Path]:
    return sorted(parts_dir.glob("part-*.parquet"))


def _load_completed_parts(parts_dir: Path, native_dimension: int) -> tuple[list[pd.DataFrame], set[str]]:
    frames: list[pd.DataFrame] = []
    completed: set[str] = set()
    expected = set(_metadata_columns()) | {f"embedding_{index:04d}" for index in range(native_dimension)}
    for path in _part_paths(parts_dir):
        frame = pd.read_parquet(path)
        missing = expected.difference(frame.columns)
        if missing:
            raise ValueError(f"invalid resume shard {path.name}; missing columns: {sorted(missing)[:5]}")
        frame["visit_id"] = frame["visit_id"].astype(str)
        if frame["visit_id"].duplicated().any() or completed.intersection(frame["visit_id"]):
            raise ValueError(f"duplicate visit_id across resume shards near {path.name}")
        completed.update(frame["visit_id"])
        frames.append(frame)
    return frames, completed


def _embedding_frame(metadata: Mapping[str, Any] | pd.DataFrame, vectors: np.ndarray, model_id: str, model_revision: str, precision: str, quantization: str, max_length: int) -> pd.DataFrame:
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[1] != EXPECTED_NATIVE_DIMENSION:
        raise ValueError("unexpected native embedding shape")
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4, rtol=1e-4):
        raise ValueError("native embeddings are invalid or not L2-normalized")
    if isinstance(metadata, pd.DataFrame):
        result = metadata.reset_index(drop=True).copy()
    else:
        result = pd.DataFrame([dict(metadata) for _ in range(len(vectors))])
    if len(result) != len(vectors):
        raise ValueError("metadata and vector row counts differ")
    result["model_id"] = model_id
    result["model_revision"] = model_revision
    result["native_dimension"] = EXPECTED_NATIVE_DIMENSION
    result["output_dimension"] = EXPECTED_NATIVE_DIMENSION
    result["normalized"] = True
    result["precision"] = precision
    result["quantization"] = quantization
    result["max_length"] = max_length
    vector_frame = pd.DataFrame(
        vectors,
        columns=[f"embedding_{index:04d}" for index in range(EXPECTED_NATIVE_DIMENSION)],
    )
    return pd.concat([result, vector_frame], axis=1)


def _merge_outputs(frames: list[pd.DataFrame], visit_order: Sequence[str], output_dir: Path, model_slug: str, manifest_base: dict[str, Any]) -> dict[str, Any]:
    if not frames:
        raise ValueError("no embedding shards found")
    merged = pd.concat(frames, ignore_index=True)
    merged["visit_id"] = merged["visit_id"].astype(str)
    if len(merged) != len(visit_order) or set(merged["visit_id"]) != set(visit_order):
        raise ValueError("merged shards do not cover exactly all visits")
    if merged["visit_id"].duplicated().any():
        raise ValueError("merged shards contain duplicate visit_id")
    order = pd.Series(np.arange(len(visit_order)), index=list(visit_order))
    merged = merged.assign(_order=merged["visit_id"].map(order)).sort_values("_order").drop(columns=["_order"])
    metadata = _metadata_columns()
    vector_columns = [f"embedding_{index:04d}" for index in range(EXPECTED_NATIVE_DIMENSION)]
    if set(FORBIDDEN_OUTPUT_COLUMNS).intersection(merged.columns):
        raise ValueError("raw text or hidden-state columns would be persisted")
    output_4096 = merged[metadata + vector_columns].copy()
    prefix = output_4096[[f"embedding_{index:04d}" for index in range(OUTPUT_256_DIMENSION)]].to_numpy(dtype=np.float32)
    prefix_norm = np.linalg.norm(prefix, axis=1, keepdims=True)
    if np.any(prefix_norm == 0) or not np.isfinite(prefix_norm).all():
        raise ValueError("256-D prefix has invalid norm")
    prefix = prefix / prefix_norm
    output_256 = pd.concat(
        [
            merged[metadata].copy().reset_index(drop=True),
            pd.DataFrame(
                prefix.astype(np.float32),
                columns=[f"embedding_{index:04d}" for index in range(OUTPUT_256_DIMENSION)],
            ),
        ],
        axis=1,
    )
    output_256["output_dimension"] = OUTPUT_256_DIMENSION
    output_256 = output_256[metadata + [f"embedding_{index:04d}" for index in range(OUTPUT_256_DIMENSION)]]
    for frame, dimension in ((output_4096, EXPECTED_NATIVE_DIMENSION), (output_256, OUTPUT_256_DIMENSION)):
        values = frame[[f"embedding_{index:04d}" for index in range(dimension)]].to_numpy(dtype=np.float32)
        if not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1.0, atol=1e-4, rtol=1e-4):
            raise ValueError(f"invalid {dimension}-D output vectors")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_4096 = output_dir / f"visit_note_embeddings_{model_slug}_{EXPECTED_NATIVE_DIMENSION}d.csv"
    out_256 = output_dir / f"visit_note_embeddings_{model_slug}_{OUTPUT_256_DIMENSION}d.csv"
    manifest_path = output_dir / "manifest.json"
    if out_4096.exists() or out_256.exists() or manifest_path.exists():
        raise FileExistsError("refusing to overwrite an existing final output or manifest")
    temporary_paths: list[Path] = []
    try:
        for frame, target in ((output_4096, out_4096), (output_256, out_256)):
            temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
            frame.to_csv(temporary, index=False, float_format="%.9g")
            temporary_paths.append(temporary)
        output_checksums = {
            out_4096.name: {"sha256": _sha256(temporary_paths[0]), "bytes": temporary_paths[0].stat().st_size},
            out_256.name: {"sha256": _sha256(temporary_paths[1]), "bytes": temporary_paths[1].stat().st_size},
        }
        os.replace(temporary_paths[0], out_4096)
        os.replace(temporary_paths[1], out_256)
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
    manifest = dict(manifest_base)
    manifest.update({
        "outputs": output_checksums,
        "output_filenames": [out_4096.name, out_256.name],
        "embedding_dimensions": [EXPECTED_NATIVE_DIMENSION, OUTPUT_256_DIMENSION],
        "l2_normalization_policy": "4096-D normalized model output; 256-D is the 4096-D prefix then normalized again",
        "raw_text_persisted": False,
        "clinical_similarity_labels_used": False,
    })
    temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp.{os.getpid()}")
    try:
        temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_manifest, manifest_path)
    finally:
        temporary_manifest.unlink(missing_ok=True)
    return {"output_4096": str(out_4096), "output_256": str(out_256), "manifest": str(manifest_path), "manifest_data": manifest}


def _model_slug(model_id: str) -> str:
    slug = model_id.split("/")[-1].lower().replace("-embedding-", "_").replace("-", "_")
    return slug.replace("_embedding", "")


def _preflight(args: argparse.Namespace) -> tuple[pd.DataFrame, list[str], Any, dict[str, Any], int]:
    notes, visits = _read_inputs(args.input_notes, args.input_visits)
    visit_frame, visit_order = _prepare_visits(notes, visits)
    tokenizer = _load_tokenizer(args.model, args.model_revision, args.tokenizer_revision, args.cache_dir)
    stats = _token_statistics(visit_frame, tokenizer, args.max_length)
    return visit_frame, visit_order, tokenizer, stats, len(notes)


def _run(args: argparse.Namespace) -> int:
    if args.max_length <= 0 or args.max_batch_size <= 0 or args.shard_size <= 0:
        raise ValueError("max_length, max_batch_size and shard_size must be positive")
    if args.max_length > DEFAULT_CONTEXT_LENGTH:
        raise ValueError(f"max_length cannot exceed the Qwen3 context limit {DEFAULT_CONTEXT_LENGTH}")
    visit_frame, visit_order, tokenizer, token_stats, note_count = _preflight(args)
    print(json.dumps({"row_counts": {"clinical_notes": note_count, "visits": len(visit_frame)}, "token_length_statistics": token_stats}, ensure_ascii=False))
    if token_stats["over_context_count"]:
        raise RuntimeError("one or more visits exceed the model context; full run stopped. Choose an approved long-note policy before continuing.")
    if args.preflight_only:
        return 0
    device = _device(args.device)
    if args.smoke_only:
        model, config, batch_size, attempts = _select_model_and_batch(args, tokenizer, visit_frame, device)
        try:
            smoke = _run_smoke(model, tokenizer, visit_frame, device, args.max_length, batch_size, _smoke_indices(visit_frame))
            print(json.dumps({"smoke": "ok", "batch_size": batch_size, "config": config, "attempts": attempts, "peak_memory": smoke}, ensure_ascii=False))
        finally:
            _clear_model(model, device)
        return 0
    model, config, batch_size, oom_attempts = _select_model_and_batch(args, tokenizer, visit_frame, device)
    model_config = getattr(model, "config", None)
    actual_model_revision = str(getattr(model_config, "_commit_hash", None) or args.model_revision)
    tokenizer_revision = str(tokenizer.init_kwargs.get("_commit_hash", None) or args.tokenizer_revision or args.model_revision)
    model_slug = _model_slug(args.model)
    parts_dir = args.output_dir / f"parts_{model_slug}_{EXPECTED_NATIVE_DIMENSION}d"
    existing_frames, completed = _load_completed_parts(parts_dir, EXPECTED_NATIVE_DIMENSION) if args.resume else ([], set())
    expected_ids = set(visit_order)
    if not completed.issubset(expected_ids):
        raise ValueError("resume shards contain visit_id values absent from current inputs")
    remaining = visit_frame[~visit_frame["visit_id"].isin(completed)].reset_index(drop=True)
    metadata_base = {
        "model_id": args.model, "model_revision": actual_model_revision, "native_dimension": EXPECTED_NATIVE_DIMENSION,
        "output_dimension": EXPECTED_NATIVE_DIMENSION, "normalized": True, "precision": config["precision"],
        "quantization": config["quantization"], "max_length": args.max_length,
    }
    for start in range(0, len(remaining), batch_size):
        batch = remaining.iloc[start : start + batch_size]
        vectors = _forward(model, tokenizer, batch["_text"].tolist(), device, args.max_length).cpu().numpy().astype(np.float32)
        rows = []
        for row in batch.to_dict(orient="records"):
            row = {key: value for key, value in row.items() if key != "_text"}
            row.update(metadata_base)
            rows.append(row)
        part_frame = _embedding_frame(
            pd.DataFrame(rows), vectors, args.model, actual_model_revision,
            config["precision"], config["quantization"], args.max_length,
        )
        shard_number = len(_part_paths(parts_dir))
        _write_atomic_parquet(part_frame, parts_dir / f"part-{shard_number:06d}.parquet")
    _clear_model(model, device)
    all_frames, all_completed = _load_completed_parts(parts_dir, EXPECTED_NATIVE_DIMENSION)
    if all_completed != expected_ids:
        raise RuntimeError(f"embedding shards incomplete: {len(all_completed)}/{len(expected_ids)} visits")
    manifest_base = {
        "run_started_utc": datetime.now(timezone.utc).isoformat(),
        "command": shlex.join([sys.executable, *sys.argv]),
        "source_paths": {"clinical_notes": str(args.input_notes), "visits": str(args.input_visits)},
        "source_sha256": {"clinical_notes": _sha256(args.input_notes), "visits": _sha256(args.input_visits)},
        "row_counts": {"clinical_notes": note_count, "visits": len(visit_frame), "output_visits": len(visit_order)},
        "model_id": args.model, "model_revision": actual_model_revision, "tokenizer_revision": tokenizer_revision,
        "dependency_versions": _dependency_versions(), "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
        "gpu": _gpu_info(device), "precision": config["precision"], "quantization": config["quantization"],
        "batch_size": batch_size, "maximum_length": args.max_length, "token_length_statistics": token_stats,
        "oom_attempts": oom_attempts, "peak_vram": config["peak_memory"], "resume_completed_visit_count": len(completed),
    }
    result = _merge_outputs(all_frames, visit_order, args.output_dir, model_slug, manifest_base)
    print(json.dumps({key: value for key, value in result.items() if key != "manifest_data"}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    return _run(_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
