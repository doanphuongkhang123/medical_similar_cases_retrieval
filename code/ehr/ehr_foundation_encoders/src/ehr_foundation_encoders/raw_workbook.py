"""Raw workbook entry point for the SMB data-only pipeline."""
from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .common import (
    STRUCTURED_TABLES,
    build_common_dataset,
    sha256_file,
    validate_structured_tables,
    write_json,
)
from .smb import (
    SMB_MODEL_ID,
    SMB_MODEL_REVISION,
    SMB_UTILS_REVISION,
    build_smb_preflight,
)


def _load_raw_builders(preprocessing_root: Path) -> tuple[Any, Any]:
    preprocessing_root = preprocessing_root.resolve()
    required = (
        preprocessing_root / "preprocess_ehr_tables.py",
        preprocessing_root / "preprocess_ehr_tables_v2.py",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing raw EHR preprocessing code: {missing}")
    if str(preprocessing_root) not in sys.path:
        sys.path.insert(0, str(preprocessing_root))
    v1 = importlib.import_module("preprocess_ehr_tables")
    v2 = importlib.import_module("preprocess_ehr_tables_v2")
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


def build_structured_tables_from_raw(
    workbook_path: Path,
    preprocessing_root: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
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
    return tables, {name: int(len(frame)) for name, frame in frames.items()}


def prepare_smb_raw_dataset(
    workbook_path: Path,
    output_root: Path,
    preprocessing_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run raw XLSX -> isolated structured tables -> common MEDS -> SMB audit."""
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_root}")
    tables, sheet_rows = build_structured_tables_from_raw(workbook_path, preprocessing_root)
    quality = validate_structured_tables(tables)
    raw_sha256 = sha256_file(workbook_path)

    structured_root = output_root / "structured"
    common_root = output_root / "common"
    adapter_root = output_root / "adapters" / "smb_v1_1_7b"
    structured_root.mkdir(parents=True, exist_ok=True)
    for name in STRUCTURED_TABLES:
        tables[name].to_parquet(structured_root / f"{name}.parquet", index=False)
    structured_manifest = {
        "schema_version": 1,
        "stage": "raw_xlsx_to_structured_ehr_tables",
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
    write_json(structured_root / "manifest.json", structured_manifest)

    common_manifest = build_common_dataset(tables, common_root, overwrite=overwrite)
    common_manifest["lineage"] = {
        "source_type": "raw_xlsx",
        "source_workbook": str(workbook_path.resolve()),
        "source_sha256": raw_sha256,
        "structured_root": str(structured_root.resolve()),
        "consumed_existing_derived_dataset": False,
    }
    write_json(common_root / "manifest.json", common_manifest)

    events = pd.read_parquet(common_root / "events.parquet")
    targets = pd.read_parquet(common_root / "targets.parquet")
    preflight = build_smb_preflight(events, targets)
    adapter_root.mkdir(parents=True, exist_ok=True)
    preflight.to_parquet(adapter_root / "target_preflight.parquet", index=False)
    adapter_manifest = {
        "schema_version": 1,
        "stage": "smb_meds_adapter_preflight",
        "model": SMB_MODEL_ID,
        "model_revision": SMB_MODEL_REVISION,
        "common_events": str((common_root / "events.parquet").resolve()),
        "common_targets": str((common_root / "targets.parquet").resolve()),
        "smb_utils_revision": SMB_UTILS_REVISION,
        "counts": {
            "targets": int(len(preflight)),
            "targets_with_current_visit_events": int(preflight["has_current_visit_event"].sum()),
            "targets_without_current_visit_events": int((~preflight["has_current_visit_event"]).sum()),
        },
        "serialized_text_persisted": False,
        "tokenization_run": False,
        "model_weights_used": False,
        "encoder_run": False,
        "gpu_used": False,
    }
    write_json(adapter_root / "manifest.json", adapter_manifest)

    root_manifest = {
        "schema_version": 1,
        "pipeline": "ehr_foundation_encoders_smb_data_only",
        "source_type": "raw_xlsx",
        "source_workbook": str(workbook_path.resolve()),
        "source_sha256": raw_sha256,
        "structured_root": str(structured_root.resolve()),
        "common_root": str(common_root.resolve()),
        "smb_adapter_root": str(adapter_root.resolve()),
        "counts": common_manifest["counts"],
        "encoder_run": False,
        "model_weights_used": False,
        "gpu_used": False,
    }
    write_json(output_root / "manifest.json", root_manifest)
    return root_manifest
