"""SMB-v1-1.7B adapter over the shared MEDS-compatible event store."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .common import write_json


MEDS_COLUMNS = ("subject_id", "time", "code", "table", "numeric_value", "text_value", "unit")
SMB_UTILS_REVISION = "4f963e124a940c2ddbc10f50a7448a6e20654555"
SMB_MODEL_ID = "standardmodelbio/SMB-v1_Qwen3-1.7b_multi-objective"
SMB_MODEL_REVISION = "81a889a17c84160eaab4c975c70e451482bc9e56"
SMB_MAX_SEQUENCE_LENGTH = 3300


def validate_common_input(events: pd.DataFrame, targets: pd.DataFrame) -> None:
    required_events = set(MEDS_COLUMNS) | {
        "patient_id",
        "visit_id",
        "event_id",
        "event_priority",
        "source_table",
    }
    missing_events = required_events - set(events.columns)
    missing_targets = {"patient_id", "visit_id", "cutoff_time", "target_order"} - set(targets.columns)
    if missing_events:
        raise ValueError(f"events missing columns: {sorted(missing_events)}")
    if missing_targets:
        raise ValueError(f"targets missing columns: {sorted(missing_targets)}")
    if events["event_id"].duplicated().any():
        raise ValueError("events contains duplicate event_id")
    if targets["visit_id"].duplicated().any():
        raise ValueError("targets contains duplicate visit_id")
    if targets["target_order"].duplicated().any():
        raise ValueError("targets contains duplicate target_order")


def build_target_meds(events: pd.DataFrame, target: pd.Series | Any) -> pd.DataFrame:
    """Select one leakage-safe patient history without materializing copies."""
    patient_id = str(target.patient_id if hasattr(target, "patient_id") else target["patient_id"])
    visit_id = str(target.visit_id if hasattr(target, "visit_id") else target["visit_id"])
    cutoff_value = target.cutoff_time if hasattr(target, "cutoff_time") else target["cutoff_time"]
    cutoff = pd.Timestamp(cutoff_value)
    if pd.isna(cutoff):
        raise ValueError(f"Target {visit_id} has no cutoff_time")
    selected = events[
        events["patient_id"].astype(str).eq(patient_id)
        & (pd.to_datetime(events["time"], errors="coerce") <= cutoff)
    ].copy()
    selected.sort_values(["time", "event_priority", "event_id"], inplace=True)
    return selected


def group_events_by_patient(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    prepared = events.copy()
    prepared["patient_id"] = prepared["patient_id"].astype(str)
    prepared["time"] = pd.to_datetime(prepared["time"], errors="coerce")
    if prepared["time"].isna().any():
        raise ValueError("events contains missing or invalid time")
    return {
        str(patient_id): group.sort_values(["time", "event_priority", "event_id"])
        for patient_id, group in prepared.groupby("patient_id", sort=False)
    }


def build_smb_preflight(events: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    validate_common_input(events, targets)
    patient_events = group_events_by_patient(events)
    rows: list[dict[str, Any]] = []
    for target in targets.sort_values("target_order").itertuples(index=False):
        selected = build_target_meds(patient_events.get(str(target.patient_id), events.iloc[0:0]), target)
        clinical = selected[selected["source_table"].ne("demographics")]
        current = clinical[clinical["visit_id"].astype(str).eq(str(target.visit_id))]
        rows.append(
            {
                "target_order": int(target.target_order),
                "patient_id": str(target.patient_id),
                "visit_id": str(target.visit_id),
                "cutoff_time": pd.Timestamp(target.cutoff_time),
                "history_event_count": int(len(selected)),
                "history_clinical_event_count": int(len(clinical)),
                "current_visit_event_count": int(len(current)),
                "history_visit_count": int(clinical["visit_id"].nunique()),
                "has_current_visit_event": bool(len(current) > 0),
                "earliest_event_time": selected["time"].min() if len(selected) else pd.NaT,
                "latest_event_time": selected["time"].max() if len(selected) else pd.NaT,
            }
        )
    return pd.DataFrame(rows)


def audit_smb_serialization(
    events: pd.DataFrame,
    targets: pd.DataFrame,
    formatter: Callable[..., str],
    output_root: Path,
    overwrite: bool = False,
    max_targets: int | None = None,
) -> dict[str, Any]:
    """Run the official serializer and store only non-clinical audit metadata."""
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_root}")
    validate_common_input(events, targets)
    ordered = targets.sort_values("target_order")
    if max_targets is not None:
        ordered = ordered.head(max_targets)
    patient_events = group_events_by_patient(events)
    rows: list[dict[str, Any]] = []
    for target in ordered.itertuples(index=False):
        selected = build_target_meds(patient_events.get(str(target.patient_id), events.iloc[0:0]), target)
        text = formatter(
            selected[list(MEDS_COLUMNS)],
            subject_id=str(target.patient_id),
            code_column="code",
            category_column="table",
            end_time=pd.Timestamp(target.cutoff_time),
            include_demographics=True,
        )
        if not isinstance(text, str):
            raise TypeError("SMB EHR formatter must return str when include_imaging=False")
        rows.append(
            {
                "target_order": int(target.target_order),
                "patient_id": str(target.patient_id),
                "visit_id": str(target.visit_id),
                "cutoff_time": pd.Timestamp(target.cutoff_time),
                "selected_event_count": int(len(selected)),
                "serialized_char_count": len(text),
                "serialized_line_count": len(text.splitlines()),
                "serialization_nonempty": bool(text.strip()),
                "serialized_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    audit = pd.DataFrame(rows)
    manifest = {
        "schema_version": 1,
        "stage": "smb_official_serialization_audit",
        "smb_utils_revision": SMB_UTILS_REVISION,
        "counts": {
            "targets": int(len(audit)),
            "nonempty_serializations": int(audit["serialization_nonempty"].sum()),
            "empty_serializations": int((~audit["serialization_nonempty"]).sum()),
        },
        "serialized_text_persisted": False,
        "tokenization_run": False,
        "model_weights_used": False,
        "encoder_run": False,
        "gpu_used": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    audit.to_parquet(output_root / "serialization_audit.parquet", index=False)
    write_json(output_root / "manifest.json", manifest)
    return manifest
