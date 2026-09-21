#!/usr/bin/env python3
"""Offline Qwen3 patient embeddings and exact-cosine retrieval.

This pipeline starts from the canonical raw workbook, creates its own copy of
the agreed patient text bundle, downloads a pinned public Qwen snapshot, runs a
representative CUDA smoke, and then writes normalized query/document vectors.
No API key or hosted inference endpoint is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Sequence

import numpy as np

from common import read_json, read_jsonl, sha256, write_json
from prepare_qwen3_inputs import prepare as prepare_inputs
from prepare_qwen3_inputs import verify as verify_inputs


MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
EXPECTED_DIMENSION = 1024
MAX_LENGTH = 32768
TASK_INSTRUCTION = (
    "Given a patient clinical profile, retrieve other patient profiles with "
    "similar diseases, diagnoses, symptoms, and clinical course."
)
INPUT_BUNDLE = "input_bundle"
DOCUMENT_FILE = "document_embeddings.npy"
QUERY_FILE = "query_embeddings.npy"
IDS_FILE = "patient_ids.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def query_text(text: str) -> str:
    return f"Instruct: {TASK_INSTRUCTION}\nQuery: {text}"


def last_token_pool(last_hidden_states, attention_mask):
    import torch

    left_padding = bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item())
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    return last_hidden_states[
        torch.arange(last_hidden_states.shape[0], device=last_hidden_states.device),
        sequence_lengths,
    ]


def initialize(workbook: Path, output: Path) -> dict[str, Any]:
    workbook, output = workbook.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    input_manifest = prepare_inputs(workbook, output / INPUT_BUNDLE)
    state = {
        "schema_version": 1,
        "status": "input_prepared",
        "created_at": utc_now(),
        "host": socket.gethostname(),
        "raw_input": str(workbook),
        "raw_sha256": input_manifest["raw_sha256"],
        "input_bundle": INPUT_BUNDLE,
        "input_manifest_sha256": sha256(output / INPUT_BUNDLE / "manifest.json"),
        "patients": input_manifest["patients"],
        "clinical_data_sent": False,
        "api_calls": 0,
    }
    write_json(output / "pipeline_state.json", state)
    return state


def _snapshot_files(snapshot: Path) -> list[dict[str, Any]]:
    values = []
    for path in sorted(p for p in snapshot.rglob("*") if p.is_file()):
        values.append({
            "path": str(path.relative_to(snapshot)),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    if not values:
        raise ValueError("Downloaded model snapshot is empty")
    return values


def download_model(output: Path, cache_dir: Path, model_id: str, revision: str) -> dict[str, Any]:
    from huggingface_hub import snapshot_download

    output, cache_dir = output.resolve(), cache_dir.resolve()
    state = read_json(output / "pipeline_state.json")
    if (output / "model_download.json").exists():
        raise FileExistsError("model_download.json already exists; refusing to replace pinned model metadata")
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot = Path(snapshot_download(repo_id=model_id, revision=revision, cache_dir=cache_dir)).resolve()
    resolved_revision = snapshot.name
    if not re.fullmatch(r"[0-9a-f]{40,64}", resolved_revision):
        raise ValueError("Hugging Face snapshot path does not contain a commit revision")
    manifest = {
        "schema_version": 1,
        "downloaded_at": utc_now(),
        "host": socket.gethostname(),
        "model_id": model_id,
        "requested_revision": revision,
        "resolved_revision": resolved_revision,
        "snapshot_path": str(snapshot),
        "cache_dir": str(cache_dir),
        "files": _snapshot_files(snapshot),
        "raw_sha256": state["raw_sha256"],
        "clinical_data_read": False,
        "clinical_data_sent": False,
        "api_calls": 0,
    }
    write_json(output / "model_download.json", manifest)
    return manifest


def _load_rows(output: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    output = output.resolve()
    verified = verify_inputs(output / INPUT_BUNDLE)
    manifest = read_json(output / INPUT_BUNDLE / "manifest.json")
    rows = read_jsonl(output / INPUT_BUNDLE / manifest["output_file"])
    ids = [row["patient_id"] for row in rows]
    texts = [row["embedding_text"] for row in rows]
    if ids != sorted(ids) or len(ids) != len(set(ids)) or len(ids) != verified["patients"]:
        raise ValueError("Input bundle has invalid patient identity order or count")
    return ids, texts, manifest


def _load_download(output: Path) -> dict[str, Any]:
    manifest = read_json(output / "model_download.json")
    snapshot = Path(manifest["snapshot_path"])
    if not snapshot.is_dir() or snapshot.name != manifest["resolved_revision"]:
        raise ValueError("Pinned model snapshot is missing or changed")
    current = {item["path"]: item for item in _snapshot_files(snapshot)}
    expected = {item["path"]: item for item in manifest["files"]}
    if current != expected:
        raise ValueError("Pinned model files do not match model_download.json")
    return manifest


def _dtype(precision: str):
    import torch

    return torch.bfloat16 if precision == "bf16" else torch.float16


def _load_encoder(snapshot: Path, precision: str, device: str):
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(snapshot), local_files_only=True, padding_side="left"
    )
    tokenizer.padding_side = "left"
    model = AutoModel.from_pretrained(
        str(snapshot), local_files_only=True, dtype=_dtype(precision), low_cpu_mem_usage=True
    )
    model.to(torch.device(device))
    model.eval()
    dimension = int(getattr(model.config, "hidden_size", 0))
    if dimension != EXPECTED_DIMENSION:
        raise ValueError(f"Expected {EXPECTED_DIMENSION}-D Qwen output, found {dimension}")
    return tokenizer, model


def _token_lengths(tokenizer, texts: Sequence[str], batch_size: int = 64) -> list[int]:
    lengths: list[int] = []
    for start in range(0, len(texts), batch_size):
        encoded = tokenizer(
            list(texts[start : start + batch_size]),
            add_special_tokens=True,
            padding=False,
            truncation=False,
            return_attention_mask=False,
        )
        lengths.extend(len(value) for value in encoded["input_ids"])
    return lengths


def _statistics(values: Sequence[int]) -> dict[str, int]:
    array = np.asarray(values, dtype=np.int64)
    if array.size == 0:
        raise ValueError("Cannot summarize empty token lengths")
    return {
        "min": int(array.min()),
        "p50": int(np.percentile(array, 50)),
        "p95": int(np.percentile(array, 95)),
        "max": int(array.max()),
        "total": int(array.sum()),
    }


def _forward(model, tokenizer, texts: Sequence[str], device: str, max_length: int) -> np.ndarray:
    import torch
    import torch.nn.functional as functional

    encoded = tokenizer(
        list(texts), padding=True, truncation=False, return_tensors="pt"
    )
    length = int(encoded["input_ids"].shape[1])
    if length > max_length:
        raise ValueError(f"Input batch has {length} tokens, above max_length={max_length}")
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        outputs = model(**encoded)
        vectors = last_token_pool(outputs.last_hidden_state, encoded["attention_mask"])
        vectors = functional.normalize(vectors.float(), p=2, dim=1)
    array = vectors.cpu().numpy().astype(np.float32, copy=False)
    if array.shape != (len(texts), EXPECTED_DIMENSION):
        raise ValueError(f"Unexpected embedding shape {array.shape}")
    if not np.isfinite(array).all() or not np.allclose(
        np.linalg.norm(array, axis=1), 1.0, atol=1e-4, rtol=1e-4
    ):
        raise ValueError("Encoder returned non-finite or non-normalized vectors")
    return array


def _cuda_snapshot(device: str) -> dict[str, Any]:
    import torch

    target = torch.device(device)
    if target.type != "cuda":
        return {"device": str(target)}
    free, total = torch.cuda.mem_get_info(target)
    index = target.index if target.index is not None else torch.cuda.current_device()
    return {
        "device": str(target),
        "index": int(index),
        "name": torch.cuda.get_device_name(index),
        "free_bytes": int(free),
        "total_bytes": int(total),
        "allocated_bytes": int(torch.cuda.memory_allocated(target)),
        "reserved_bytes": int(torch.cuda.memory_reserved(target)),
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(target)),
        "peak_reserved_bytes": int(torch.cuda.max_memory_reserved(target)),
    }


def smoke(output: Path, batch_size: int, precision: str, device: str, max_length: int) -> dict[str, Any]:
    import torch

    output = output.resolve()
    if batch_size <= 0 or max_length <= 0 or max_length > MAX_LENGTH:
        raise ValueError("Invalid smoke batch_size or max_length")
    if torch.device(device).type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("Representative smoke requires an available CUDA device")
    ids, texts, input_manifest = _load_rows(output)
    download = _load_download(output)
    tokenizer, model = _load_encoder(Path(download["snapshot_path"]), precision, device)
    document_lengths = _token_lengths(tokenizer, texts)
    queries = [query_text(value) for value in texts]
    query_lengths = _token_lengths(tokenizer, queries)
    if max(document_lengths + query_lengths) > max_length:
        raise ValueError("At least one production input exceeds the selected max_length")
    longest_document = texts[int(np.argmax(document_lengths))]
    longest_query = queries[int(np.argmax(query_lengths))]
    torch.cuda.reset_peak_memory_stats(torch.device(device))
    before = _cuda_snapshot(device)
    started = time.monotonic()
    _forward(model, tokenizer, [longest_document] * batch_size, device, max_length)
    _forward(model, tokenizer, [longest_query] * batch_size, device, max_length)
    result = {
        "schema_version": 1,
        "status": "passed",
        "completed_at": utc_now(),
        "host": socket.gethostname(),
        "model_id": download["model_id"],
        "model_revision": download["resolved_revision"],
        "precision": precision,
        "device": device,
        "batch_size": batch_size,
        "max_length": max_length,
        "patients": len(ids),
        "document_tokens": _statistics(document_lengths),
        "query_tokens": _statistics(query_lengths),
        "gpu_before": before,
        "gpu_after": _cuda_snapshot(device),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "input_sha256": input_manifest["output_sha256"],
        "clinical_data_persisted_by_smoke": False,
        "clinical_data_sent": False,
        "api_calls": 0,
    }
    write_json(output / "smoke.json", result)
    return result


def _write_npy_atomic(path: Path, array: np.ndarray) -> None:
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            np.save(handle, array, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _encode_all(model, tokenizer, texts: Sequence[str], batch_size: int, device: str,
                max_length: int, label: str) -> np.ndarray:
    vectors = np.empty((len(texts), EXPECTED_DIMENSION), dtype=np.float32)
    for start in range(0, len(texts), batch_size):
        stop = min(len(texts), start + batch_size)
        vectors[start:stop] = _forward(model, tokenizer, texts[start:stop], device, max_length)
        if stop == len(texts) or stop % 100 == 0:
            print(json.dumps({"mode": label, "completed": stop, "total": len(texts)}), flush=True)
    return vectors


def run(output: Path, batch_size: int, precision: str, device: str, max_length: int) -> dict[str, Any]:
    import torch
    import transformers

    output = output.resolve()
    if (output / "manifest.json").exists():
        raise FileExistsError("Final manifest already exists; refusing to overwrite embeddings")
    smoke_manifest = read_json(output / "smoke.json")
    expected_smoke = {
        "status": "passed", "batch_size": batch_size, "precision": precision,
        "device": device, "max_length": max_length,
    }
    if any(smoke_manifest.get(key) != value for key, value in expected_smoke.items()):
        raise ValueError("Run configuration does not match the passed representative smoke")
    ids, texts, input_manifest = _load_rows(output)
    download = _load_download(output)
    if smoke_manifest["model_revision"] != download["resolved_revision"]:
        raise ValueError("Smoke and run model revisions differ")
    tokenizer, model = _load_encoder(Path(download["snapshot_path"]), precision, device)
    document_lengths = _token_lengths(tokenizer, texts)
    queries = [query_text(value) for value in texts]
    query_lengths = _token_lengths(tokenizer, queries)
    if max(document_lengths + query_lengths) > max_length:
        raise ValueError("At least one production input exceeds max_length")
    torch.cuda.reset_peak_memory_stats(torch.device(device))
    started_at, started = utc_now(), time.monotonic()
    document_vectors = _encode_all(model, tokenizer, texts, batch_size, device, max_length, "document")
    query_vectors = _encode_all(model, tokenizer, queries, batch_size, device, max_length, "query")
    _write_npy_atomic(output / DOCUMENT_FILE, document_vectors)
    _write_npy_atomic(output / QUERY_FILE, query_vectors)
    write_json(output / IDS_FILE, ids)
    manifest = {
        "schema_version": 1,
        "status": "complete_not_clinically_validated",
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "host": socket.gethostname(),
        "raw_input": input_manifest["raw_input"],
        "raw_sha256": input_manifest["raw_sha256"],
        "input_bundle": INPUT_BUNDLE,
        "input_sha256": input_manifest["output_sha256"],
        "model_id": download["model_id"],
        "model_revision": download["resolved_revision"],
        "model_snapshot": download["snapshot_path"],
        "embedding_dimension": EXPECTED_DIMENSION,
        "dtype": "float32",
        "l2_normalized": True,
        "patients": len(ids),
        "document_policy": "embedding_text without instruction",
        "query_policy": "English retrieval instruction prepended to embedding_text",
        "task_instruction": TASK_INSTRUCTION,
        "similarity": "exact cosine via dot product of L2-normalized query and document vectors",
        "self_match_excluded": True,
        "precision": precision,
        "batch_size": batch_size,
        "max_length": max_length,
        "document_tokens": _statistics(document_lengths),
        "query_tokens": _statistics(query_lengths),
        "gpu": _cuda_snapshot(device),
        "dependencies": {
            "numpy": np.__version__, "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "outputs": {
            DOCUMENT_FILE: sha256(output / DOCUMENT_FILE),
            QUERY_FILE: sha256(output / QUERY_FILE),
            IDS_FILE: sha256(output / IDS_FILE),
        },
        "clinical_data_sent": False,
        "api_calls": 0,
        "clinical_validation_performed": False,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def _load_vectors(output: Path) -> tuple[list[str], np.ndarray, np.ndarray, dict[str, Any]]:
    manifest = read_json(output / "manifest.json")
    for filename, expected in manifest["outputs"].items():
        if sha256(output / filename) != expected:
            raise ValueError(f"Artifact hash mismatch: {filename}")
    ids = read_json(output / IDS_FILE)
    documents = np.load(output / DOCUMENT_FILE, allow_pickle=False)
    queries = np.load(output / QUERY_FILE, allow_pickle=False)
    expected_shape = (manifest["patients"], manifest["embedding_dimension"])
    if documents.shape != expected_shape or queries.shape != expected_shape:
        raise ValueError("Embedding matrix shape mismatch")
    if ids != sorted(ids) or len(ids) != len(set(ids)) or len(ids) != manifest["patients"]:
        raise ValueError("Patient IDs are missing, duplicated, or out of order")
    for name, matrix in (("document", documents), ("query", queries)):
        if matrix.dtype != np.float32 or not np.isfinite(matrix).all():
            raise ValueError(f"{name} embeddings have invalid dtype or values")
        if not np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-4, rtol=1e-4):
            raise ValueError(f"{name} embeddings are not L2-normalized")
    return ids, documents, queries, manifest


def exact_cosine(output: Path, patient_id: str, top_k: int) -> list[dict[str, Any]]:
    ids, documents, queries, _ = _load_vectors(output.resolve())
    if patient_id not in ids:
        raise KeyError(f"Unknown patient_id {patient_id}")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    query_index = ids.index(patient_id)
    scores = documents @ queries[query_index]
    scores[query_index] = -np.inf
    count = min(top_k, len(ids) - 1)
    candidates = np.argpartition(-scores, count - 1)[:count]
    ordered = sorted(candidates.tolist(), key=lambda index: (-float(scores[index]), ids[index]))
    return [
        {"rank": rank, "patient_id": ids[index], "cosine_similarity": float(scores[index])}
        for rank, index in enumerate(ordered, 1)
    ]


def verify(output: Path) -> dict[str, Any]:
    output = output.resolve()
    ids, documents, queries, manifest = _load_vectors(output)
    state = read_json(output / "pipeline_state.json")
    input_manifest = read_json(output / INPUT_BUNDLE / "manifest.json")
    if len({manifest["raw_sha256"], input_manifest["raw_sha256"], state["raw_sha256"]}) != 1:
        raise ValueError("Raw workbook lineage mismatch")
    sample = exact_cosine(output, ids[0], min(20, len(ids) - 1))
    if len({row["patient_id"] for row in sample}) != len(sample) or any(
        row["patient_id"] == ids[0] or not np.isfinite(row["cosine_similarity"])
        for row in sample
    ):
        raise ValueError("Exact-cosine retrieval verification failed")
    return {
        "status": "verified",
        "patients": len(ids),
        "document_shape": list(documents.shape),
        "query_shape": list(queries.shape),
        "document_norm_min": float(np.linalg.norm(documents, axis=1).min()),
        "document_norm_max": float(np.linalg.norm(documents, axis=1).max()),
        "query_norm_min": float(np.linalg.norm(queries, axis=1).min()),
        "query_norm_max": float(np.linalg.norm(queries, axis=1).max()),
        "self_match_excluded": True,
        "raw_sha256": manifest["raw_sha256"],
        "clinical_data_sent": False,
        "api_calls": 0,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--workbook", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    download = commands.add_parser("download")
    download.add_argument("--output", type=Path, required=True)
    download.add_argument("--cache-dir", type=Path, required=True)
    download.add_argument("--model", default=MODEL_ID)
    download.add_argument("--revision", default="main")
    for name in ("smoke", "run"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--batch-size", type=int, default=1)
        command.add_argument("--precision", choices=("bf16", "fp16"), default="bf16")
        command.add_argument("--device", default="cuda:0")
        command.add_argument("--max-length", type=int, default=MAX_LENGTH)
    check = commands.add_parser("verify")
    check.add_argument("--output", type=Path, required=True)
    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("--output", type=Path, required=True)
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--top-k", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = initialize(args.workbook, args.output)
    elif args.command == "download":
        result = download_model(args.output, args.cache_dir, args.model, args.revision)
    elif args.command == "smoke":
        result = smoke(args.output, args.batch_size, args.precision, args.device, args.max_length)
    elif args.command == "run":
        result = run(args.output, args.batch_size, args.precision, args.device, args.max_length)
    elif args.command == "verify":
        result = verify(args.output)
    else:
        result = exact_cosine(args.output.resolve(), args.query, args.top_k)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
