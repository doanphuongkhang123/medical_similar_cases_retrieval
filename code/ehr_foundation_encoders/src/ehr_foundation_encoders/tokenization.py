"""Tokenizer-only audit for SMB visit timelines.

This stage never loads model weights and never persists serialized clinical
text or token IDs. It measures both full longitudinal history and the target
visit plus demographics so truncation can be designed from evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .common import sha256_file, write_json
from .smb import (
    MEDS_COLUMNS,
    SMB_MAX_SEQUENCE_LENGTH,
    SMB_MODEL_ID,
    SMB_MODEL_REVISION,
    SMB_UTILS_REVISION,
    build_target_meds,
    group_events_by_patient,
    validate_common_input,
)


def _quantiles(values: pd.Series) -> dict[str, float]:
    points = [0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0]
    return {
        str(point): float(value)
        for point, value in values.quantile(points).items()
    }


def _token_lengths(tokenizer: Any, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=True,
        truncation=False,
        padding=False,
        return_attention_mask=False,
        return_token_type_ids=False,
    )
    input_ids = encoded["input_ids"]
    return [len(ids) for ids in input_ids]


def _flush_batch(
    tokenizer: Any,
    pending: list[dict[str, Any]],
    full_texts: list[str],
    current_texts: list[str],
    rows: list[dict[str, Any]],
    max_length: int,
) -> None:
    if not pending:
        return
    full_lengths = _token_lengths(tokenizer, full_texts)
    current_lengths = _token_lengths(tokenizer, current_texts)
    for metadata, full_tokens, current_tokens in zip(
        pending, full_lengths, current_lengths
    ):
        metadata.update(
            full_token_count=int(full_tokens),
            full_over_limit=bool(full_tokens > max_length),
            full_overflow_tokens=max(0, int(full_tokens - max_length)),
            current_plus_demographics_token_count=int(current_tokens),
            current_plus_demographics_over_limit=bool(current_tokens > max_length),
            current_plus_demographics_overflow_tokens=max(
                0, int(current_tokens - max_length)
            ),
        )
        rows.append(metadata)
    pending.clear()
    full_texts.clear()
    current_texts.clear()


def audit_smb_token_lengths(
    events: pd.DataFrame,
    targets: pd.DataFrame,
    tokenizer: Any,
    formatter: Callable[..., str],
    output_root: Path,
    tokenizer_root: Path,
    max_length: int = SMB_MAX_SEQUENCE_LENGTH,
    batch_size: int = 16,
    overwrite: bool = False,
    max_targets: int | None = None,
) -> dict[str, Any]:
    """Measure untruncated SMB token lengths for every target visit."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_targets is not None and max_targets <= 0:
        raise ValueError("max_targets must be positive")
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite non-empty output directory: {output_root}"
        )
    validate_common_input(events, targets)
    patient_events = group_events_by_patient(events)
    ordered = targets.sort_values("target_order")
    if max_targets is not None:
        ordered = ordered.head(max_targets)

    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    full_texts: list[str] = []
    current_texts: list[str] = []
    empty = events.iloc[0:0]
    for target in ordered.itertuples(index=False):
        selected = build_target_meds(
            patient_events.get(str(target.patient_id), empty), target
        )
        current = selected[
            selected["source_table"].eq("demographics")
            | selected["visit_id"].astype(str).eq(str(target.visit_id))
        ].copy()
        full_text = formatter(
            selected[list(MEDS_COLUMNS)],
            subject_id=str(target.patient_id),
            code_column="code",
            category_column="table",
            end_time=pd.Timestamp(target.cutoff_time),
            include_demographics=True,
        )
        current_text = formatter(
            current[list(MEDS_COLUMNS)],
            subject_id=str(target.patient_id),
            code_column="code",
            category_column="table",
            end_time=pd.Timestamp(target.cutoff_time),
            include_demographics=True,
        )
        if not isinstance(full_text, str) or not isinstance(current_text, str):
            raise TypeError("SMB formatter must return strings")
        if not full_text.strip() or not current_text.strip():
            raise ValueError(f"Empty serialization for target visit {target.visit_id}")
        pending.append(
            {
                "target_order": int(target.target_order),
                "patient_id": str(target.patient_id),
                "visit_id": str(target.visit_id),
                "cutoff_time": pd.Timestamp(target.cutoff_time),
                "history_event_count": int(len(selected)),
                "current_plus_demographics_event_count": int(len(current)),
                "current_visit_clinical_event_count": int(
                    current["source_table"].ne("demographics").sum()
                ),
                "full_serialized_char_count": len(full_text),
                "current_serialized_char_count": len(current_text),
                "full_serialized_sha256": hashlib.sha256(
                    full_text.encode("utf-8")
                ).hexdigest(),
                "current_serialized_sha256": hashlib.sha256(
                    current_text.encode("utf-8")
                ).hexdigest(),
            }
        )
        full_texts.append(full_text)
        current_texts.append(current_text)
        if len(pending) >= batch_size:
            _flush_batch(
                tokenizer, pending, full_texts, current_texts, rows, max_length
            )
    _flush_batch(tokenizer, pending, full_texts, current_texts, rows, max_length)

    audit = pd.DataFrame(rows).sort_values("target_order").reset_index(drop=True)
    if audit.empty:
        raise ValueError("Tokenization audit produced no targets")
    integer_columns = [
        column
        for column in audit.columns
        if column.endswith("_count") or column.endswith("_tokens")
    ]
    if not np.isfinite(audit[integer_columns].to_numpy(dtype=float)).all():
        raise ValueError("Tokenization audit contains non-finite counts")

    tokenizer_manifest_path = tokenizer_root / "tokenizer_manifest.json"
    tokenizer_manifest = (
        json.loads(tokenizer_manifest_path.read_text(encoding="utf-8"))
        if tokenizer_manifest_path.exists()
        else {}
    )
    tokenizer_files = [
        path
        for path in tokenizer_root.rglob("*")
        if path.is_file() and ".cache" not in path.parts
    ]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "stage": "smb_tokenizer_length_audit",
        "model": SMB_MODEL_ID,
        "model_revision": tokenizer_manifest.get(
            "resolved_revision", SMB_MODEL_REVISION
        ),
        "max_length": max_length,
        "smb_utils_revision": SMB_UTILS_REVISION,
        "tokenizer": {
            "class": tokenizer.__class__.__name__,
            "vocab_size": int(len(tokenizer)),
            "reported_model_max_length": int(tokenizer.model_max_length),
            "root": str(tokenizer_root.resolve()),
            "manifest_sha256": (
                sha256_file(tokenizer_manifest_path)
                if tokenizer_manifest_path.exists()
                else ""
            ),
            "files": {
                str(path.relative_to(tokenizer_root)): {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in sorted(tokenizer_files)
            },
        },
        "counts": {
            "targets": int(len(audit)),
            "full_history_over_limit": int(audit["full_over_limit"].sum()),
            "full_history_within_limit": int((~audit["full_over_limit"]).sum()),
            "current_plus_demographics_over_limit": int(
                audit["current_plus_demographics_over_limit"].sum()
            ),
        },
        "quantiles": {
            "full_token_count": _quantiles(audit["full_token_count"]),
            "current_plus_demographics_token_count": _quantiles(
                audit["current_plus_demographics_token_count"]
            ),
            "full_overflow_tokens": _quantiles(audit["full_overflow_tokens"]),
        },
        "policy": {
            "measurement": "untruncated token count with special tokens",
            "current_view": "target visit clinical events plus patient demographics",
            "truncation_applied": False,
            "serialized_text_persisted": False,
            "token_ids_persisted": False,
        },
        "model_weights_used": False,
        "encoder_run": False,
        "gpu_used": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    audit.to_parquet(output_root / "token_length_audit.parquet", index=False)
    write_json(output_root / "manifest.json", manifest)
    return manifest
