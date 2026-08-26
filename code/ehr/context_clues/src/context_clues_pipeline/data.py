"""Convert the project's structured EHR tables into Context Clues events.

The Stanford tokenizer does not understand local hospital identifiers.  Every
clinical concept therefore has to be mapped to an OMOP-standard code string
that occurs in the released tokenizer, for example ``SNOMED/44054006`` or
``LOINC/8480-6``.  This module deliberately keeps concept mapping separate from
event materialization so that mapping provenance can be audited.
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

REQUIRED_TABLES = (
    "visits",
    "diagnoses",
    "medicines",
    "procedures",
    "observations",
)

MAPPING_COLUMNS = (
    "source_table",
    "source_key",
    "source_code",
    "source_name",
    "event_count",
    "visit_count",
    "patient_count",
    "target_code",
    "mapping_status",
    "mapping_method",
    "use_value",
    "value_multiplier",
    "value_offset",
    "target_unit",
    "mapping_notes",
)

APPROVED_MAPPING_STATUSES = {"approved", "auto_approved"}
STANDARD_CODE_RE = re.compile(r"^[^/\s]+/.+$")


def _clean(value: Any) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()


def _normalized(value: Any) -> str:
    text = _clean(value).casefold()
    return re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()


def _string_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype="string")
    return frame[column].map(_clean).astype("string")


def _first_nonempty_series(*series: pd.Series) -> pd.Series:
    if not series:
        raise ValueError("At least one series is required")
    result = pd.Series("", index=series[0].index, dtype="string")
    for values in series:
        mask = result.eq("") & values.ne("")
        result.loc[mask] = values.loc[mask]
    return result


def _first_time(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    result = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    for column in columns:
        if column not in frame:
            continue
        values = pd.to_datetime(frame[column], errors="coerce")
        result = result.fillna(values)
    return result


def _make_source_keys(
    table: str,
    source_code: pd.Series,
    source_name: pd.Series,
) -> pd.Series:
    code_key = source_code.map(_normalized)
    name_key = source_name.map(_normalized)
    if table == "observations":
        # A local service code often denotes a panel, while the observation
        # name denotes an analyte.  Combining them prevents one panel code from
        # incorrectly mapping every component to the same LOINC concept.
        return pd.Series(
            [
                f"code_name:{code}|{name}" if code and name else
                f"code:{code}" if code else f"name:{name}"
                for code, name in zip(code_key, name_key)
            ],
            index=source_code.index,
            dtype="string",
        )
    return pd.Series(
        [f"code:{code}" if code else f"name:{name}" for code, name in zip(code_key, name_key)],
        index=source_code.index,
        dtype="string",
    )


def _require_columns(frame: pd.DataFrame, table: str, columns: set[str]) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{table}.parquet is missing required columns: {sorted(missing)}")


def _project_source_table(table: str, frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, table, {"patient_id", "visit_id"})

    if table == "diagnoses":
        source_code = _string_series(frame, "diagnosis_code")
        source_name = _string_series(frame, "diagnosis_text")
        source_event_id = _string_series(frame, "diagnosis_id")
        event_time = _first_time(frame, ("event_time",))
        omop_table = "condition_occurrence"
    elif table == "medicines":
        source_code = pd.Series("", index=frame.index, dtype="string")
        source_name = _first_nonempty_series(
            _string_series(frame, "active_ingredient"),
            _string_series(frame, "drug_name"),
        )
        source_event_id = _string_series(frame, "medicine_id")
        event_time = _first_time(frame, ("prescribed_time",))
        omop_table = "drug_exposure"
    elif table == "procedures":
        source_code = _string_series(frame, "service_code")
        source_name = _first_nonempty_series(
            _string_series(frame, "performed_name"),
            _string_series(frame, "procedure_name"),
        )
        source_event_id = _string_series(frame, "procedure_id")
        event_time = _first_time(frame, ("start_time", "ordered_time", "received_time"))
        omop_table = "procedure_occurrence"
    elif table == "observations":
        source_code = _string_series(frame, "service_code")
        source_name = _string_series(frame, "observation_name")
        source_event_id = _string_series(frame, "observation_id")
        event_time = _first_time(frame, ("observed_time",))
        omop_table = "measurement"
    else:
        raise ValueError(f"Unsupported source table: {table}")

    numeric = pd.to_numeric(
        frame["result_numeric"] if table == "observations" and "result_numeric" in frame
        else pd.Series(np.nan, index=frame.index),
        errors="coerce",
    )
    if table == "observations" and "result_type" in frame:
        # Only exact measurements are safe numeric inputs.  Censored, interval,
        # approximate and proxy values remain code-presence events.
        numeric = numeric.where(frame["result_type"].astype("string").eq("numeric_exact"))

    result = pd.DataFrame(
        {
            "patient_id": _string_series(frame, "patient_id"),
            "visit_id": _string_series(frame, "visit_id"),
            "source_table": table,
            "source_event_id": source_event_id,
            "source_code": source_code,
            "source_name": source_name,
            "event_time": event_time,
            "raw_numeric_value": numeric.astype(float),
            "raw_unit": _string_series(frame, "unit"),
            "omop_table": omop_table,
        }
    )
    result["source_key"] = _make_source_keys(table, source_code, source_name)
    result = result[
        result["patient_id"].ne("")
        & result["visit_id"].ne("")
        & ~result["source_key"].isin({"name:", "code:"})
    ].copy()
    return result


def load_source_events(input_root: Path) -> pd.DataFrame:
    """Load and project the four structured clinical event tables."""
    frames: list[pd.DataFrame] = []
    for table in REQUIRED_TABLES[1:]:
        path = input_root / f"{table}.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(_project_source_table(table, pd.read_parquet(path)))
    return pd.concat(frames, ignore_index=True)


def _read_mapping(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.casefold() == ".parquet":
        mapping = pd.read_parquet(path)
    elif path.suffix.casefold() == ".csv":
        mapping = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        raise ValueError("Concept map must be .csv or .parquet")
    required = {"source_table", "source_key", "target_code", "mapping_status"}
    _require_columns(mapping, path.name, required)
    for column in MAPPING_COLUMNS:
        if column not in mapping:
            mapping[column] = ""
    for column in mapping.columns:
        if column not in {"event_count", "visit_count", "patient_count", "value_multiplier", "value_offset"}:
            mapping[column] = mapping[column].map(_clean)
    mapping["source_table"] = mapping["source_table"].str.casefold()
    mapping["mapping_status"] = mapping["mapping_status"].str.casefold()
    return mapping


def build_concept_map_template(
    input_root: Path,
    output_path: Path,
    existing_map: Path | None = None,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Create one editable row per distinct local clinical concept."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing concept map: {output_path}")
    events = load_source_events(input_root)
    template = (
        events.groupby(["source_table", "source_key"], as_index=False, sort=False)
        .agg(
            source_code=("source_code", "first"),
            source_name=("source_name", "first"),
            event_count=("source_event_id", "size"),
            visit_count=("visit_id", "nunique"),
            patient_count=("patient_id", "nunique"),
        )
    )
    for column in MAPPING_COLUMNS[7:]:
        template[column] = ""
    template["value_multiplier"] = "1"
    template["value_offset"] = "0"

    if existing_map is not None:
        old = _read_mapping(existing_map)
        preserved = list(MAPPING_COLUMNS[7:])
        template = template.merge(
            old[["source_table", "source_key", *preserved]],
            on=["source_table", "source_key"],
            how="left",
            suffixes=("", "_old"),
            validate="one_to_one",
        )
        for column in preserved:
            old_column = f"{column}_old"
            template[column] = template[old_column].where(
                template[old_column].notna() & template[old_column].astype(str).ne(""),
                template[column],
            )
            template.drop(columns=old_column, inplace=True)

    template = template[list(MAPPING_COLUMNS)].sort_values(
        ["source_table", "event_count", "source_key"],
        ascending=[True, False, True],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.casefold() == ".parquet":
        template.to_parquet(output_path, index=False)
    elif output_path.suffix.casefold() == ".csv":
        template.to_csv(output_path, index=False)
    else:
        raise ValueError("Output concept map must be .csv or .parquet")
    return template


def _truthy(value: Any) -> bool:
    return _clean(value).casefold() in {"1", "true", "yes", "y"}


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _gender_token(value: Any) -> str:
    key = _normalized(value)
    if key in {"m", "male", "nam", "1"}:
        return "Gender/M"
    if key in {"f", "female", "nu", "nữ", "0", "2"}:
        return "Gender/F"
    return ""


def _stable_event_id(*parts: Any) -> str:
    payload = "\x1f".join(_clean(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_context_clues_events(
    input_root: Path,
    concept_map_path: Path,
    output_root: Path,
    visit_code: str = "Visit/IP",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Materialize mapped Context Clues events in a dedicated data folder."""
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_root}")
    if not STANDARD_CODE_RE.match(visit_code):
        raise ValueError(f"Invalid visit code: {visit_code!r}")

    visits_path = input_root / "visits.parquet"
    if not visits_path.exists():
        raise FileNotFoundError(visits_path)
    visits = pd.read_parquet(visits_path).copy()
    _require_columns(
        visits,
        "visits",
        {"patient_id", "visit_id", "admission_time", "discharge_time"},
    )
    visits["patient_id"] = _string_series(visits, "patient_id")
    visits["visit_id"] = _string_series(visits, "visit_id")
    visits["admission_time"] = pd.to_datetime(visits["admission_time"], errors="coerce")
    visits["discharge_time"] = pd.to_datetime(visits["discharge_time"], errors="coerce")
    if visits["visit_id"].eq("").any() or visits["patient_id"].eq("").any():
        raise ValueError("visits contains blank patient_id or visit_id")
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id must be unique")
    if visits["admission_time"].isna().any():
        raise ValueError("Every visit requires admission_time for chronological encoding")
    bad_ranges = visits["discharge_time"].notna() & (
        visits["discharge_time"] < visits["admission_time"]
    )
    if bad_ranges.any():
        raise ValueError(f"Found {int(bad_ranges.sum())} visits with discharge before admission")

    source = load_source_events(input_root)
    mapping = _read_mapping(concept_map_path)
    approved = mapping[mapping["mapping_status"].isin(APPROVED_MAPPING_STATUSES)].copy()
    invalid_codes = approved[~approved["target_code"].map(lambda x: bool(STANDARD_CODE_RE.match(x)))]
    if not invalid_codes.empty:
        sample = invalid_codes[["source_table", "source_key", "target_code"]].head(10)
        raise ValueError(f"Approved mappings contain invalid target_code values:\n{sample}")
    duplicated = approved.duplicated(["source_table", "source_key"], keep=False)
    if duplicated.any():
        raise ValueError("Approved concept map has duplicate source_table/source_key rows")

    mapped = source.merge(
        approved[
            [
                "source_table", "source_key", "target_code", "mapping_status",
                "mapping_method", "use_value", "value_multiplier", "value_offset",
                "target_unit", "mapping_notes",
            ]
        ],
        on=["source_table", "source_key"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    mapped_mask = mapped["_merge"].eq("both") & mapped["target_code"].fillna("").ne("")

    admission_lookup = visits.set_index("visit_id")["admission_time"]
    clinical = mapped[mapped_mask].copy()
    clinical["start"] = clinical["event_time"].fillna(clinical["visit_id"].map(admission_lookup))
    clinical["end"] = pd.NaT
    clinical["code"] = clinical["target_code"]
    clinical["unit"] = clinical["target_unit"].fillna("").map(_clean)

    values: list[float] = []
    for row in clinical.itertuples(index=False):
        value = float("nan")
        if _truthy(row.use_value) and pd.notna(row.raw_numeric_value):
            multiplier = _number(row.value_multiplier, 1.0)
            offset = _number(row.value_offset, 0.0)
            value = float(row.raw_numeric_value) * multiplier + offset
        values.append(value)
    clinical["value"] = values
    clinical["event_priority"] = clinical["source_table"].map(
        {"diagnoses": 20, "medicines": 30, "procedures": 40, "observations": 50}
    ).fillna(90).astype(int)
    clinical["event_id"] = [
        _stable_event_id(row.source_table, row.source_event_id, row.code)
        for row in clinical.itertuples(index=False)
    ]

    visit_events = pd.DataFrame(
        {
            "event_id": [_stable_event_id("visit", value, visit_code) for value in visits["visit_id"]],
            "patient_id": visits["patient_id"],
            "visit_id": visits["visit_id"],
            "source_table": "visits",
            "source_event_id": visits["visit_id"],
            "code": visit_code,
            "value": np.nan,
            "unit": "",
            "start": visits["admission_time"],
            "end": visits["discharge_time"],
            "omop_table": "visit_occurrence",
            "event_priority": 10,
        }
    )

    demographic_rows: list[dict[str, Any]] = []
    for patient_id, group in visits.groupby("patient_id", sort=False):
        first = group.sort_values("admission_time").iloc[0]
        birth_year = pd.to_numeric(first.get("birth_year", pd.NA), errors="coerce")
        if pd.notna(birth_year) and 1900 <= int(birth_year) <= 2100:
            start = pd.Timestamp(year=int(birth_year), month=1, day=1)
            demographic_rows.append(
                {
                    "event_id": _stable_event_id("demographic", patient_id, "birth"),
                    "patient_id": patient_id,
                    "visit_id": "",
                    "source_table": "demographics",
                    "source_event_id": "birth_year",
                    "code": "SNOMED/3950001",
                    "value": np.nan,
                    "unit": "",
                    "start": start,
                    "end": pd.NaT,
                    "omop_table": "person",
                    "event_priority": 0,
                }
            )
        gender = _gender_token(first.get("gender_code", ""))
        if gender:
            demographic_rows.append(
                {
                    "event_id": _stable_event_id("demographic", patient_id, "gender"),
                    "patient_id": patient_id,
                    "visit_id": "",
                    "source_table": "demographics",
                    "source_event_id": "gender_code",
                    "code": gender,
                    "value": np.nan,
                    "unit": "",
                    "start": first["admission_time"],
                    "end": pd.NaT,
                    "omop_table": "person",
                    "event_priority": 1,
                }
            )
    demographics = pd.DataFrame(demographic_rows, columns=visit_events.columns)

    event_columns = list(visit_events.columns)
    events = pd.concat(
        [demographics, visit_events, clinical[event_columns]],
        ignore_index=True,
    )
    events["start"] = pd.to_datetime(events["start"], errors="coerce")
    events["end"] = pd.to_datetime(events["end"], errors="coerce")
    events.sort_values(
        ["patient_id", "start", "event_priority", "event_id"],
        na_position="last",
        inplace=True,
        ignore_index=True,
    )

    concept_template = (
        source.groupby(["source_table", "source_key"], as_index=False)
        .agg(
            source_code=("source_code", "first"),
            source_name=("source_name", "first"),
            event_count=("source_event_id", "size"),
            visit_count=("visit_id", "nunique"),
            patient_count=("patient_id", "nunique"),
        )
    )
    concept_snapshot = concept_template.merge(
        mapping[list(MAPPING_COLUMNS[0:2]) + list(MAPPING_COLUMNS[7:])],
        on=["source_table", "source_key"],
        how="left",
        validate="one_to_one",
    )
    concept_snapshot["is_approved"] = (
        concept_snapshot["mapping_status"].fillna("").str.casefold().isin(APPROVED_MAPPING_STATUSES)
        & concept_snapshot["target_code"].fillna("").ne("")
    )
    unmapped = concept_snapshot[~concept_snapshot["is_approved"]].copy()

    table_audit_rows: list[dict[str, Any]] = []
    for table, group in mapped.groupby("source_table", sort=True):
        is_mapped = group["_merge"].eq("both") & group["target_code"].fillna("").ne("")
        table_audit_rows.append(
            {
                "source_table": table,
                "source_event_count": len(group),
                "mapped_event_count": int(is_mapped.sum()),
                "event_mapping_coverage": float(is_mapped.mean()) if len(group) else 0.0,
                "source_concept_count": int(group["source_key"].nunique()),
                "mapped_concept_count": int(group.loc[is_mapped, "source_key"].nunique()),
            }
        )
    mapping_audit = pd.DataFrame(table_audit_rows)
    total_source = len(mapped)
    total_mapped = int(mapped_mask.sum())
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "input_root": str(input_root.resolve()),
        "concept_map": str(concept_map_path.resolve()),
        "visit_code": visit_code,
        "counts": {
            "patients": int(visits["patient_id"].nunique()),
            "visits": int(visits["visit_id"].nunique()),
            "source_clinical_events": total_source,
            "mapped_clinical_events": total_mapped,
            "prepared_events": len(events),
            "approved_concepts": int(concept_snapshot["is_approved"].sum()),
            "unmapped_concepts": int((~concept_snapshot["is_approved"]).sum()),
        },
        "event_mapping_coverage": float(total_mapped / total_source) if total_source else 0.0,
        "numeric_policy": "Only approved exact observations with use_value=true; otherwise code presence",
        "clinical_notes_included": False,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    events.to_parquet(output_root / "events.parquet", index=False)
    visits.to_parquet(output_root / "visits.parquet", index=False)
    concept_snapshot.to_parquet(output_root / "concept_map_snapshot.parquet", index=False)
    unmapped.to_parquet(output_root / "unmapped_concepts.parquet", index=False)
    mapping_audit.to_parquet(output_root / "mapping_audit.parquet", index=False)
    _write_json(output_root / "manifest.json", manifest)
    return manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _concept_template_from_events(source: pd.DataFrame) -> pd.DataFrame:
    template = (
        source.groupby(["source_table", "source_key"], as_index=False, sort=False)
        .agg(
            source_code=("source_code", "first"),
            source_name=("source_name", "first"),
            event_count=("source_event_id", "size"),
            visit_count=("visit_id", "nunique"),
            patient_count=("patient_id", "nunique"),
        )
    )
    for column in MAPPING_COLUMNS[7:]:
        template[column] = ""
    template["value_multiplier"] = "1"
    template["value_offset"] = "0"
    return template[list(MAPPING_COLUMNS)].sort_values(
        ["source_table", "event_count", "source_key"],
        ascending=[True, False, True],
    )


def _source_handoff_markdown(manifest: dict[str, Any], output_root: Path) -> str:
    counts = manifest["counts"]
    table_lines = "\n".join(
        f"- `{row['source_table']}`: {row['events']:,} events, "
        f"{row['concepts']:,} local concepts"
        for row in manifest["table_summary"]
    )
    return f"""# Context Clues encoder handoff

Data-only preprocessing is complete. No model weights were downloaded and no
encoder inference was run.

## Dataset

- Patients: **{counts['patients']:,}**
- Visits: **{counts['visits']:,}**
- Structured clinical events: **{counts['source_events']:,}**
- Local concepts requiring mapping/review: **{counts['local_concepts']:,}**
- Events available by their visit discharge: **{counts['available_by_discharge']:,}**
- Events after their visit discharge: **{counts['after_discharge']:,}**
- Events with imputed time (admission fallback): **{counts['time_imputed']:,}**

{table_lines}

## Files

- `{output_root / 'source_events.parquet'}`: one normalized row per structured
  clinical event, sorted chronologically within patient.
- `{output_root / 'visits.parquet'}`: the 3,500 target visits and cutoff times.
- `{output_root / 'visit_event_audit.parquet'}`: event/time counts per visit.
- `{output_root / 'source_table_audit.parquet'}`: aggregate quality audit.
- `{output_root / 'concept_map.csv'}`: one row per local concept. This must be
  mapped to a code present in the released Context Clues tokenizer.
- `{output_root / 'concept_mapping_worklist.csv'}`: the practical mapping set:
  all code-bearing diagnoses plus every medication, observation and procedure
  concept. It contains {counts['mapping_worklist_concepts']:,} concepts covering
  {counts['mapping_worklist_event_coverage']:.2%} of source events; text-only
  diagnosis phrases remain preserved in the full map.
- `{output_root / 'manifest.json'}`: fingerprints, counts, schema and policies.

`source_events.parquet` deliberately preserves local `source_code`,
`source_name` and `source_key`. It does **not** pretend local hospital concepts
are OMOP concepts. A frozen Context Clues checkpoint has no learned embedding
for an unknown local code, so feeding this file directly before mapping would
silently discard most events.

## Temporal policy

- `effective_time = event_time` when available.
- Missing diagnosis time uses the visit `admission_time` and sets
  `time_imputed=true`.
- `temporal_status` records `before_admission`, `within_visit`, or
  `after_discharge`.
- For a target visit embedding at discharge, retain only rows satisfying
  `effective_time <= target discharge_time`. The supplied encoder pipeline does
  this cutoff per target visit; it never consumes future events.

## Finish mapping before encoder inference

Edit `concept_map.csv`:

1. Set `target_code` to the exact model vocabulary form, such as
   `SNOMED/...`, `LOINC/...`, `RxNorm/...`, or `CPT4/...`.
2. Set `mapping_status=approved` only after terminology/clinical review.
3. For exact numerical labs, set `use_value=true` only after unit and scale
   harmonization; otherwise the event is encoded as code presence.

Then materialize encoder-ready events:

```bash
PY=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
PIPE=/mnt/disk4/similar_cases_retrieval/code/code/ehr/context_clues
INPUT={manifest['input_root']}
SOURCE={output_root}
PIPELINE_ROOT={output_root.parent}

$PY $PIPE/prepare_events.py \\
  --input-root $INPUT \\
  --concept-map $SOURCE/concept_map.csv \\
  --output-root $PIPELINE_ROOT/prepared
```

After gated-model access and GPU space are available, place Hugging Face cache
on disk4 (disk1 is full) and run:

```bash
export HF_HOME=/mnt/disk4/similar_cases_retrieval/data/ehr/context_clues/hf_cache
export PYTHONPATH=/mnt/disk4/similar_cases_retrieval/data/ehr/context_clues/runtime/python_packages

$PY $PIPE/embed_visits.py \\
  --prepared-root $PIPELINE_ROOT/prepared \\
  --output-root /mnt/disk4/similar_cases_retrieval/data/ehr/context_clues/embeddings/gpt-base-4096-clmbr \\
  --model StanfordShahLab/gpt-base-4096-clmbr \\
  --timeline-mode history \\
  --max-length 4096
```

Expected final matrix: one 768-dimensional row per visit, shape `[3500, 768]`.
"""


def prepare_source_event_dataset(
    input_root: Path,
    output_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Materialize all model-independent structured EHR preprocessing.

    This stage intentionally stops before terminology mapping and tokenization.
    It is safe to run without the gated checkpoint and preserves every source
    event needed for a later reviewed mapping pass.
    """
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_root}")

    visits_path = input_root / "visits.parquet"
    if not visits_path.exists():
        raise FileNotFoundError(visits_path)
    visits = pd.read_parquet(visits_path).copy()
    _require_columns(
        visits,
        "visits",
        {"patient_id", "visit_id", "admission_time", "discharge_time"},
    )
    visits["patient_id"] = _string_series(visits, "patient_id")
    visits["visit_id"] = _string_series(visits, "visit_id")
    visits["admission_time"] = pd.to_datetime(visits["admission_time"], errors="coerce")
    visits["discharge_time"] = pd.to_datetime(visits["discharge_time"], errors="coerce")
    if visits["patient_id"].eq("").any() or visits["visit_id"].eq("").any():
        raise ValueError("visits contains blank patient_id or visit_id")
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id must be unique")
    if visits[["admission_time", "discharge_time"]].isna().any().any():
        raise ValueError("Every visit requires admission_time and discharge_time")
    invalid_range = visits["discharge_time"] < visits["admission_time"]
    if invalid_range.any():
        raise ValueError(f"Found {int(invalid_range.sum())} visits with discharge before admission")

    source = load_source_events(input_root)
    visit_times = visits[
        ["patient_id", "visit_id", "admission_time", "discharge_time"]
    ]
    source = source.merge(
        visit_times,
        on=["patient_id", "visit_id"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    if not source["_merge"].eq("both").all():
        raise ValueError("At least one source event does not resolve to a visit")
    source.drop(columns="_merge", inplace=True)
    source["event_time"] = pd.to_datetime(source["event_time"], errors="coerce")
    source["time_imputed"] = source["event_time"].isna()
    source["effective_time"] = source["event_time"].fillna(source["admission_time"])
    source["time_source"] = np.where(
        source["time_imputed"], "admission_fallback", "source_event_time"
    )
    source["temporal_status"] = np.select(
        [
            source["effective_time"] < source["admission_time"],
            source["effective_time"] > source["discharge_time"],
        ],
        ["before_admission", "after_discharge"],
        default="within_visit",
    )
    source["available_by_discharge"] = source["effective_time"] <= source["discharge_time"]
    source["event_priority"] = source["source_table"].map(
        {"diagnoses": 20, "medicines": 30, "procedures": 40, "observations": 50}
    ).astype("int16")
    source["event_id"] = [
        _stable_event_id(row.source_table, row.source_event_id, row.source_key)
        for row in source.itertuples(index=False)
    ]
    if source["event_id"].duplicated().any():
        duplicated = int(source["event_id"].duplicated(keep=False).sum())
        raise ValueError(f"Generated {duplicated} duplicate event_id rows")
    source.sort_values(
        ["patient_id", "effective_time", "event_priority", "event_id"],
        inplace=True,
        ignore_index=True,
    )
    source["event_order_within_patient"] = (
        source.groupby("patient_id", sort=False).cumcount().astype("int32")
    )
    source["event_order_within_visit"] = (
        source.groupby("visit_id", sort=False).cumcount().astype("int32")
    )

    concept_map = _concept_template_from_events(source)
    worklist_mask = concept_map["source_table"].ne("diagnoses") | concept_map[
        "source_code"
    ].ne("")
    concept_worklist = concept_map[worklist_mask].copy()
    concept_worklist.insert(
        7,
        "mapping_scope_reason",
        np.where(
            concept_worklist["source_table"].eq("diagnoses"),
            "coded_diagnosis",
            "structured_non_diagnosis",
        ),
    )
    concept_worklist["cumulative_table_event_coverage"] = (
        concept_worklist.groupby("source_table", sort=False)["event_count"].cumsum()
        / concept_worklist.groupby("source_table", sort=False)["event_count"].transform("sum")
    )
    table_audit = (
        source.groupby("source_table", as_index=False, sort=True)
        .agg(
            events=("event_id", "size"),
            concepts=("source_key", "nunique"),
            visits=("visit_id", "nunique"),
            patients=("patient_id", "nunique"),
            time_imputed=("time_imputed", "sum"),
            available_by_discharge=("available_by_discharge", "sum"),
        )
    )
    temporal_counts = (
        source.groupby(["source_table", "temporal_status"]).size().unstack(fill_value=0)
    )
    table_audit = table_audit.merge(
        temporal_counts.reset_index(), on="source_table", how="left"
    )

    per_visit_total = (
        source.groupby(["patient_id", "visit_id"], as_index=False)
        .agg(
            source_event_count=("event_id", "size"),
            available_by_discharge_count=("available_by_discharge", "sum"),
            time_imputed_count=("time_imputed", "sum"),
        )
    )
    per_visit_table = (
        source.groupby(["patient_id", "visit_id", "source_table"])
        .size()
        .unstack(fill_value=0)
        .add_suffix("_count")
        .reset_index()
    )
    visit_audit = visits[["patient_id", "visit_id", "admission_time", "discharge_time"]]
    visit_audit = visit_audit.merge(
        per_visit_total,
        on=["patient_id", "visit_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        per_visit_table,
        on=["patient_id", "visit_id"],
        how="left",
        validate="one_to_one",
    )
    count_columns = [column for column in visit_audit if column.endswith("_count")]
    visit_audit[count_columns] = visit_audit[count_columns].fillna(0).astype("int64")

    input_files = [input_root / f"{table}.parquet" for table in REQUIRED_TABLES]
    table_summary = [
        {
            "source_table": str(row.source_table),
            "events": int(row.events),
            "concepts": int(row.concepts),
        }
        for row in table_audit.itertuples(index=False)
    ]
    counts = {
        "patients": int(visits["patient_id"].nunique()),
        "visits": int(visits["visit_id"].nunique()),
        "source_events": len(source),
        "local_concepts": len(concept_map),
        "available_by_discharge": int(source["available_by_discharge"].sum()),
        "after_discharge": int(source["temporal_status"].eq("after_discharge").sum()),
        "time_imputed": int(source["time_imputed"].sum()),
        "mapping_worklist_concepts": len(concept_worklist),
        "mapping_worklist_event_coverage": float(
            concept_worklist["event_count"].sum() / len(source)
        ),
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "stage": "model_independent_source_events",
        "input_root": str(input_root.resolve()),
        "output_root": str(output_root.resolve()),
        "counts": counts,
        "table_summary": table_summary,
        "input_fingerprints": {
            path.name: {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}
            for path in input_files
        },
        "event_order": [
            "patient_id",
            "effective_time",
            "event_priority",
            "event_id",
        ],
        "time_policy": {
            "missing_event_time": "admission_time fallback",
            "future_filter_for_target_visit": "effective_time <= target discharge_time",
        },
        "numeric_policy": "Preserve exact result_numeric only; mapping/unit review happens later",
        "clinical_notes_included": False,
        "encoder_run": False,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    source.to_parquet(output_root / "source_events.parquet", index=False)
    visits.to_parquet(output_root / "visits.parquet", index=False)
    concept_map.to_csv(output_root / "concept_map.csv", index=False)
    concept_worklist.to_csv(output_root / "concept_mapping_worklist.csv", index=False)
    table_audit.to_parquet(output_root / "source_table_audit.parquet", index=False)
    visit_audit.to_parquet(output_root / "visit_event_audit.parquet", index=False)
    _write_json(output_root / "manifest.json", manifest)
    (output_root / "ENCODER_HANDOFF.md").write_text(
        _source_handoff_markdown(manifest, output_root), encoding="utf-8"
    )
    return manifest
