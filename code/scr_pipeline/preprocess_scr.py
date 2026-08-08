#!/usr/bin/env python3
"""Prepare MIMIC-IV text + laboratory-event inputs for SCR.

The unit of one example is one hospital admission (``hadm_id``).  Clinical
text is reduced to sections available at admission, following the public
CliniBench preprocessing idea.  Laboratory events are restricted to a
configurable window after ``admittime`` (24 hours by default), and are kept as
an irregular event sequence rather than being silently resampled.

The script is deliberately based on DuckDB and PyArrow instead of pandas so
that the same command can run on the small local samples and on the much
larger CSV/CSV.GZ files on the server.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


LOG = logging.getLogger("scr_preprocess")

SECTION_NAMES: Sequence[Tuple[str, Sequence[str]]] = (
    ("chief_complaint", ("Chief Complaint",)),
    ("history_of_present_illness", ("History of Present Illness", "HPI")),
    ("past_medical_history", ("Past Medical History", "PMH")),
    ("medications_on_admission", ("Medications on Admission", "Medication on Admission")),
    ("allergies", ("Allergies",)),
    ("physical_exam", ("Physical Exam",)),
    ("family_history", ("Family History",)),
    ("social_history", ("Social History",)),
)

# These are the sections that CliniBench treats as admission-time information.
IMPORTANT_SECTIONS = {"chief_complaint", "history_of_present_illness", "past_medical_history"}


def sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def find_file(root: Path, *names: str) -> Path:
    candidates: List[Path] = []
    for name in names:
        path = root / name
        candidates.extend([path, Path(str(path) + ".gz")])
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("Could not find any of: " + ", ".join(str(p) for p in candidates))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mimic-iv", type=Path, required=True,
                        help="MIMIC-IV root containing hosp/ and optionally icu/.")
    parser.add_argument("--notes", type=Path, required=True,
                        help="MIMIC-IV-Note root or its note/ directory.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory for SCR-ready files.")
    parser.add_argument("--lab-window-hours", type=float, default=24.0,
                        help="Keep labs in [admittime, admittime + N hours]. Default: 24.")
    parser.add_argument("--min-lab-count", type=int, default=5,
                        help="Minimum train-event count for a lab item to receive a vocabulary id.")
    parser.add_argument("--max-events", type=int, default=512,
                        help="Maximum events stored in each padded-ready sequence. Raw events are retained.")
    parser.add_argument("--seed", type=int, default=42,
                        help="Seed used for deterministic subject-level train/val/test assignment.")
    parser.add_argument("--limit-notes", type=int, default=0,
                        help="Optional input-note limit for local smoke tests; 0 means all.")
    parser.add_argument("--keep-intermediate", action="store_true",
                        help="Keep the cleaned per-note intermediate parquet file.")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING"))
    return parser.parse_args()


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def fix_anonymization(text: str) -> str:
    replacements = (
        (r"___\s*\nFamily History:", "___\n\nFamily History:"),
        (r"\n\s*\n___ Complaint:\n", "\n\nChief Complaint:\n"),
        (r"\n\s*\nPhysical ___:\n", "\n\nPhysical Exam:\n"),
        (r"\n\s*\n___ on Admission:\n", "\n\nMedication on Admission:\n"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def section_body(text: str, aliases: Sequence[str]) -> str:
    """Extract one section until the next blank-line-delimited heading."""
    aliases_pattern = "|".join(re.escape(alias) for alias in aliases)
    # MIMIC discharge notes conventionally use a blank line before headings.
    pattern = rf"(?ims)(?:^|\n\s*\n)(?:{aliases_pattern}):\s*(.*?)(?=\n\s*\n[^\n:]+:\s*|\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def remove_late_physical_exam(text: str) -> str:
    # Physical Exam occasionally contains a later "Discharge ...:" heading.
    return re.split(r"(?im)(?:^|\n).*discharge.*:\s*", text, maxsplit=1)[0].strip()


def extract_admission_text(raw_text: Optional[str]) -> str:
    """Return a section-labelled admission-only text, or an empty string."""
    text = fix_anonymization(normalize_text(raw_text))
    if not text:
        return ""
    pieces: List[str] = []
    for key, aliases in SECTION_NAMES:
        body = section_body(text, aliases)
        if key == "physical_exam":
            body = remove_late_physical_exam(body)
        if body:
            pieces.append(f"## {key.upper()}\n{body}")
    # Match CliniBench's guard against notes without meaningful admission data.
    if not any(piece.startswith("## " + key.upper()) for piece in pieces for key in IMPORTANT_SECTIONS):
        return ""
    return "\n\n".join(pieces).strip()


def arrow_schema() -> pa.Schema:
    return pa.schema([
        ("note_id", pa.string()),
        ("subject_id", pa.string()),
        ("hadm_id", pa.string()),
        ("note_seq", pa.int64()),
        ("storetime", pa.string()),
        ("admission_note", pa.string()),
    ])


def iter_note_batches(con: duckdb.DuckDBPyConnection, note_path: Path, limit: int) -> Iterator[List[dict]]:
    columns = "note_id, subject_id, hadm_id, note_seq, storetime, text"
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    query = (
        f"SELECT {columns} FROM read_csv_auto({sql_string(note_path)}, header=true, "
        f"sample_size=-1, all_varchar=true, ignore_errors=false) "
        f"WHERE upper(coalesce(note_type, 'DS')) = 'DS' {limit_sql}"
    )
    # Some CSV versions do not expose note_type if the projection is explicit;
    # fall back to a query without that predicate in that case.
    try:
        reader = con.execute(query).fetch_record_batch(rows_per_batch=4096)
    except duckdb.BinderException:
        query = (
            f"SELECT {columns} FROM read_csv_auto({sql_string(note_path)}, header=true, "
            f"sample_size=-1, all_varchar=true, ignore_errors=false) {limit_sql}"
        )
        reader = con.execute(query).fetch_record_batch(rows_per_batch=4096)
    for batch in reader:
        rows: List[dict] = []
        for row in batch.to_pylist():
            admission_note = extract_admission_text(row.get("text"))
            hadm_id = (row.get("hadm_id") or "").strip()
            subject_id = (row.get("subject_id") or "").strip()
            if not admission_note or not hadm_id or not subject_id:
                continue
            try:
                note_seq = int(row.get("note_seq") or 0)
            except (TypeError, ValueError):
                note_seq = 0
            rows.append({
                "note_id": row.get("note_id") or "",
                "subject_id": subject_id,
                "hadm_id": hadm_id,
                "note_seq": note_seq,
                "storetime": row.get("storetime") or "",
                "admission_note": admission_note,
            })
        if rows:
            yield rows


def write_clean_notes(con: duckdb.DuckDBPyConnection, note_path: Path, path: Path, limit: int) -> int:
    schema = arrow_schema()
    path.unlink(missing_ok=True)
    writer: Optional[pq.ParquetWriter] = None
    count = 0
    try:
        for rows in iter_note_batches(con, note_path, limit):
            table = pa.Table.from_pylist(rows, schema=schema)
            if writer is None:
                writer = pq.ParquetWriter(path, schema, compression="zstd")
            writer.write_table(table)
            count += len(rows)
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        pq.write_table(pa.Table.from_pylist([], schema=schema), path, compression="zstd")
    return count


def stable_split(subject_id: int, seed: int) -> str:
    # Keep this in sync with the DuckDB expression in ``create_samples``.
    # Fifteen hex digits fit safely into an unsigned 64-bit integer.
    digest = hashlib.md5(f"{seed}:{subject_id}".encode("utf-8")).hexdigest()
    bucket = int(digest[:15], 16) % 100
    return "train" if bucket < 70 else "val" if bucket < 80 else "test"


def create_samples(con: duckdb.DuckDBPyConnection, admissions: Path, clean_notes: Path, output: Path, seed: int) -> int:
    # Select the longest cleaned note per admission. This avoids duplicate note
    # rows while retaining the most complete addendum when one exists.
    query = f"""
    WITH a AS (
        SELECT
            try_cast(subject_id AS BIGINT) AS subject_id,
            try_cast(hadm_id AS BIGINT) AS hadm_id,
            try_cast(admittime AS TIMESTAMP) AS admittime,
            try_cast(dischtime AS TIMESTAMP) AS dischtime,
            admission_type,
            admission_location,
            hospital_expire_flag
        FROM read_csv_auto({sql_string(admissions)}, header=true, sample_size=-1, all_varchar=true)
    ),
    n AS (
        SELECT *, row_number() OVER (
            PARTITION BY try_cast(hadm_id AS BIGINT)
            ORDER BY length(admission_note) DESC, note_seq DESC, storetime DESC
        ) AS rn
        FROM read_parquet({sql_string(clean_notes)})
    )
    SELECT
        a.subject_id, a.hadm_id, a.admittime, a.dischtime,
        a.admission_type, a.admission_location, a.hospital_expire_flag,
        n.note_id, n.note_seq, n.storetime, n.admission_note AS text,
        CASE
            WHEN ((CAST('0x' || substr(md5('{seed}:' || CAST(a.subject_id AS VARCHAR)), 1, 15)
                   AS UBIGINT) % 100) < 70) THEN 'train'
            WHEN ((CAST('0x' || substr(md5('{seed}:' || CAST(a.subject_id AS VARCHAR)), 1, 15)
                   AS UBIGINT) % 100) < 80) THEN 'val'
            ELSE 'test'
        END AS split
    FROM a INNER JOIN n
      ON a.subject_id = try_cast(n.subject_id AS BIGINT)
     AND a.hadm_id = try_cast(n.hadm_id AS BIGINT)
    WHERE n.rn = 1 AND a.admittime IS NOT NULL
    """
    output.unlink(missing_ok=True)
    con.execute(f"COPY ({query}) TO {sql_string(output)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    return int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(output)})").fetchone()[0])


def create_raw_labs(
    con: duckdb.DuckDBPyConnection,
    labevents: Path,
    labitems: Path,
    samples: Path,
    output: Path,
    window_hours: float,
) -> int:
    output.unlink(missing_ok=True)
    query = f"""
    COPY (
        WITH d AS (
            SELECT try_cast(itemid AS BIGINT) AS itemid, label, fluid, category
            FROM read_csv_auto({sql_string(labitems)}, header=true, sample_size=-1, all_varchar=true)
        ),
        s AS (SELECT * FROM read_parquet({sql_string(samples)})),
        l AS (
            SELECT
                try_cast(l.subject_id AS BIGINT) AS subject_id,
                try_cast(l.hadm_id AS BIGINT) AS hadm_id,
                try_cast(l.labevent_id AS BIGINT) AS labevent_id,
                try_cast(l.itemid AS BIGINT) AS itemid,
                try_cast(l.charttime AS TIMESTAMP) AS charttime,
                try_cast(l.valuenum AS DOUBLE) AS valuenum,
                l.value, l.valueuom, l.ref_range_lower, l.ref_range_upper,
                l.flag, l.priority, l.comments
            FROM read_csv_auto({sql_string(labevents)}, header=true, sample_size=-1, all_varchar=true) l
        )
        SELECT
            l.labevent_id, l.subject_id, l.hadm_id, l.itemid,
            d.label, d.fluid, d.category, l.charttime,
            date_diff('second', s.admittime, l.charttime) / 3600.0 AS time_hours,
            l.valuenum, l.value, l.valueuom,
            try_cast(l.ref_range_lower AS DOUBLE) AS ref_range_lower,
            try_cast(l.ref_range_upper AS DOUBLE) AS ref_range_upper,
            l.flag, l.priority, l.comments,
            CASE WHEN coalesce(l.flag, '') <> ''
                      OR (l.valuenum IS NOT NULL AND try_cast(l.ref_range_lower AS DOUBLE) IS NOT NULL
                          AND l.valuenum < try_cast(l.ref_range_lower AS DOUBLE))
                      OR (l.valuenum IS NOT NULL AND try_cast(l.ref_range_upper AS DOUBLE) IS NOT NULL
                          AND l.valuenum > try_cast(l.ref_range_upper AS DOUBLE))
                 THEN TRUE ELSE FALSE END AS is_abnormal
        FROM l
        INNER JOIN s ON s.subject_id = l.subject_id AND s.hadm_id = l.hadm_id
        LEFT JOIN d ON d.itemid = l.itemid
        WHERE l.charttime IS NOT NULL AND l.valuenum IS NOT NULL
          AND l.charttime >= s.admittime
          AND l.charttime < s.admittime + INTERVAL '{window_hours} hours'
        ORDER BY l.hadm_id, l.charttime, l.labevent_id
    ) TO {sql_string(output)} (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con.execute(query)
    return int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(output)})").fetchone()[0])


def encode_labs(
    con: duckdb.DuckDBPyConnection,
    raw_labs: Path,
    samples: Path,
    events_output: Path,
    sequences_output: Path,
    vocab_output: Path,
    stats_output: Path,
    min_lab_count: int,
    max_events: int,
) -> Tuple[int, int]:
    stats = con.execute(f"""
        SELECT r.itemid, count(*) AS n, avg(r.valuenum) AS mean,
               stddev_pop(r.valuenum) AS std
        FROM read_parquet({sql_string(raw_labs)}) r
        INNER JOIN read_parquet({sql_string(samples)}) s ON s.hadm_id = r.hadm_id
        WHERE s.split = 'train'
        GROUP BY r.itemid
        HAVING count(*) >= {int(min_lab_count)}
        ORDER BY r.itemid
    """).fetchall()
    vocab = {str(int(itemid)): idx + 2 for idx, (itemid, _, _, _) in enumerate(stats)}
    stats_map = {
        str(int(itemid)): {"count": int(n), "mean": float(mean), "std": float(std or 0.0)}
        for itemid, n, mean, std in stats
    }
    vocab_payload = {
        "padding_index": 0,
        "unknown_index": 1,
        "itemid_to_index": vocab,
        "min_train_event_count": min_lab_count,
    }
    vocab_output.write_text(json.dumps(vocab_payload, indent=2, sort_keys=True) + "\n")
    stats_output.write_text(json.dumps(stats_map, indent=2, sort_keys=True) + "\n")

    vocab_rows = [{"itemid": int(k), "item_index": v} for k, v in vocab.items()]
    stat_rows = [
        {"itemid": int(itemid), "mean": values["mean"], "std": values["std"]}
        for itemid, values in stats_map.items()
    ]
    con.register("scr_vocab", pa.Table.from_pylist(vocab_rows, schema=pa.schema([
        ("itemid", pa.int64()), ("item_index", pa.int64())
    ])))
    con.register("scr_stats", pa.Table.from_pylist(stat_rows, schema=pa.schema([
        ("itemid", pa.int64()), ("mean", pa.float64()), ("std", pa.float64())
    ])))
    encoded_query = f"""
        SELECT r.*,
               coalesce(v.item_index, 1) AS item_index,
               CASE WHEN st.std IS NULL OR st.std = 0 THEN 0.0
                    ELSE (r.valuenum - st.mean) / st.std END AS value_norm
        FROM read_parquet({sql_string(raw_labs)}) r
        LEFT JOIN scr_vocab v ON v.itemid = r.itemid
        LEFT JOIN scr_stats st ON st.itemid = r.itemid
    """
    events_output.unlink(missing_ok=True)
    sequences_output.unlink(missing_ok=True)
    con.execute(f"COPY ({encoded_query}) TO {sql_string(events_output)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    event_count = int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(events_output)})").fetchone()[0])

    grouped_query = f"""
    WITH grouped AS (
        SELECT
            hadm_id,
            count(*) AS event_count_total,
            list(item_index ORDER BY charttime, labevent_id) AS item_indices_all,
            list(value_norm ORDER BY charttime, labevent_id) AS values_norm_all,
            list(time_hours ORDER BY charttime, labevent_id) AS times_hours_all,
            list(is_abnormal ORDER BY charttime, labevent_id) AS abnormal_all
        FROM read_parquet({sql_string(events_output)})
        GROUP BY hadm_id
    )
    SELECT hadm_id, event_count_total,
           least(event_count_total, {int(max_events)}) AS event_count_kept,
           list_slice(item_indices_all, 1, {int(max_events)}) AS item_indices,
           list_slice(values_norm_all, 1, {int(max_events)}) AS values_norm,
           list_slice(times_hours_all, 1, {int(max_events)}) AS times_hours,
           list_slice(abnormal_all, 1, {int(max_events)}) AS is_abnormal
    FROM grouped
    """
    con.execute(f"COPY ({grouped_query}) TO {sql_string(sequences_output)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    sequence_count = int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(sequences_output)})").fetchone()[0])
    return event_count, sequence_count


def finish_samples(con: duckdb.DuckDBPyConnection, samples: Path, sequences: Path, output: Path) -> int:
    query = f"""
    SELECT s.*, coalesce(q.event_count_total, 0) AS lab_event_count,
           coalesce(q.event_count_kept, 0) AS lab_event_count_kept,
           (q.hadm_id IS NOT NULL) AS has_lab_events
    FROM read_parquet({sql_string(samples)}) s
    LEFT JOIN read_parquet({sql_string(sequences)}) q ON q.hadm_id = s.hadm_id
    """
    output.unlink(missing_ok=True)
    con.execute(f"COPY ({query}) TO {sql_string(output)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    return int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(output)})").fetchone()[0])


def write_manifest(out: Path, con: duckdb.DuckDBPyConnection, samples: Path, events: Path, sequences: Path, args: argparse.Namespace) -> None:
    counts = {
        "samples": int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(samples)})").fetchone()[0]),
        "samples_with_lab": int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(samples)}) WHERE has_lab_events").fetchone()[0]),
        "events": int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(events)})").fetchone()[0]),
        "sequences": int(con.execute(f"SELECT count(*) FROM read_parquet({sql_string(sequences)})").fetchone()[0]),
    }
    splits = con.execute(f"SELECT split, count(*) FROM read_parquet({sql_string(samples)}) GROUP BY split ORDER BY split").fetchall()
    payload = {
        "unit": "hadm_id",
        "split_unit": "subject_id",
        "lab_window_hours": args.lab_window_hours,
        "max_events_per_sequence": args.max_events,
        "seed": args.seed,
        "counts": counts,
        "split_counts": {str(k): int(v) for k, v in splits},
        "source": {
            "mimic_iv": str(args.mimic_iv),
            "notes": str(args.notes),
        },
    }
    (out / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    hosp = args.mimic_iv / "hosp"
    notes_root = args.notes / "note" if (args.notes / "note").is_dir() else args.notes
    admissions = find_file(hosp, "admissions.csv")
    labevents = find_file(hosp, "labevents.csv")
    labitems = find_file(hosp, "d_labitems.csv")
    discharge = find_file(notes_root, "discharge.csv")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    clean_notes = args.out / "_admission_note_rows.parquet"
    samples_base = args.out / "_samples_base.parquet"
    raw_labs = args.out / "_lab_events_raw.parquet"
    samples_final = args.out / "samples.parquet"
    events_final = args.out / "lab_events.parquet"
    sequences_final = args.out / "lab_sequences.parquet"

    LOG.info("Cleaning admission sections from %s", discharge)
    note_rows = write_clean_notes(con, discharge, clean_notes, args.limit_notes)
    LOG.info("Kept %d note rows with admission sections", note_rows)
    sample_rows = create_samples(con, admissions, clean_notes, samples_base, args.seed)
    LOG.info("Created %d one-row-per-hadm candidates", sample_rows)
    raw_event_rows = create_raw_labs(con, labevents, labitems, samples_base, raw_labs, args.lab_window_hours)
    LOG.info("Created %d numeric lab events in the time window", raw_event_rows)
    encoded_events, sequence_rows = encode_labs(
        con, raw_labs, samples_base, events_final, sequences_final,
        args.out / "lab_vocab.json", args.out / "lab_stats.json",
        args.min_lab_count, args.max_events,
    )
    LOG.info("Encoded %d lab events into %d admission sequences", encoded_events, sequence_rows)
    finish_samples(con, samples_base, sequences_final, samples_final)
    write_manifest(args.out, con, samples_final, events_final, sequences_final, args)

    for path in (samples_base, raw_labs):
        path.unlink(missing_ok=True)
    if not args.keep_intermediate:
        clean_notes.unlink(missing_ok=True)
    LOG.info("Finished. Output directory: %s", args.out)


if __name__ == "__main__":
    main()
