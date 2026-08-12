"""Create canonical EHR tables for one independent graph per visit.

Only approved fields from ``feature_policy.yaml`` are materialized as model
features.  IDs stay as lineage keys and are never encoded as features.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ehr_common import find_column, normalize_name, parse_lab_value, require_column, robust_stats, stable_hash, write_json

SHEETS = {"visits": "thông tin bệnh án", "orders": "chỉ định DVKT", "medications": "Thuốc", "labs": "KQCLS", "procedures": "Phẫu thuật thủ thuật"}


def load_policy(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def read_workbook(path: Path) -> dict[str, pd.DataFrame]:
    workbook = pd.ExcelFile(path, engine="openpyxl")
    missing = set(SHEETS.values()).difference(workbook.sheet_names)
    if missing:
        raise ValueError(f"Workbook missing required sheets: {sorted(missing)}")
    return {name: pd.read_excel(workbook, sheet_name=sheet, dtype=object) for name, sheet in SHEETS.items()}


def _event_id(event_type: str, visit_id: str, ordinal: int, source_hash: str) -> str:
    return f"{event_type}:{stable_hash([visit_id, ordinal, source_hash])[:24]}"


def _date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def canonicalize(frames: dict[str, pd.DataFrame], policy: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    visits_raw = frames["visits"].copy()
    visit_key = require_column(visits_raw, "SoBenhAn")
    visits_raw[visit_key] = visits_raw[visit_key].map(normalize_name)
    visits_raw = visits_raw[visits_raw[visit_key] != ""].drop_duplicates(visit_key, keep="first")
    admission = find_column(visits_raw, "NgayVaoVien")
    discharge = find_column(visits_raw, "NgayRaVien")
    department = find_column(visits_raw, "TenPhongBan")
    visits = pd.DataFrame({
        "visit_id": visits_raw[visit_key],
        "admission_time": _date(visits_raw[admission]) if admission else pd.NaT,
        "discharge_time": _date(visits_raw[discharge]) if discharge else pd.NaT,
        "department": visits_raw[department].map(normalize_name) if department else "",
    })
    visits["source_row_hash"] = [stable_hash(["visit", value]) for value in visits["visit_id"]]
    known_visits = set(visits.visit_id)
    events: list[dict[str, Any]] = []
    relations: list[dict[str, str]] = []

    def add_event(visit_id: str, event_type: str, concept: Any, event_time: Any = pd.NaT, numeric: Any = np.nan, text: Any = "", unit: Any = "", order_id: Any = "", prescription_id: Any = "", extra: dict[str, Any] | None = None) -> str:
        ordinal = len(events)
        source_hash = stable_hash([event_type, visit_id, normalize_name(concept), normalize_name(event_time), normalize_name(numeric), normalize_name(text), normalize_name(unit), normalize_name(order_id), normalize_name(prescription_id)])
        event_id = _event_id(event_type, visit_id, ordinal, source_hash)
        event = {"event_id": event_id, "visit_id": visit_id, "event_type": event_type, "concept_id": normalize_name(concept), "concept_name": normalize_name(concept), "event_time": event_time, "numeric_value": numeric, "text_value": normalize_name(text), "unit": normalize_name(unit), "order_id": normalize_name(order_id), "prescription_id": normalize_name(prescription_id), "source_row_hash": source_hash}
        if extra:
            event.update(extra)
        events.append(event)
        return event_id

    # Approved admission/static information only. Text is represented by a hash
    # in the canonical artifact; raw text never reaches graph tensors or logs.
    for _, row in visits_raw.iterrows():
        visit_id = row[visit_key]
        for field in policy["allowed_text_sections"]:
            column = find_column(visits_raw, field)
            value = normalize_name(row[column]) if column else ""
            if value:
                add_event(visit_id, "TEXT_SECTION", field, text=stable_hash(value))
        for field in policy["vitals"]:
            column = find_column(visits_raw, field)
            if column:
                value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
                if pd.notna(value):
                    add_event(visit_id, "VITAL", field, numeric=float(value))

    order_nodes: dict[tuple[str, str], str] = {}
    orders_by_id: dict[str, list[tuple[str, str]]] = defaultdict(list)
    order_frame = frames["orders"]
    order_visit = require_column(order_frame, "SoBenhAn")
    order_id_col, service_col, order_time = require_column(order_frame, "YeuCauChiTiet_Id"), require_column(order_frame, "TenDichVu"), find_column(order_frame, "NgayYeuCau")
    for _, row in order_frame.iterrows():
        visit_id = normalize_name(row[order_visit])
        order_id = normalize_name(row[order_id_col])
        if visit_id not in known_visits or not order_id:
            continue
        node = add_event(visit_id, "ORDER", row[service_col], _date(pd.Series([row[order_time]])).iloc[0] if order_time else pd.NaT, order_id=order_id)
        order_nodes[(visit_id, order_id)] = node
        orders_by_id[order_id].append((visit_id, node))

    prescription_nodes: dict[tuple[str, str], str] = {}
    medication_frame = frames["medications"]
    med_visit, prescription, drug, active, med_time = require_column(medication_frame, "sobenhan", "SoBenhAn"), require_column(medication_frame, "SoThuTuToa"), require_column(medication_frame, "TenDuoc"), find_column(medication_frame, "TenHoatChat"), find_column(medication_frame, "NgayKham")
    for _, row in medication_frame.iterrows():
        visit_id, prescription_id = normalize_name(row[med_visit]), normalize_name(row[prescription])
        if visit_id not in known_visits:
            continue
        key = (visit_id, prescription_id or "__ungrouped__")
        if key not in prescription_nodes:
            prescription_nodes[key] = add_event(visit_id, "PRESCRIPTION", "PRESCRIPTION", prescription_id=key[1])
        time = _date(pd.Series([row[med_time]])).iloc[0] if med_time else pd.NaT
        medication = add_event(visit_id, "MEDICATION", row[drug], time, text=normalize_name(row[active]) if active else "", prescription_id=key[1])
        relations.append({"source_event_id": prescription_nodes[key], "relation_type": "has_drug", "target_event_id": medication, "visit_id": visit_id})

    lab_frame = frames["labs"]
    lab_visit, lab_order, test, result, unit, result_time = require_column(lab_frame, "SoBenhAn"), require_column(lab_frame, "YeuCauChiTiet_Id"), require_column(lab_frame, "TEN_CHI_SO"), require_column(lab_frame, "GIA_TRI"), find_column(lab_frame, "DON_VI_DO"), find_column(lab_frame, "NGAY_KQ")
    for _, row in lab_frame.iterrows():
        visit_id, order_id = normalize_name(row[lab_visit]), normalize_name(row[lab_order])
        if visit_id not in known_visits:
            continue
        parsed = parse_lab_value(row[result])
        time = _date(pd.Series([row[result_time]])).iloc[0] if result_time else pd.NaT
        lab = add_event(visit_id, "LAB_RESULT", row[test], time, parsed["numeric_value"], text=parsed["categorical_value"], unit=row[unit] if unit else "", order_id=order_id, extra={"comparison_operator": parsed["comparison_operator"], "parse_success": parsed["parse_success"]})
        if (visit_id, order_id) in order_nodes:
            relations.append({"source_event_id": order_nodes[(visit_id, order_id)], "relation_type": "has_result", "target_event_id": lab, "visit_id": visit_id})

    procedure_frame = frames["procedures"]
    procedure_order, procedure_name, start = require_column(procedure_frame, "YeuCauChiTiet_Id"), find_column(procedure_frame, "TenDichVu", "ten_dich_vu"), find_column(procedure_frame, "ThoiGianBatDau")
    # Procedure rows inherit visit identity only through a validated order join.
    for _, row in procedure_frame.iterrows():
        order_id = normalize_name(row[procedure_order])
        matches = orders_by_id.get(order_id, [])
        for visit_id, order_node in matches:
            time = _date(pd.Series([row[start]])).iloc[0] if start else pd.NaT
            procedure = add_event(visit_id, "PROCEDURE", row[procedure_name] if procedure_name else "PROCEDURE", time, order_id=order_id)
            relations.append({"source_event_id": order_node, "relation_type": "has_procedure", "target_event_id": procedure, "visit_id": visit_id})

    events_frame = pd.DataFrame(events)
    relations_frame = pd.DataFrame(relations, columns=["source_event_id", "relation_type", "target_event_id", "visit_id"])
    unmatched_lab_orders = sum(
        event["event_type"] == "LAB_RESULT" and (event["visit_id"], event["order_id"]) not in order_nodes
        for event in events
    )
    counts = {"visits": len(visits), "events": len(events_frame), "relations": len(relations_frame), "unmatched_lab_orders": int(unmatched_lab_orders)}
    return visits, events_frame, relations_frame, counts


def apply_snapshot(visits: pd.DataFrame, events: pd.DataFrame, mode: str, hours: float) -> pd.DataFrame:
    if mode == "full_visit":
        return events.copy()
    merged = events.merge(visits[["visit_id", "admission_time"]], on="visit_id", how="left")
    static_types = {"TEXT_SECTION", "VITAL"}
    if mode == "admission":
        return merged[merged.event_type.isin(static_types)].drop(columns="admission_time")
    if mode != "first_24h":
        raise ValueError(f"Unsupported snapshot mode: {mode}")
    timed = merged.event_time.notna() & merged.admission_time.notna() & (merged.event_time >= merged.admission_time) & (merged.event_time <= merged.admission_time + pd.Timedelta(hours=hours))
    return merged[timed | merged.event_type.isin(static_types)].drop(columns="admission_time")


def split_visits(visits: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    result = visits.copy()
    seed = str(policy["split"]["seed"])
    score = result.visit_id.map(lambda value: int(hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()[:12], 16) / 16**12)
    train = float(policy["split"]["train_fraction"])
    validation = train + float(policy["split"]["validation_fraction"])
    result["split"] = np.where(score < train, "train", np.where(score < validation, "validation", "test"))
    return result


def fit_artifacts(events: pd.DataFrame, visits: pd.DataFrame) -> tuple[dict[str, int], dict[str, dict[str, float]]]:
    train_visits = set(visits.loc[visits.split == "train", "visit_id"])
    train = events[events.visit_id.isin(train_visits)]
    concepts = sorted({normalize_name(value) for value in train.concept_name if normalize_name(value)})
    vocab = {"<UNK>": 0, **{concept: index for index, concept in enumerate(concepts, start=1)}}
    numeric = train[train.numeric_value.notna()].copy()
    stats: dict[str, dict[str, float]] = {}
    for (concept, unit), group in numeric.groupby(["concept_name", "unit"], dropna=False):
        median, iqr = robust_stats(group.numeric_value)
        stats[f"{normalize_name(concept)}\u241f{normalize_name(unit)}"] = {"median": median, "iqr": iqr, "count": int(len(group))}
    return vocab, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonicalize EHR workbook without embedding direct identifiers.")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config" / "feature_policy.yaml")
    parser.add_argument("--snapshot-mode", choices=["admission", "first_24h", "full_visit"])
    args = parser.parse_args()
    policy = load_policy(args.config)
    mode = args.snapshot_mode or policy["snapshot"]["mode"]
    frames = read_workbook(args.workbook)
    visits, events, relations, counts = canonicalize(frames, policy)
    visits = split_visits(visits, policy)
    events = apply_snapshot(visits, events, mode, float(policy["snapshot"]["first_24h_hours"]))
    relations = relations[relations.source_event_id.isin(set(events.event_id)) & relations.target_event_id.isin(set(events.event_id))]
    visits["snapshot_mode"] = mode
    vocab, stats = fit_artifacts(events, visits)
    args.output.mkdir(parents=True, exist_ok=True)
    visits.to_parquet(args.output / "visits.parquet", index=False)
    events.drop(columns="text_value").to_parquet(args.output / "events.parquet", index=False)
    relations.to_parquet(args.output / "relations.parquet", index=False)
    write_json(args.output / "concept_vocab.json", vocab)
    write_json(args.output / "numeric_stats.json", stats)
    write_json(args.output / "preprocessing_manifest.json", {"workbook_sha256": hashlib.sha256(args.workbook.read_bytes()).hexdigest(), "snapshot_mode": mode, "split": policy["split"], "counts": counts, "raw_text_in_artifacts": False})
    print({"output": str(args.output), "counts": counts, "snapshot_mode": mode})


if __name__ == "__main__":
    main()
