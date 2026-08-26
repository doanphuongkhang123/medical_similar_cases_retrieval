"""Build a model-neutral event store that is also MEDS-compatible for SMB.

The common table deliberately retains local concepts and provenance. Only
diagnosis codes originating from the workbook's ICD fields and matching an
ICD-10 shape are namespaced as ICD10. Other domains use human-readable local
labels until a reviewed terminology mapping becomes available.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STRUCTURED_TABLES = (
    "visits",
    "diagnoses",
    "medicines",
    "procedures",
    "observations",
)

EVENT_TABLES = STRUCTURED_TABLES[1:]
ICD10_RE = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?$", re.IGNORECASE)
EVENT_PRIORITY = {
    "demographics": 0,
    "diagnoses": 20,
    "medicines": 30,
    "procedures": 40,
    "observations": 50,
}
TABLE_BY_SOURCE = {
    "diagnoses": "condition_occurrence",
    "medicines": "drug_exposure",
    "procedures": "procedure_occurrence",
    "observations": "measurement",
}


def clean(value: Any) -> str:
    """Normalize one scalar without collapsing distinct clinical concepts."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()
    return "" if text.casefold() in {"", "null", "none", "nan", "nat", "not available"} else text


def normalized(value: Any) -> str:
    return re.sub(r"[\W_]+", " ", clean(value).casefold(), flags=re.UNICODE).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join(clean(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _strings(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype="string")
    return frame[column].map(clean).astype("string")


def _first_nonempty(*series: pd.Series) -> pd.Series:
    if not series:
        raise ValueError("At least one series is required")
    output = pd.Series("", index=series[0].index, dtype="string")
    for values in series:
        mask = output.eq("") & values.ne("")
        output.loc[mask] = values.loc[mask]
    return output


def _first_time(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    output = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    for column in columns:
        if column in frame:
            output = output.fillna(pd.to_datetime(frame[column], errors="coerce"))
    return output


def _require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")


def validate_structured_tables(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Validate the isolated five-table dataset before materialization."""
    missing_tables = set(STRUCTURED_TABLES) - set(tables)
    if missing_tables:
        raise ValueError(f"Missing structured tables: {sorted(missing_tables)}")

    visits = tables["visits"]
    _require_columns(
        visits,
        "visits",
        {"patient_id", "visit_id", "admission_time", "discharge_time"},
    )
    patient_ids = _strings(visits, "patient_id")
    visit_ids = _strings(visits, "visit_id")
    admission = pd.to_datetime(visits["admission_time"], errors="coerce")
    discharge = pd.to_datetime(visits["discharge_time"], errors="coerce")
    if patient_ids.eq("").any() or visit_ids.eq("").any():
        raise ValueError("visits contains blank patient_id or visit_id")
    if visit_ids.duplicated().any():
        raise ValueError("visit_id must be unique")
    if admission.isna().any() or discharge.isna().any():
        raise ValueError("Every visit requires admission_time and discharge_time")
    if (discharge < admission).any():
        raise ValueError("At least one visit has discharge_time before admission_time")

    known = set(zip(patient_ids.astype(str), visit_ids.astype(str)))
    table_quality: dict[str, Any] = {}
    for name in EVENT_TABLES:
        frame = tables[name]
        _require_columns(frame, name, {"patient_id", "visit_id"})
        keys = set(zip(_strings(frame, "patient_id").astype(str), _strings(frame, "visit_id").astype(str)))
        orphan_count = len(keys - known)
        if orphan_count:
            raise ValueError(f"{name} contains {orphan_count} orphan visit keys")
        if {"clinical_note", "note_text"} & set(frame.columns):
            raise ValueError(f"{name} unexpectedly contains clinical-note columns")
        table_quality[name] = {
            "rows": int(len(frame)),
            "visits": int(frame["visit_id"].nunique()),
            "orphan_visit_keys": orphan_count,
        }
    return {
        "patients": int(patient_ids.nunique()),
        "visits": int(visit_ids.nunique()),
        "tables": table_quality,
        "clinical_notes_built": False,
        "graph_tables_built": False,
    }


def _source_key(table: str, code: pd.Series, name: pd.Series) -> pd.Series:
    code_key = code.map(normalized)
    name_key = name.map(normalized)
    if table == "observations":
        return pd.Series(
            [
                f"code_name:{c}|{n}" if c and n else f"code:{c}" if c else f"name:{n}"
                for c, n in zip(code_key, name_key)
            ],
            index=code.index,
            dtype="string",
        )
    return pd.Series(
        [f"code:{c}" if c else f"name:{n}" for c, n in zip(code_key, name_key)],
        index=code.index,
        dtype="string",
    )


def _observation_values(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    result_type = _strings(frame, "result_type")
    numeric = pd.to_numeric(
        frame["result_numeric"] if "result_numeric" in frame else pd.Series(np.nan, index=frame.index),
        errors="coerce",
    ).astype(float)
    numeric = numeric.where(result_type.isin({"numeric_exact", "numeric_with_unit"}))
    finite = numeric.isna() | np.isfinite(numeric)
    if not finite.all():
        raise ValueError(f"observations contains {int((~finite).sum())} non-finite numeric values")

    raw = _strings(frame, "result_raw")
    category = _strings(frame, "result_category")
    text = pd.Series(pd.NA, index=frame.index, dtype="string")
    categorical = result_type.isin({"categorical", "semi_quantitative"})
    text.loc[categorical] = category.where(category.ne(""), raw).loc[categorical]
    qualified_numeric = result_type.isin({"numeric_censored", "numeric_interval", "numeric_approx"})
    text.loc[qualified_numeric] = raw.loc[qualified_numeric].replace("", pd.NA)
    return numeric, text, result_type


def _project_clinical_table(table: str, frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, table, {"patient_id", "visit_id"})
    if table == "diagnoses":
        source_code = _strings(frame, "diagnosis_code")
        source_name = _strings(frame, "diagnosis_text")
        source_event_id = _strings(frame, "diagnosis_id")
        event_time = _first_time(frame, ("event_time",))
        numeric = pd.Series(np.nan, index=frame.index, dtype=float)
        text_value = pd.Series(pd.NA, index=frame.index, dtype="string")
        result_type = pd.Series("code_presence", index=frame.index, dtype="string")
        unit = pd.Series("", index=frame.index, dtype="string")
    elif table == "medicines":
        source_code = pd.Series("", index=frame.index, dtype="string")
        source_name = _first_nonempty(_strings(frame, "active_ingredient"), _strings(frame, "drug_name"))
        source_event_id = _strings(frame, "medicine_id")
        event_time = _first_time(frame, ("prescribed_time",))
        numeric = pd.Series(np.nan, index=frame.index, dtype=float)
        text_value = pd.Series(pd.NA, index=frame.index, dtype="string")
        result_type = pd.Series("code_presence", index=frame.index, dtype="string")
        unit = _strings(frame, "unit")
    elif table == "procedures":
        source_code = _strings(frame, "service_code")
        source_name = _first_nonempty(_strings(frame, "performed_name"), _strings(frame, "procedure_name"))
        source_event_id = _strings(frame, "procedure_id")
        event_time = _first_time(frame, ("start_time", "ordered_time", "received_time"))
        numeric = pd.Series(np.nan, index=frame.index, dtype=float)
        text_value = pd.Series(pd.NA, index=frame.index, dtype="string")
        result_type = pd.Series("code_presence", index=frame.index, dtype="string")
        unit = pd.Series("", index=frame.index, dtype="string")
    elif table == "observations":
        source_code = _strings(frame, "service_code")
        source_name = _strings(frame, "observation_name")
        source_event_id = _strings(frame, "observation_id")
        event_time = _first_time(frame, ("observed_time",))
        numeric, text_value, result_type = _observation_values(frame)
        unit = _first_nonempty(_strings(frame, "unit"), _strings(frame, "value_unit"))
    else:
        raise ValueError(f"Unsupported source table: {table}")

    source_key = _source_key(table, source_code, source_name)
    if table == "diagnoses":
        icd = source_code.str.upper().str.replace(" ", "", regex=False)
        is_icd = icd.map(lambda value: bool(ICD10_RE.fullmatch(value)))
        fallback = source_name.where(source_name.ne(""), source_code)
        smb_code = fallback.copy()
        smb_code.loc[is_icd] = "ICD10:" + icd.loc[is_icd]
        standard_system = pd.Series("", index=frame.index, dtype="string")
        standard_code = pd.Series("", index=frame.index, dtype="string")
        standard_system.loc[is_icd] = "ICD10"
        standard_code.loc[is_icd] = icd.loc[is_icd]
        code_strategy = pd.Series("local_label_fallback", index=frame.index, dtype="string")
        code_strategy.loc[is_icd] = "source_icd_field_regex"
    else:
        smb_code = source_name.where(source_name.ne(""), source_code)
        standard_system = pd.Series("", index=frame.index, dtype="string")
        standard_code = pd.Series("", index=frame.index, dtype="string")
        code_strategy = pd.Series("local_label_fallback", index=frame.index, dtype="string")

    output = pd.DataFrame(
        {
            "patient_id": _strings(frame, "patient_id"),
            "visit_id": _strings(frame, "visit_id"),
            "source_table": table,
            "source_event_id": source_event_id,
            "source_key": source_key,
            "source_code": source_code,
            "source_name": source_name,
            "event_time": event_time,
            "result_type": result_type,
            "standard_system": standard_system,
            "standard_code": standard_code,
            "code_strategy": code_strategy,
            "subject_id": _strings(frame, "patient_id"),
            "time": event_time,
            "code": smb_code.map(clean).astype("string"),
            "table": TABLE_BY_SOURCE[table],
            "numeric_value": numeric,
            "text_value": text_value,
            "unit": unit,
            "event_priority": EVENT_PRIORITY[table],
        }
    )
    output = output[
        output["patient_id"].ne("")
        & output["visit_id"].ne("")
        & output["code"].ne("")
        & ~output["source_key"].isin({"name:", "code:"})
    ].copy()
    output["event_id"] = [
        _stable_id("event", row.source_table, row.source_event_id, row.source_key)
        for row in output.itertuples(index=False)
    ]
    return output


def _demographic_events(visits: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ordered = visits.sort_values(["patient_id", "admission_time", "visit_id"])
    for patient_id, group in ordered.groupby("patient_id", sort=False):
        first = group.iloc[0]
        birth_year = pd.to_numeric(first.get("birth_year", pd.NA), errors="coerce")
        if pd.notna(birth_year) and 1900 <= int(birth_year) <= 2100:
            time = pd.Timestamp(year=int(birth_year), month=1, day=1)
            rows.append(_demographic_row(str(patient_id), "birth_year", "Birth", time, pd.NA))
        gender_key = normalized(first.get("gender_code", ""))
        gender = "Male" if gender_key in {"m", "male", "nam", "1"} else "Female" if gender_key in {"f", "female", "nu", "nữ", "0", "2"} else ""
        if gender:
            rows.append(
                _demographic_row(
                    str(patient_id), "gender", "Gender", pd.Timestamp(first["admission_time"]), gender
                )
            )
    columns = [
        "patient_id", "visit_id", "source_table", "source_event_id", "source_key",
        "source_code", "source_name", "event_time", "result_type", "standard_system",
        "standard_code", "code_strategy", "subject_id", "time", "code", "table",
        "numeric_value", "text_value", "unit", "event_priority", "event_id",
    ]
    return pd.DataFrame(rows, columns=columns)


def _demographic_row(
    patient_id: str,
    event_name: str,
    code: str,
    time: pd.Timestamp,
    text_value: Any,
) -> dict[str, Any]:
    return {
        "patient_id": patient_id,
        "visit_id": "",
        "source_table": "demographics",
        "source_event_id": event_name,
        "source_key": f"demographic:{event_name}",
        "source_code": "",
        "source_name": code,
        "event_time": time,
        "result_type": "demographic",
        "standard_system": "",
        "standard_code": "",
        "code_strategy": "derived_demographic",
        "subject_id": patient_id,
        "time": time,
        "code": code,
        "table": "person",
        "numeric_value": np.nan,
        "text_value": text_value,
        "unit": "",
        "event_priority": EVENT_PRIORITY["demographics"],
        "event_id": _stable_id("demographic", patient_id, event_name),
    }


def _targets(visits: pd.DataFrame) -> pd.DataFrame:
    targets = visits[["patient_id", "visit_id", "admission_time", "discharge_time"]].copy()
    targets.sort_values(["patient_id", "admission_time", "visit_id"], inplace=True)
    targets["target_order"] = np.arange(len(targets), dtype=np.int32)
    targets["visit_ordinal"] = targets.groupby("patient_id", sort=False).cumcount().add(1).astype("int16")
    targets["cutoff_time"] = targets["discharge_time"]
    return targets.reset_index(drop=True)


def _concept_inventory(clinical: pd.DataFrame) -> pd.DataFrame:
    inventory = (
        clinical.groupby(["source_table", "source_key"], as_index=False, sort=False)
        .agg(
            source_code=("source_code", "first"),
            source_name=("source_name", "first"),
            default_smb_code=("code", "first"),
            code_strategy=("code_strategy", "first"),
            standard_system=("standard_system", "first"),
            standard_code=("standard_code", "first"),
            event_count=("event_id", "size"),
            visit_count=("visit_id", "nunique"),
            patient_count=("patient_id", "nunique"),
        )
        .sort_values(["source_table", "event_count", "source_key"], ascending=[True, False, True])
        .reset_index(drop=True)
    )
    return inventory


def build_common_dataset(
    tables: dict[str, pd.DataFrame],
    output_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write common events, targets, terminology inventory and audits."""
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_root}")
    quality = validate_structured_tables(tables)
    visits = tables["visits"].copy()
    visits["patient_id"] = _strings(visits, "patient_id")
    visits["visit_id"] = _strings(visits, "visit_id")
    visits["admission_time"] = pd.to_datetime(visits["admission_time"], errors="coerce")
    visits["discharge_time"] = pd.to_datetime(visits["discharge_time"], errors="coerce")

    clinical = pd.concat(
        [_project_clinical_table(name, tables[name]) for name in EVENT_TABLES],
        ignore_index=True,
    )
    visit_times = visits[["patient_id", "visit_id", "admission_time", "discharge_time"]]
    clinical = clinical.merge(
        visit_times,
        on=["patient_id", "visit_id"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    if not clinical["_merge"].eq("both").all():
        raise ValueError("At least one event does not resolve to a visit")
    clinical.drop(columns="_merge", inplace=True)
    clinical["time_imputed"] = clinical["time"].isna()
    clinical["time"] = clinical["time"].fillna(clinical["admission_time"])
    clinical["effective_time"] = clinical["time"]
    clinical["temporal_status"] = np.select(
        [clinical["time"] < clinical["admission_time"], clinical["time"] > clinical["discharge_time"]],
        ["before_admission", "after_discharge"],
        default="within_visit",
    )
    clinical["available_by_discharge"] = clinical["time"] <= clinical["discharge_time"]
    demographics = _demographic_events(visits)
    for column in ("admission_time", "discharge_time"):
        demographics[column] = pd.NaT
    demographics["time_imputed"] = False
    demographics["effective_time"] = demographics["time"]
    demographics["temporal_status"] = "demographic"
    demographics["available_by_discharge"] = True

    event_columns = list(clinical.columns)
    events = pd.concat([demographics.reindex(columns=event_columns), clinical], ignore_index=True)
    events.sort_values(["patient_id", "time", "event_priority", "event_id"], inplace=True, ignore_index=True)
    if events["event_id"].duplicated().any():
        raise ValueError("event_id must be globally unique")
    if events["time"].isna().any():
        raise ValueError("Every common event requires a time")
    events["event_order_within_patient"] = events.groupby("patient_id", sort=False).cumcount().astype("int32")

    targets = _targets(visits)
    inventory = _concept_inventory(clinical)
    mappings = inventory[
        ["source_table", "source_key", "source_code", "source_name", "default_smb_code", "event_count", "visit_count", "patient_count"]
    ].copy()
    mappings["target_system"] = ""
    mappings["target_code"] = ""
    mappings["mapping_status"] = "pending_review"
    mappings["mapping_method"] = ""
    mappings["mapping_version"] = ""
    mappings["mapping_notes"] = ""

    table_audit = (
        clinical.groupby("source_table", as_index=False, sort=True)
        .agg(
            events=("event_id", "size"),
            concepts=("source_key", "nunique"),
            patients=("patient_id", "nunique"),
            visits=("visit_id", "nunique"),
            numeric_values=("numeric_value", lambda values: int(values.notna().sum())),
            text_values=("text_value", lambda values: int(values.notna().sum())),
            time_imputed=("time_imputed", "sum"),
            available_by_discharge=("available_by_discharge", "sum"),
        )
    )
    counts = {
        "patients": int(targets["patient_id"].nunique()),
        "target_visits": int(len(targets)),
        "clinical_events": int(len(clinical)),
        "demographic_events": int(len(demographics)),
        "common_events": int(len(events)),
        "local_concepts": int(len(inventory)),
        "non_null_numeric_values": int(events["numeric_value"].notna().sum()),
        "non_null_text_values": int(events["text_value"].notna().sum()),
        "time_imputed": int(clinical["time_imputed"].sum()),
        "after_discharge": int(clinical["temporal_status"].eq("after_discharge").sum()),
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "stage": "common_structured_ehr_events",
        "counts": counts,
        "quality": quality,
        "meds_contract": {
            "columns": ["subject_id", "time", "code", "table", "numeric_value", "text_value", "unit"],
            "category_values": sorted(events["table"].unique().tolist()),
            "one_physical_event_table": True,
        },
        "target_policy": {
            "retrieval_unit": "visit_id",
            "cutoff": "target visit discharge_time",
            "history": "same patient events with time <= cutoff_time",
        },
        "terminology_policy": {
            "diagnoses": "ICD10 namespace only for source ICD-field values matching ICD10 shape; otherwise local label",
            "other_domains": "local human-readable label until reviewed mapping",
            "automatic_fuzzy_mapping": False,
        },
        "numeric_policy": "Only finite numeric_exact/numeric_with_unit observations become numeric_value; qualified values stay text",
        "clinical_notes_included": False,
        "encoder_run": False,
        "model_weights_used": False,
        "gpu_used": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    events.to_parquet(output_root / "events.parquet", index=False)
    targets.to_parquet(output_root / "targets.parquet", index=False)
    inventory.to_parquet(output_root / "concept_inventory.parquet", index=False)
    mappings.to_csv(output_root / "concept_mappings.csv", index=False)
    table_audit.to_parquet(output_root / "table_audit.parquet", index=False)
    write_json(output_root / "manifest.json", manifest)
    return manifest
