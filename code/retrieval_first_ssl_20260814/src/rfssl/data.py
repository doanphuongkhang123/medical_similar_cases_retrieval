"""Structured-EHR-only graph construction for retrieval-first SSL.

This module intentionally never reads ``clinical_notes.parquet``, ``visit_ehr``,
graph-node text fields, or free-text diagnosis descriptions.  The initial
structured-only release accepts a diagnosis node only when its controlled
diagnosis code is present.  Raw clinical text is neither an encoder input nor
an output artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import torch


NODE_TYPES = ("VISIT", "DIAGNOSIS", "MEDICINE", "PROCEDURE", "OBSERVATION")
TYPE_TO_ID = {name: index for index, name in enumerate(NODE_TYPES)}

RELATIONS = (
    "has_diagnosis", "diagnosis_of",
    "has_medicine", "medicine_of",
    "has_procedure", "procedure_of",
    "has_observation", "observation_of",
    "has_result", "result_of",
    "next_same_test", "prev_same_test",
)
RELATION_TO_ID = {name: index for index, name in enumerate(RELATIONS)}

FEATURE_DIMENSION = 7  # normalized value, count, time, flags incl. augmented mask
# ``-1`` is a valid bucket for an event occurring during the 24 hours before
# admission, so missing timestamps need an out-of-band sentinel.
MISSING_TIME_BUCKET = -(2**31)


def _clean(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).strip().split())


def _opaque_token(node_type: str, *values: Any) -> str:
    """Create a stable categorical key without retaining its source value."""
    payload = json.dumps([_clean(value).casefold() for value in values], ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{node_type}:{digest}"


def _split(visit_id: str, seed: int) -> str:
    score = int(hashlib.sha256(f"{seed}:{visit_id}".encode()).hexdigest()[:12], 16) / 16**12
    return "train" if score < 0.70 else "validation" if score < 0.85 else "test"


def _read_table(root: Path, name: str, wanted: Sequence[str]) -> pd.DataFrame:
    """Read a column projection from Parquet full data or CSV preview data."""
    parquet_path = root / f"{name}.parquet"
    csv_path = root / f"{name}.csv"
    if parquet_path.is_file():
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(parquet_path).schema.names)
        selected = [column for column in wanted if column in available]
        frame = pd.read_parquet(parquet_path, columns=selected)
    elif csv_path.is_file():
        header = pd.read_csv(csv_path, nrows=0)
        selected = [column for column in wanted if column in set(header.columns)]
        frame = pd.read_csv(csv_path, usecols=selected, low_memory=False)
    else:
        raise FileNotFoundError(f"Missing {name}.parquet or {name}.csv below {root}")
    for column in wanted:
        if column not in frame:
            frame[column] = np.nan
    return frame.loc[:, list(wanted)]


def _as_time(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _finite_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


@dataclass(frozen=True)
class Event:
    node_type: str
    token: str
    numeric_value: float
    count: int
    time_hours: float
    order_key: str = ""


@dataclass(frozen=True)
class GraphExample:
    visit_id: str
    split: str
    node_types: tuple[int, ...]
    tokens: tuple[str, ...]
    numeric_values: tuple[float, ...]
    counts: tuple[int, ...]
    time_hours: tuple[float, ...]
    order_keys: tuple[str, ...]
    edges: tuple[tuple[int, int, int], ...]

    @property
    def node_count(self) -> int:
        return len(self.node_types)

    def tensors(
        self,
        vocab: dict[str, int],
        numeric_stats: dict[str, dict[str, float]],
        device: torch.device,
        *,
        concept_mask: Iterable[int] = (),
        numeric_mask: Iterable[int] = (),
        remove_index: int | None = None,
    ) -> dict[str, torch.Tensor]:
        """Return one sparse graph tensor bundle, optionally masked/with one node removed."""
        masked_concepts = set(concept_mask)
        masked_numeric = set(numeric_mask)
        kept = [index for index in range(self.node_count) if index != remove_index]
        reindex = {old: new for new, old in enumerate(kept)}
        concept_ids: list[int] = []
        type_ids: list[int] = []
        features: list[list[float]] = []
        numeric_targets: list[float] = []
        time_buckets: list[int] = []
        for old in kept:
            token = self.tokens[old]
            value = self.numeric_values[old]
            has_numeric = float(math.isfinite(value))
            stats = numeric_stats.get(token, {"median": 0.0, "iqr": 1.0})
            normalized = 0.0 if not has_numeric else float(np.clip((value - stats["median"]) / stats["iqr"], -5.0, 5.0))
            time = self.time_hours[old]
            has_time = float(math.isfinite(time))
            time_feature = 0.0 if not has_time else float(np.clip(time / 168.0, -4.0, 4.0))
            # The encoder receives a bounded continuous feature for numerical
            # stability.  MI corruption needs the original 24-hour window,
            # however, so retain its exact integer bucket separately.
            time_bucket = MISSING_TIME_BUCKET if not has_time else math.floor(time / 24.0)
            augmented = float(old in masked_numeric and bool(has_numeric))
            if augmented:
                normalized = 0.0
            concept_id = vocab.get(token, vocab["<UNK>"])
            if old in masked_concepts and old != 0:
                concept_id = vocab["<MASK>"]
            concept_ids.append(concept_id)
            type_ids.append(self.node_types[old])
            features.append([
                normalized,
                math.log1p(max(0, self.counts[old])),
                time_feature,
                has_numeric,
                has_time,
                1.0 - has_numeric,
                augmented,
            ])
            numeric_targets.append(normalized if not augmented else float(np.clip((value - stats["median"]) / stats["iqr"], -5.0, 5.0)))
            time_buckets.append(time_bucket)
        edge_rows = [
            (reindex[source], reindex[target], relation)
            for source, target, relation in self.edges
            if source in reindex and target in reindex
        ]
        if not edge_rows:
            # A single-node graph is valid for the encoder, even though the main
            # loader does not normally emit it.
            edge_rows = [(0, 0, 0)]
        return {
            "concept_ids": torch.tensor(concept_ids, dtype=torch.long, device=device),
            "type_ids": torch.tensor(type_ids, dtype=torch.long, device=device),
            "numeric": torch.tensor(features, dtype=torch.float32, device=device),
            "numeric_targets": torch.tensor(numeric_targets, dtype=torch.float32, device=device),
            "sources": torch.tensor([row[0] for row in edge_rows], dtype=torch.long, device=device),
            "destinations": torch.tensor([row[1] for row in edge_rows], dtype=torch.long, device=device),
            "relation_ids": torch.tensor([row[2] for row in edge_rows], dtype=torch.long, device=device),
            "time_buckets": torch.tensor(time_buckets, dtype=torch.long, device=device),
            "kept_indices": torch.tensor(kept, dtype=torch.long, device=device),
        }


@dataclass
class StructuredDataset:
    examples: list[GraphExample]
    vocab: dict[str, int]
    numeric_stats: dict[str, dict[str, float]]
    idf: dict[str, float]
    manifest: dict[str, Any]

    def split_examples(self, split: str) -> list[GraphExample]:
        return [example for example in self.examples if example.split == split]


def _aggregate_diagnoses(frame: pd.DataFrame, admission: dict[str, pd.Timestamp]) -> list[tuple[str, Event]]:
    frame = frame.copy()
    frame["visit_id"] = frame["visit_id"].map(_clean)
    frame["diagnosis_code"] = frame["diagnosis_code"].map(_clean)
    # No text fallback: a hash of free text still makes that text a model
    # feature.  Description-only diagnoses are deferred to the text stage.
    frame = frame[frame.visit_id.ne("") & frame.diagnosis_code.ne("")]
    frame["event_time"] = _as_time(frame["event_time"])
    frame["token"] = [
        _opaque_token("DIAGNOSIS", code, diag_type)
        for code, diag_type in zip(frame.diagnosis_code, frame.diagnosis_type)
    ]
    rows: list[tuple[str, Event]] = []
    for (visit_id, token), group in frame.groupby(["visit_id", "token"], sort=False):
        timestamp = group.event_time.min()
        start = admission.get(visit_id, pd.NaT)
        hours = math.nan if pd.isna(timestamp) or pd.isna(start) else float((timestamp - start).total_seconds() / 3600.0)
        rows.append((visit_id, Event("DIAGNOSIS", token, math.nan, int(len(group)), hours)))
    return rows


def _aggregate_medicines(frame: pd.DataFrame, admission: dict[str, pd.Timestamp]) -> list[tuple[str, Event]]:
    frame = frame.copy()
    frame["visit_id"] = frame["visit_id"].map(_clean)
    frame = frame[frame.visit_id.ne("")]
    frame["prescribed_time"] = _as_time(frame["prescribed_time"])
    frame["token"] = [
        _opaque_token("MEDICINE", _clean(active) or _clean(drug), route, unit, status)
        for active, drug, route, unit, status in zip(
            frame.active_ingredient, frame.drug_name, frame.route, frame.unit, frame.status
        )
    ]
    frame["numeric"] = frame.total_quantity.map(_finite_number)
    rows: list[tuple[str, Event]] = []
    for (visit_id, token), group in frame.groupby(["visit_id", "token"], sort=False):
        timestamp = group.prescribed_time.min()
        start = admission.get(visit_id, pd.NaT)
        hours = math.nan if pd.isna(timestamp) or pd.isna(start) else float((timestamp - start).total_seconds() / 3600.0)
        numeric = pd.to_numeric(group.numeric, errors="coerce").median()
        rows.append((visit_id, Event("MEDICINE", token, _finite_number(numeric), int(len(group)), hours)))
    return rows


def _aggregate_procedures(frame: pd.DataFrame, admission: dict[str, pd.Timestamp]) -> list[tuple[str, Event]]:
    frame = frame.copy()
    frame["visit_id"] = frame["visit_id"].map(_clean)
    frame["order_id"] = frame["order_id"].map(_clean)
    frame = frame[frame.visit_id.ne("")]
    frame["event_time"] = _as_time(frame.start_time).fillna(_as_time(frame.ordered_time))
    frame["token"] = [
        _opaque_token("PROCEDURE", _clean(code) or _clean(name), status)
        for code, name, status in zip(frame.service_code, frame.procedure_name, frame.status)
    ]
    rows: list[tuple[str, Event]] = []
    for (visit_id, order_id, token), group in frame.groupby(["visit_id", "order_id", "token"], sort=False):
        timestamp = group.event_time.min()
        start = admission.get(visit_id, pd.NaT)
        hours = math.nan if pd.isna(timestamp) or pd.isna(start) else float((timestamp - start).total_seconds() / 3600.0)
        rows.append((visit_id, Event("PROCEDURE", token, math.nan, int(len(group)), hours, order_id)))
    return rows


def _aggregate_observations(frame: pd.DataFrame, admission: dict[str, pd.Timestamp]) -> list[tuple[str, Event]]:
    frame = frame.copy()
    frame["visit_id"] = frame["visit_id"].map(_clean)
    frame["order_id"] = frame["order_id"].map(_clean)
    frame = frame[frame.visit_id.ne("")]
    frame["observed_time"] = _as_time(frame["observed_time"])
    frame["token"] = [
        _opaque_token("OBSERVATION", _clean(code) or _clean(name), unit)
        for code, name, unit in zip(frame.service_code, frame.observation_name, frame.unit)
    ]
    frame["numeric"] = frame.result_numeric.map(_finite_number)
    rows: list[tuple[str, Event]] = []
    for (visit_id, order_id, token), group in frame.groupby(["visit_id", "order_id", "token"], sort=False):
        timestamp = group.observed_time.min()
        start = admission.get(visit_id, pd.NaT)
        hours = math.nan if pd.isna(timestamp) or pd.isna(start) else float((timestamp - start).total_seconds() / 3600.0)
        numeric = pd.to_numeric(group.numeric, errors="coerce").median()
        rows.append((visit_id, Event("OBSERVATION", token, _finite_number(numeric), int(len(group)), hours, order_id)))
    return rows


def _build_graph(visit_id: str, split: str, events: Sequence[Event]) -> GraphExample:
    events = sorted(events, key=lambda item: (TYPE_TO_ID[item.node_type], item.token, item.order_key, item.time_hours if math.isfinite(item.time_hours) else float("inf")))
    node_types = [TYPE_TO_ID["VISIT"]]
    tokens = ["<PAD>"]
    numeric_values = [math.nan]
    counts = [0]
    time_hours = [0.0]
    order_keys = [""]
    relation_for_type = {
        "DIAGNOSIS": ("has_diagnosis", "diagnosis_of"),
        "MEDICINE": ("has_medicine", "medicine_of"),
        "PROCEDURE": ("has_procedure", "procedure_of"),
        "OBSERVATION": ("has_observation", "observation_of"),
    }
    edges: list[tuple[int, int, int]] = []
    procedure_by_order: dict[str, list[int]] = {}
    observations_by_token: dict[str, list[int]] = {}
    for event in events:
        index = len(node_types)
        node_types.append(TYPE_TO_ID[event.node_type])
        tokens.append(event.token)
        numeric_values.append(event.numeric_value)
        counts.append(event.count)
        time_hours.append(event.time_hours)
        order_keys.append(event.order_key)
        forward, reverse = relation_for_type[event.node_type]
        edges.append((0, index, RELATION_TO_ID[forward]))
        edges.append((index, 0, RELATION_TO_ID[reverse]))
        if event.node_type == "PROCEDURE" and event.order_key:
            procedure_by_order.setdefault(event.order_key, []).append(index)
        if event.node_type == "OBSERVATION":
            observations_by_token.setdefault(event.token, []).append(index)
    for index, node_type in enumerate(node_types):
        if node_type != TYPE_TO_ID["OBSERVATION"]:
            continue
        order_key = order_keys[index]
        if order_key:
            for procedure in procedure_by_order.get(order_key, []):
                edges.append((procedure, index, RELATION_TO_ID["has_result"]))
                edges.append((index, procedure, RELATION_TO_ID["result_of"]))
    for indices in observations_by_token.values():
        ordered = sorted(
            (index for index in indices if math.isfinite(time_hours[index])),
            key=lambda index: time_hours[index],
        )
        for source, target in zip(ordered, ordered[1:]):
            edges.append((source, target, RELATION_TO_ID["next_same_test"]))
            edges.append((target, source, RELATION_TO_ID["prev_same_test"]))
    return GraphExample(
        visit_id=visit_id,
        split=split,
        node_types=tuple(node_types),
        tokens=tuple(tokens),
        numeric_values=tuple(numeric_values),
        counts=tuple(counts),
        time_hours=tuple(time_hours),
        order_keys=tuple(order_keys),
        edges=tuple(edges),
    )


def load_structured_dataset(data_root: Path, *, seed: int = 20260812, limit_visits: int = 0) -> StructuredDataset:
    """Load and aggregate structured EHR tables without reading clinical notes.

    ``limit_visits`` is deterministic and intended only for a smoke run.  It is
    selected after the visit-disjoint split assignment, not by slicing source rows.
    """
    visits = _read_table(data_root, "visits", ["visit_id", "admission_time"])
    visits["visit_id"] = visits.visit_id.map(_clean)
    visits = visits[visits.visit_id.ne("")].drop_duplicates("visit_id", keep="first")
    visits["admission_time"] = _as_time(visits.admission_time)
    visits["split"] = visits.visit_id.map(lambda value: _split(value, seed))
    visits = visits.sort_values("visit_id", kind="stable")
    if limit_visits:
        visits = visits.head(limit_visits).copy()
    allowed_visits = set(visits.visit_id)
    admission = dict(zip(visits.visit_id, visits.admission_time))

    diagnoses = _read_table(data_root, "diagnoses", [
        "visit_id", "diagnosis_code", "diagnosis_type", "event_time",
    ])
    medicines = _read_table(data_root, "medicines", [
        "visit_id", "drug_name", "active_ingredient", "route", "unit", "total_quantity", "prescribed_time", "status",
    ])
    procedures = _read_table(data_root, "procedures", [
        "visit_id", "order_id", "service_code", "procedure_name", "status", "ordered_time", "start_time",
    ])
    observations = _read_table(data_root, "observations", [
        "visit_id", "order_id", "service_code", "observation_name", "result_numeric", "unit", "observed_time",
    ])
    source_frames = [diagnoses, medicines, procedures, observations]
    for frame in source_frames:
        frame["visit_id"] = frame.visit_id.map(_clean)
        frame.drop(frame.index[~frame.visit_id.isin(allowed_visits)], inplace=True)

    by_visit: dict[str, list[Event]] = {visit_id: [] for visit_id in visits.visit_id}
    for visit_id, event in _aggregate_diagnoses(diagnoses, admission):
        by_visit[visit_id].append(event)
    for visit_id, event in _aggregate_medicines(medicines, admission):
        by_visit[visit_id].append(event)
    for visit_id, event in _aggregate_procedures(procedures, admission):
        by_visit[visit_id].append(event)
    for visit_id, event in _aggregate_observations(observations, admission):
        by_visit[visit_id].append(event)

    examples = [
        _build_graph(row.visit_id, row.split, by_visit[row.visit_id])
        for row in visits.itertuples(index=False)
    ]
    train_examples = [example for example in examples if example.split == "train"]
    train_tokens = sorted({token for example in train_examples for token in example.tokens[1:]})
    vocab = {"<PAD>": 0, "<MASK>": 1, "<UNK>": 2}
    vocab.update({token: index for index, token in enumerate(train_tokens, start=len(vocab))})
    values_by_token: dict[str, list[float]] = {}
    document_frequency: dict[str, int] = {}
    for example in train_examples:
        seen: set[str] = set()
        for token, value in zip(example.tokens[1:], example.numeric_values[1:]):
            if math.isfinite(value):
                values_by_token.setdefault(token, []).append(value)
            seen.add(token)
        for token in seen:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    numeric_stats: dict[str, dict[str, float]] = {}
    for token, values in values_by_token.items():
        vector = np.asarray(values, dtype=np.float64)
        median = float(np.median(vector))
        iqr = float(np.quantile(vector, 0.75) - np.quantile(vector, 0.25))
        numeric_stats[token] = {"median": median, "iqr": iqr if iqr > 1e-8 else 1.0}
    total_train = max(1, len(train_examples))
    idf = {token: float(math.log((total_train + 1) / (count + 1)) + 1.0) for token, count in document_frequency.items()}
    node_counts = [example.node_count for example in examples]
    manifest = {
        "data_root": str(data_root),
        "scope": "structured_ehr_only_no_clinical_notes",
        "snapshot_mode": "full_visit",
        "split": {"unit": "visit_id", "seed": seed, "fractions": {"train": 0.70, "validation": 0.15, "test": 0.15}},
        "selected_tables": ["visits", "diagnoses", "medicines", "procedures", "observations"],
        "excluded_tables": ["clinical_notes", "visit_ehr", "graph_nodes", "graph_edges"],
        "diagnosis_policy": "controlled_code_only_no_description_fallback",
        "raw_text_persisted": False,
        "graph_count": len(examples),
        "split_counts": {split: sum(example.split == split for example in examples) for split in ("train", "validation", "test")},
        "node_count": {"median": float(np.median(node_counts)), "p90": float(np.quantile(node_counts, 0.90)), "max": int(max(node_counts, default=0))},
        "vocab_size": len(vocab),
    }
    return StructuredDataset(examples=examples, vocab=vocab, numeric_stats=numeric_stats, idf=idf, manifest=manifest)
