"""Build Context Clues inputs directly from the raw EHR workbook.

The EHR-graph pipeline also parses this workbook, but its materialized data is
not an input here. This module reuses the shared parsing code while writing a
new, independently fingerprinted dataset under the Context Clues data root.
Clinical notes and graph tables are never built.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .data import prepare_source_event_dataset


STRUCTURED_TABLES = (
    "visits",
    "diagnoses",
    "medicines",
    "procedures",
    "observations",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _load_raw_builders(preprocessing_root: Path) -> tuple[Any, Any]:
    """Load raw-workbook parser code without consuming its data outputs."""
    preprocessing_root = preprocessing_root.resolve()
    required = (
        preprocessing_root / "preprocess_ehr_tables.py",
        preprocessing_root / "preprocess_ehr_tables_v2.py",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing raw EHR preprocessing code: {missing}")
    root_text = str(preprocessing_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    v1 = importlib.import_module("preprocess_ehr_tables")
    v2 = importlib.import_module("preprocess_ehr_tables_v2")

    # Match semantic-v2 parsing while calling only the five structured builders.
    v1.clean = v2.clean
    v1.clean_key = v2.clean_key
    v1.normalized = v2.normalized
    v1.parse_time = v2.parse_time
    v1.clean_frame_columns = lambda frame, fields: [
        frame.__setitem__(field, frame[field].map(v2.clean))
        for field in fields
        if field in frame.columns
    ]
    return v1, v2


def validate_structured_tables(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    missing = set(STRUCTURED_TABLES) - set(tables)
    if missing:
        raise ValueError(f"Missing Context Clues structured tables: {sorted(missing)}")
    visits = tables["visits"]
    required_visit_columns = {
        "patient_id",
        "visit_id",
        "admission_time",
        "discharge_time",
    }
    missing_visit_columns = required_visit_columns - set(visits.columns)
    if missing_visit_columns:
        raise ValueError(f"visits missing columns: {sorted(missing_visit_columns)}")
    if visits["patient_id"].astype("string").fillna("").eq("").any():
        raise ValueError("visits contains blank patient_id")
    if visits["visit_id"].astype("string").fillna("").eq("").any():
        raise ValueError("visits contains blank visit_id")
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id must be unique")
    admission = pd.to_datetime(visits["admission_time"], errors="coerce")
    discharge = pd.to_datetime(visits["discharge_time"], errors="coerce")
    if admission.isna().any() or discharge.isna().any():
        raise ValueError("Every visit requires admission_time and discharge_time")
    if (discharge < admission).any():
        raise ValueError("At least one visit has discharge_time before admission_time")

    known = set(zip(visits["patient_id"].astype(str), visits["visit_id"].astype(str)))
    audit: dict[str, Any] = {
        "patients": int(visits["patient_id"].nunique()),
        "visits": int(visits["visit_id"].nunique()),
        "tables": {},
        "clinical_notes_built": False,
        "graph_tables_built": False,
    }
    forbidden_columns = {"clinical_note", "note_text"}
    for name in STRUCTURED_TABLES[1:]:
        frame = tables[name]
        if not {"patient_id", "visit_id"}.issubset(frame.columns):
            raise ValueError(f"{name} is missing patient_id/visit_id")
        leaked = forbidden_columns & set(frame.columns)
        if leaked:
            raise ValueError(f"{name} unexpectedly contains note columns: {sorted(leaked)}")
        keys = set(zip(frame["patient_id"].astype(str), frame["visit_id"].astype(str)))
        orphan_count = len(keys - known)
        if orphan_count:
            raise ValueError(f"{name} contains {orphan_count} orphan visit keys")
        audit["tables"][name] = {
            "rows": int(len(frame)),
            "visits": int(frame["visit_id"].nunique()),
            "orphan_visit_keys": orphan_count,
        }
    return audit


def build_structured_tables_from_raw(
    workbook_path: Path,
    preprocessing_root: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Read raw XLSX sheets and build only the five structured EHR tables."""
    if not workbook_path.exists():
        raise FileNotFoundError(workbook_path)
    v1, v2 = _load_raw_builders(preprocessing_root)
    frames = v1.read_workbook(workbook_path)
    visits, visit_to_patient = v1.build_visits(frames)
    visits["admission_time"] = v2.parse_time(frames["visits"]["NgayVaoVien"])
    visits["discharge_time"] = v2.parse_time(frames["visits"]["NgayRaVien"])
    diagnoses = v1.build_diagnoses(frames, visit_to_patient)
    medicines = v1.build_medicines(frames, visit_to_patient)
    procedures = v1.build_procedures(frames, visit_to_patient)
    medicines, procedures = v2._enrich_canonical_tables(medicines, procedures)
    observations = v2.build_observations_v2(frames, visit_to_patient)
    tables = {
        "visits": visits,
        "diagnoses": diagnoses,
        "medicines": medicines,
        "procedures": procedures,
        "observations": observations,
    }
    sheet_rows = {name: int(len(frame)) for name, frame in frames.items()}
    return tables, sheet_rows


def prepare_raw_workbook_dataset(
    workbook_path: Path,
    output_root: Path,
    preprocessing_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run raw XLSX -> isolated structured tables -> source event inventory."""
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_root}")

    structured_root = output_root / "structured"
    source_root = output_root / "source_prepared"
    tables, sheet_rows = build_structured_tables_from_raw(
        workbook_path=workbook_path,
        preprocessing_root=preprocessing_root,
    )
    quality = validate_structured_tables(tables)
    structured_root.mkdir(parents=True, exist_ok=True)
    for name in STRUCTURED_TABLES:
        tables[name].to_parquet(structured_root / f"{name}.parquet", index=False)

    raw_sha256 = _sha256_file(workbook_path)
    structured_manifest: dict[str, Any] = {
        "schema_version": 1,
        "stage": "raw_xlsx_to_context_clues_structured_tables",
        "source_type": "raw_xlsx",
        "source_workbook": str(workbook_path.resolve()),
        "source_sha256": raw_sha256,
        "preprocessing_code_root": str(preprocessing_root.resolve()),
        "sheet_rows": sheet_rows,
        "quality": quality,
        "outputs": {name: f"{name}.parquet" for name in STRUCTURED_TABLES},
        "clinical_notes_included": False,
        "graph_tables_included": False,
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__},
    }
    _write_json(structured_root / "manifest.json", structured_manifest)

    source_manifest = prepare_source_event_dataset(
        input_root=structured_root,
        output_root=source_root,
        overwrite=overwrite,
    )
    source_manifest["lineage"] = {
        "source_type": "raw_xlsx",
        "source_workbook": str(workbook_path.resolve()),
        "source_sha256": raw_sha256,
        "structured_root": str(structured_root.resolve()),
        "structured_manifest": str((structured_root / "manifest.json").resolve()),
        "consumed_existing_ehr_preprocessed_snapshot": False,
    }
    _write_json(source_root / "manifest.json", source_manifest)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "pipeline": "context_clues_raw_data_only",
        "source_type": "raw_xlsx",
        "source_workbook": str(workbook_path.resolve()),
        "source_sha256": raw_sha256,
        "structured_root": str(structured_root.resolve()),
        "source_prepared_root": str(source_root.resolve()),
        "counts": source_manifest["counts"],
        "encoder_run": False,
        "model_weights_used": False,
        "gpu_used": False,
    }
    _write_json(output_root / "manifest.json", manifest)
    return manifest
