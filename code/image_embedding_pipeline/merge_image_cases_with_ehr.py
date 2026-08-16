#!/usr/bin/env python3
"""Link patient-level image embeddings to visit-level EHR records.

Only an image whose DICOM study date falls inside exactly one EHR visit is
attached to that visit.  Unmatched and ambiguous rows remain in the audit
outputs; they are never assigned heuristically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


IMAGE_MODALITIES = ("CT", "MRI", "XQ")
MATCHED_STATUS = "matched_unique_visit_interval"
CODE_VERSION = "ehr-image-visit-link-v1"


def _sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _parse_study_date(value: Any) -> pd.Timestamp | None:
    raw = str(value or "").strip()
    if len(raw) < 8:
        return None
    parsed = pd.to_datetime(raw[:8], format="%Y%m%d", errors="coerce")
    return None if pd.isna(parsed) else parsed.normalize()


def match_study_date_to_visit(
    study_date: pd.Timestamp,
    visits: Iterable[dict[str, Any]],
) -> tuple[str, str]:
    """Return ``(visit_id, status)`` using an exact visit-interval match."""
    hits: list[str] = []
    for visit in visits:
        admission = visit.get("admission_time")
        if admission is None or pd.isna(admission):
            continue
        start = pd.Timestamp(admission).normalize()
        discharge = visit.get("discharge_time")
        end = start if discharge is None or pd.isna(discharge) else pd.Timestamp(discharge).normalize()
        if start <= study_date <= end:
            hits.append(_clean_id(visit.get("visit_id")))
    hits = sorted({visit_id for visit_id in hits if visit_id})
    if len(hits) == 1:
        return hits[0], MATCHED_STATUS
    if len(hits) > 1:
        return "", "ambiguous_overlapping_visit_intervals"
    return "", "no_visit_on_study_date"


def _inspect_vector(path: Path) -> tuple[int, str, bool, str]:
    try:
        vector = np.load(path, allow_pickle=False)
    except Exception as exc:  # keep the row in the audit table
        return 0, "", False, f"{type(exc).__name__}: {exc}"
    if vector.ndim != 1:
        return int(vector.size), str(vector.dtype), False, f"expected 1-D, got {vector.shape}"
    if not np.isfinite(vector).all():
        return int(vector.shape[0]), str(vector.dtype), False, "contains NaN or Inf"
    if float(np.linalg.norm(vector)) == 0.0:
        return int(vector.shape[0]), str(vector.dtype), False, "zero-norm vector"
    return int(vector.shape[0]), str(vector.dtype), True, ""


def _load_patient_modality(
    image_data_root: Path,
    patient_id: str,
    modality: str,
) -> dict[str, Any]:
    metadata_path = image_data_root / f"organized_{modality}" / patient_id / "metadata.json"
    embedding_dir = image_data_root / "embeddings" / patient_id / modality
    result: dict[str, Any] = {
        "patient_id": patient_id,
        "modality": modality,
        "metadata_status": "ok",
        "embedding_dir_status": "ok",
        "vectors": [],
    }
    if not metadata_path.is_file():
        result["metadata_status"] = "missing"
        return result
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["metadata_status"] = f"error:{type(exc).__name__}"
        return result

    suffix_to_dates: dict[str, set[str]] = defaultdict(set)
    for study in _as_records(metadata.get("studies")):
        study_date = str(study.get("study_date") or "").strip()
        for series in _as_records(study.get("series")):
            series_uid = str(series.get("series_instance_uid") or "").strip()
            if series_uid:
                suffix_to_dates[series_uid[-16:]].add(study_date)

    if not embedding_dir.is_dir():
        result["embedding_dir_status"] = "missing"
        return result

    for embedding_path in sorted(embedding_dir.glob("*.npy")):
        dates = sorted(suffix_to_dates.get(embedding_path.stem, set()))
        dim, dtype, valid, error = _inspect_vector(embedding_path)
        result["vectors"].append(
            {
                "embedding_path": str(embedding_path.resolve()),
                "embedding_relative_path": str(embedding_path.relative_to(image_data_root)),
                "series_uid_suffix": embedding_path.stem,
                "study_date_raw": dates[0] if len(dates) == 1 else "",
                "series_date_match_count": len(dates),
                "embedding_dim": dim,
                "embedding_dtype": dtype,
                "embedding_valid": valid,
                "embedding_error": error,
            }
        )
    return result


def _case_status(row: pd.Series) -> str:
    if row["image_embedding_count"] == 0:
        return "no_image_embedding"
    if row["ehr_visit_count"] == 0:
        return "patient_not_in_ehr"
    if row["matched_image_embedding_count"] == 0:
        return "no_image_embedding_matched_to_visit"
    if row["unmatched_image_embedding_count"] > 0:
        return "partially_matched"
    if row["mapped_visit_count"] == 1:
        return "matched_one_visit"
    return "matched_multiple_visits"


def build_outputs(
    image_manifest: Path,
    image_data_root: Path,
    ehr_visits_path: Path,
    output_dir: Path,
    workers: int,
) -> dict[str, Any]:
    manifest_rows = json.loads(image_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest_rows, list):
        raise ValueError("image manifest must contain a JSON list")
    patient_ids = [_clean_id(row.get("patient_id")) for row in manifest_rows]
    if not all(patient_ids):
        raise ValueError("every image-manifest row must have patient_id")
    if len(patient_ids) != len(set(patient_ids)):
        raise ValueError("patient_id must be unique in the image manifest")

    visits = pd.read_parquet(ehr_visits_path)
    required = {"patient_id", "visit_id", "admission_time", "discharge_time"}
    missing = required - set(visits.columns)
    if missing:
        raise ValueError(f"EHR visits missing columns: {sorted(missing)}")
    visits = visits.copy()
    visits["patient_id"] = visits["patient_id"].map(_clean_id)
    visits["visit_id"] = visits["visit_id"].map(_clean_id)
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id is not unique in the EHR visits table")
    visits_by_patient = {
        patient_id: group.to_dict("records")
        for patient_id, group in visits.groupby("patient_id", sort=False)
    }

    tasks = [
        (image_data_root, patient_id, modality)
        for row, patient_id in zip(manifest_rows, patient_ids)
        for modality in IMAGE_MODALITIES
        if modality in row.get("modalities", [])
    ]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        modality_results = list(executor.map(lambda args: _load_patient_modality(*args), tasks))

    metadata_missing: dict[str, list[str]] = defaultdict(list)
    embedding_dir_missing: dict[str, list[str]] = defaultdict(list)
    link_rows: list[dict[str, Any]] = []
    for result in modality_results:
        patient_id = result["patient_id"]
        modality = result["modality"]
        if result["metadata_status"] != "ok":
            metadata_missing[patient_id].append(modality)
        if result["embedding_dir_status"] != "ok":
            embedding_dir_missing[patient_id].append(modality)
        for vector in result["vectors"]:
            visit_id = ""
            if not vector["embedding_valid"]:
                join_status = "invalid_embedding"
            elif vector["series_date_match_count"] == 0:
                join_status = "series_not_found_in_metadata"
            elif vector["series_date_match_count"] > 1:
                join_status = "ambiguous_series_uid_suffix"
            else:
                study_date = _parse_study_date(vector["study_date_raw"])
                if study_date is None:
                    join_status = "invalid_or_missing_study_date"
                elif patient_id not in visits_by_patient:
                    join_status = "patient_not_in_ehr"
                else:
                    visit_id, join_status = match_study_date_to_visit(
                        study_date, visits_by_patient[patient_id]
                    )
            link_rows.append(
                {
                    "patient_id": patient_id,
                    "visit_id": visit_id,
                    "modality": modality,
                    **vector,
                    "join_status": join_status,
                }
            )

    links = pd.DataFrame(link_rows)
    if links.empty:
        raise ValueError("no image embeddings were found")
    links = links.sort_values(
        ["patient_id", "visit_id", "modality", "embedding_relative_path"],
        kind="stable",
    ).reset_index(drop=True)
    matched = links[links["join_status"] == MATCHED_STATUS].copy()

    case_rows: list[dict[str, Any]] = []
    for original, patient_id in zip(manifest_rows, patient_ids):
        patient_links = links[links["patient_id"] == patient_id]
        patient_matched = patient_links[patient_links["join_status"] == MATCHED_STATUS]
        mapped_visit_ids = sorted(patient_matched["visit_id"].unique().tolist())
        case_rows.append(
            {
                "patient_id": patient_id,
                "modalities": list(original.get("modalities", [])),
                "selection_reason": original.get("selection_reason"),
                "is_normal": original.get("is_normal"),
                "matched_phrase": original.get("matched_phrase"),
                "ehr_visit_count": len(visits_by_patient.get(patient_id, [])),
                "image_embedding_count": len(patient_links),
                "matched_image_embedding_count": len(patient_matched),
                "unmatched_image_embedding_count": len(patient_links) - len(patient_matched),
                "mapped_visit_ids": mapped_visit_ids,
                "mapped_visit_count": len(mapped_visit_ids),
                "metadata_missing_modalities": sorted(metadata_missing.get(patient_id, [])),
                "embedding_dir_missing_modalities": sorted(embedding_dir_missing.get(patient_id, [])),
            }
        )
    cases = pd.DataFrame(case_rows)
    cases["join_status"] = cases.apply(_case_status, axis=1)

    visit_image_rows: list[dict[str, Any]] = []
    for visit_id, group in matched.groupby("visit_id", sort=True):
        row: dict[str, Any] = {
            "visit_id": visit_id,
            "image_embedding_count": len(group),
            "image_modalities": sorted(group["modality"].unique().tolist()),
            "image_embedding_paths": group["embedding_path"].tolist(),
            "image_embedding_dims": group["embedding_dim"].astype(int).tolist(),
            "image_study_dates": group["study_date_raw"].tolist(),
        }
        for modality in IMAGE_MODALITIES:
            selected = group[group["modality"] == modality]
            row[f"{modality.lower()}_embedding_paths"] = selected["embedding_path"].tolist()
            row[f"{modality.lower()}_embedding_count"] = len(selected)
        visit_image_rows.append(row)
    visit_images = pd.DataFrame(visit_image_rows)
    retrieval_v2 = visits.merge(visit_images, on="visit_id", how="inner", validate="one_to_one")
    retrieval_v2 = retrieval_v2.sort_values("visit_id", kind="stable").reset_index(drop=True)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    try:
        paths = {
            "case_join_audit": temp_dir / "case_join_audit.parquet",
            "image_embedding_links": temp_dir / "image_embedding_links.parquet",
            "retrieval_v2_visits": temp_dir / "retrieval_v2_visits.parquet",
        }
        cases.to_parquet(paths["case_join_audit"], index=False)
        links.to_parquet(paths["image_embedding_links"], index=False)
        retrieval_v2.to_parquet(paths["retrieval_v2_visits"], index=False)

        report: dict[str, Any] = {
            "code_version": CODE_VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "join_policy": (
                "patient_id exact match; DICOM study_date must fall inside exactly one "
                "inclusive EHR admission_time/discharge_time interval"
            ),
            "sources": {
                "image_manifest": str(image_manifest),
                "image_manifest_sha256": _sha256(image_manifest),
                "image_data_root": str(image_data_root),
                "ehr_visits": str(ehr_visits_path),
                "ehr_visits_sha256": _sha256(ehr_visits_path),
            },
            "counts": {
                "image_manifest_cases": len(cases),
                "image_embedding_rows": len(links),
                "matched_image_embedding_rows": len(matched),
                "unmatched_image_embedding_rows": len(links) - len(matched),
                "retrieval_v2_visits": len(retrieval_v2),
                "retrieval_v2_patients": int(retrieval_v2["patient_id"].nunique()),
            },
            "case_join_status_counts": cases["join_status"].value_counts().sort_index().to_dict(),
            "embedding_join_status_counts": links["join_status"].value_counts().sort_index().to_dict(),
            "embedding_shape_counts": {
                f"{modality}:{int(dim)}": int(count)
                for (modality, dim), count in links.groupby(["modality", "embedding_dim"]).size().items()
            },
            "outputs": {},
        }
        for name, path in paths.items():
            report["outputs"][path.name] = {
                "rows": int({
                    "case_join_audit": len(cases),
                    "image_embedding_links": len(links),
                    "retrieval_v2_visits": len(retrieval_v2),
                }[name]),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        manifest_out = temp_dir / "manifest.json"
        manifest_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_dir, output_dir)
    except Exception:
        # Leave the uniquely named temporary directory for forensic inspection.
        raise
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image-manifest",
        type=Path,
        default=Path(
            "/mnt/disk4/namtn/similar_case_retrieval/building_verify_app/code/sample_manifest.json"
        ),
    )
    parser.add_argument(
        "--image-data-root",
        type=Path,
        default=Path("/mnt/disk4/namtn/similar_case_retrieval/building_verify_app/data"),
    )
    parser.add_argument(
        "--ehr-visits",
        type=Path,
        default=Path(
            "/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/"
            "ehr_preprocessed_full/visits.parquet"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/mnt/disk4/similar_cases_retrieval/data/retrieval_v2_image_1000"),
    )
    parser.add_argument("--workers", type=int, default=32)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_outputs(
        image_manifest=args.image_manifest.resolve(),
        image_data_root=args.image_data_root.resolve(),
        ehr_visits_path=args.ehr_visits.resolve(),
        output_dir=args.output_dir.resolve(),
        workers=args.workers,
    )
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
