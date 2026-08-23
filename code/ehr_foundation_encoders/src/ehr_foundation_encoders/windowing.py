"""Build reproducible recent-event windows for SMB inference."""
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
    SMB_FIX_MISTRAL_REGEX,
    SMB_MAX_SEQUENCE_LENGTH,
    SMB_MODEL_ID,
    SMB_MODEL_REVISION,
    SMB_UTILS_REVISION,
    build_target_meds,
    group_events_by_patient,
    validate_common_input,
)


def _serialize(
    frame: pd.DataFrame,
    target: Any,
    formatter: Callable[..., str],
) -> str:
    text = formatter(
        frame[list(MEDS_COLUMNS)],
        subject_id=str(target.patient_id),
        code_column="code",
        category_column="table",
        end_time=pd.Timestamp(target.cutoff_time),
        include_demographics=True,
    )
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Empty serialization for target visit {target.visit_id}")
    return text


def _token_count(tokenizer: Any, text: str) -> int:
    encoded = tokenizer(
        text,
        add_special_tokens=True,
        truncation=False,
        padding=False,
        return_attention_mask=False,
        return_token_type_ids=False,
        verbose=False,
    )
    return len(encoded["input_ids"])


def _recent_window(
    selected: pd.DataFrame,
    target: Any,
    tokenizer: Any,
    formatter: Callable[..., str],
    max_length: int,
    full_token_count: int,
    full_serialized_sha256: str,
) -> tuple[pd.DataFrame, int, str, int]:
    demographics = selected[selected["source_table"].eq("demographics")]
    clinical = selected[~selected["source_table"].eq("demographics")].copy()
    if clinical.empty:
        if full_token_count > max_length:
            raise ValueError(
                f"Demographics exceed token limit for target {target.visit_id}"
            )
        return selected, full_token_count, full_serialized_sha256, 0
    if full_token_count <= max_length:
        return selected, full_token_count, full_serialized_sha256, 0

    cache: dict[int, tuple[pd.DataFrame, int, str]] = {}

    def evaluate(start: int) -> tuple[pd.DataFrame, int, str]:
        if start not in cache:
            candidate = pd.concat(
                [demographics, clinical.iloc[start:]], ignore_index=True
            )
            text = _serialize(candidate, target, formatter)
            cache[start] = (
                candidate,
                _token_count(tokenizer, text),
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        return cache[start]

    _, last_tokens, _ = evaluate(len(clinical) - 1)
    if last_tokens > max_length:
        raise ValueError(
            "A single latest clinical event plus demographics exceeds "
            f"{max_length} tokens for target {target.visit_id}: {last_tokens}"
        )

    low = 0
    high = len(clinical) - 1
    while low < high:
        middle = (low + high) // 2
        _, tokens, _ = evaluate(middle)
        if tokens <= max_length:
            high = middle
        else:
            low = middle + 1
    window, tokens, digest = evaluate(low)
    if tokens > max_length:
        raise AssertionError("Window search returned an over-limit serialization")
    if low > 0:
        _, previous_tokens, _ = evaluate(low - 1)
        if previous_tokens <= max_length:
            raise AssertionError("Window search did not retain the maximal event suffix")
    return window, tokens, digest, low


def build_smb_window_selection(
    events: pd.DataFrame,
    targets: pd.DataFrame,
    token_audit: pd.DataFrame,
    tokenizer: Any,
    formatter: Callable[..., str],
    output_root: Path,
    tokenizer_root: Path,
    common_root: Path,
    token_audit_root: Path,
    max_length: int = SMB_MAX_SEQUENCE_LENGTH,
    overwrite: bool = False,
    max_targets: int | None = None,
) -> dict[str, Any]:
    """Select the maximal recent event suffix fitting the SMB context limit."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if max_targets is not None and max_targets <= 0:
        raise ValueError("max_targets must be positive")
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite non-empty output directory: {output_root}"
        )
    validate_common_input(events, targets)
    required_audit_columns = {
        "visit_id",
        "full_token_count",
        "full_serialized_sha256",
    }
    if not required_audit_columns.issubset(token_audit.columns):
        raise ValueError("Token audit is missing required columns")
    if token_audit["visit_id"].astype(str).duplicated().any():
        raise ValueError("Token audit visit_id must be unique")
    token_audit_manifest_path = token_audit_root / "manifest.json"
    token_audit_parquet_path = token_audit_root / "token_length_audit.parquet"
    if not token_audit_manifest_path.is_file():
        raise FileNotFoundError(
            f"Missing token audit manifest: {token_audit_manifest_path}"
        )
    token_audit_manifest = json.loads(
        token_audit_manifest_path.read_text(encoding="utf-8")
    )
    if int(token_audit_manifest.get("max_length", -1)) != max_length:
        raise ValueError("Token audit max_length does not match window selection")
    audit_by_visit = token_audit.assign(
        visit_id=token_audit["visit_id"].astype(str)
    ).set_index("visit_id")
    ordered = targets.sort_values("target_order")
    if max_targets is not None:
        ordered = ordered.head(max_targets)
    missing = set(ordered["visit_id"].astype(str)) - set(audit_by_visit.index)
    if missing:
        raise ValueError(f"Token audit is missing {len(missing)} target visits")

    patient_events = group_events_by_patient(events)
    empty = events.iloc[0:0]
    rows: list[dict[str, Any]] = []
    for target in ordered.itertuples(index=False):
        full = build_target_meds(
            patient_events.get(str(target.patient_id), empty), target
        )
        audit_row = audit_by_visit.loc[str(target.visit_id)]
        window, tokens, digest, clinical_start = _recent_window(
            full,
            target,
            tokenizer,
            formatter,
            max_length,
            int(audit_row["full_token_count"]),
            str(audit_row["full_serialized_sha256"]),
        )
        full_clinical = full[~full["source_table"].eq("demographics")]
        window_clinical = window[~window["source_table"].eq("demographics")]
        full_current = full_clinical["visit_id"].astype(str).eq(
            str(target.visit_id)
        )
        window_current = window_clinical["visit_id"].astype(str).eq(
            str(target.visit_id)
        )
        first_retained = window_clinical.iloc[0]
        full_current_count = int(full_current.sum())
        selected_current_count = int(window_current.sum())
        rows.append(
            {
                "target_order": int(target.target_order),
                "patient_id": str(target.patient_id),
                "visit_id": str(target.visit_id),
                "cutoff_time": pd.Timestamp(target.cutoff_time),
                "max_length": int(max_length),
                "full_token_count": int(audit_row["full_token_count"]),
                "selected_token_count": int(tokens),
                "selection_applied": bool(clinical_start > 0),
                "full_event_count": int(len(full)),
                "selected_event_count": int(len(window)),
                "dropped_clinical_event_count": int(clinical_start),
                "full_current_visit_event_count": full_current_count,
                "selected_current_visit_event_count": selected_current_count,
                "all_current_visit_events_retained": bool(
                    selected_current_count == full_current_count
                ),
                "first_retained_event_order_within_patient": int(
                    first_retained["event_order_within_patient"]
                ),
                "first_retained_time": pd.Timestamp(first_retained["time"]),
                "selected_serialized_sha256": digest,
            }
        )

    plan = pd.DataFrame(rows).sort_values("target_order").reset_index(drop=True)
    if plan.empty:
        raise ValueError("SMB window selection produced no targets")
    numeric_columns = [
        column
        for column in plan.columns
        if column.endswith("_count") or column.endswith("_length")
    ]
    if not np.isfinite(plan[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("SMB window selection contains non-finite counts")
    if (plan["selected_token_count"] > max_length).any():
        raise ValueError("At least one selected window exceeds max_length")
    if (plan["selected_event_count"] > plan["full_event_count"]).any():
        raise ValueError("Selected event count exceeds full event count")

    common_manifest_path = common_root / "manifest.json"
    tokenizer_manifest_path = tokenizer_root / "tokenizer_manifest.json"
    for input_path in (
        common_manifest_path,
        common_root / "events.parquet",
        common_root / "targets.parquet",
        token_audit_manifest_path,
        token_audit_parquet_path,
        tokenizer_manifest_path,
    ):
        if not input_path.is_file():
            raise FileNotFoundError(f"Missing window selection input: {input_path}")
    common_manifest = json.loads(common_manifest_path.read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "stage": "smb_recent_event_window_selection",
        "model": SMB_MODEL_ID,
        "model_revision": SMB_MODEL_REVISION,
        "smb_utils_revision": SMB_UTILS_REVISION,
        "max_length": max_length,
        "policy": {
            "window": "demographics plus maximal most-recent clinical event suffix",
            "boundary": "complete source event rows; reserialized by official smb_utils",
            "causal_cutoff": "time <= target visit discharge_time",
            "tokenizer_truncation_used": False,
            "serialized_text_persisted": False,
            "token_ids_persisted": False,
            "events_duplicated": False,
            "reconstruction": (
                "select demographics plus clinical events whose "
                "event_order_within_patient is at least the recorded first retained order"
            ),
        },
        "tokenizer": {
            "class": tokenizer.__class__.__name__,
            "vocab_size": int(len(tokenizer)),
            "reported_model_max_length": int(tokenizer.model_max_length),
            "fix_mistral_regex": SMB_FIX_MISTRAL_REGEX,
            "manifest_sha256": sha256_file(tokenizer_manifest_path),
        },
        "inputs": {
            "common_manifest": {
                "path": str(common_manifest_path.resolve()),
                "sha256": sha256_file(common_manifest_path),
            },
            "common_events": {
                "path": str((common_root / "events.parquet").resolve()),
                "sha256": sha256_file(common_root / "events.parquet"),
            },
            "common_targets": {
                "path": str((common_root / "targets.parquet").resolve()),
                "sha256": sha256_file(common_root / "targets.parquet"),
            },
            "token_audit_manifest": {
                "path": str(token_audit_manifest_path.resolve()),
                "sha256": sha256_file(token_audit_manifest_path),
            },
            "token_audit": {
                "path": str(token_audit_parquet_path.resolve()),
                "sha256": sha256_file(token_audit_parquet_path),
            },
            "raw_source": common_manifest.get("lineage", {}),
        },
        "counts": {
            "targets": int(len(plan)),
            "selection_applied": int(plan["selection_applied"].sum()),
            "full_history_retained": int((~plan["selection_applied"]).sum()),
            "all_current_visit_events_retained": int(
                plan["all_current_visit_events_retained"].sum()
            ),
            "current_visit_events_partially_retained": int(
                (~plan["all_current_visit_events_retained"]).sum()
            ),
            "dropped_clinical_events": int(
                plan["dropped_clinical_event_count"].sum()
            ),
        },
        "selected_token_quantiles": {
            str(point): float(value)
            for point, value in plan["selected_token_count"]
            .quantile([0.0, 0.5, 0.9, 0.95, 0.99, 1.0])
            .items()
        },
        "model_weights_used": False,
        "encoder_run": False,
        "gpu_used": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    plan.to_parquet(output_root / "window_selection.parquet", index=False)
    write_json(output_root / "manifest.json", manifest)
    return manifest
