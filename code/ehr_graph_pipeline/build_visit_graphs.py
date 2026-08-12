"""Turn canonical EHR tables into sparse, independent visit graphs."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ehr_common import normalize_name, write_json

NODE_TYPES = ["VISIT", "TEXT_SECTION", "VITAL", "ORDER", "LAB_RESULT", "PRESCRIPTION", "MEDICATION", "PROCEDURE"]


def graph_for_visit(visit: pd.Series, events: pd.DataFrame, relations: pd.DataFrame, vocab: dict[str, int], stats: dict[str, dict[str, float]]) -> dict[str, Any]:
    visit_id = str(visit.visit_id)
    nodes: list[dict[str, Any]] = [{"node_type": "VISIT", "concept_index": 0, "numeric_value": 0.0, "time_hours": 0.0}]
    event_nodes: dict[str, int] = {}
    admission = pd.to_datetime(visit.admission_time, errors="coerce", utc=True)
    for _, event in events.iterrows():
        event_id = str(event.event_id)
        event_nodes[event_id] = len(nodes)
        key = f"{normalize_name(event.concept_name)}\u241f{normalize_name(event.unit)}"
        values = stats.get(key, {"median": 0.0, "iqr": 1.0})
        numeric = pd.to_numeric(pd.Series([event.numeric_value]), errors="coerce").iloc[0]
        numeric_norm = 0.0 if pd.isna(numeric) else float(np.clip((numeric - values["median"]) / values["iqr"], -5, 5))
        timestamp = pd.to_datetime(event.event_time, errors="coerce", utc=True)
        delta = 0.0 if pd.isna(timestamp) or pd.isna(admission) else float((timestamp - admission).total_seconds() / 3600)
        nodes.append({"node_type": event.event_type, "concept_index": int(vocab.get(normalize_name(event.concept_name), 0)), "numeric_value": numeric_norm, "time_hours": delta})
    edges: list[dict[str, Any]] = []

    def add_edge(source: int, relation: str, target: int) -> None:
        edges.append({"source": source, "relation": relation, "target": target})
        edges.append({"source": target, "relation": f"rev_{relation}", "target": source})

    for node_index in range(1, len(nodes)):
        # Direct links preserve the VISIT readout's access to all modalities.
        add_edge(0, "has_event", node_index)
    for _, relation in relations.iterrows():
        source, target = event_nodes.get(str(relation.source_event_id)), event_nodes.get(str(relation.target_event_id))
        if source is not None and target is not None:
            add_edge(source, str(relation.relation_type), target)
    # Linear temporal links only for consecutive lab results of the same test.
    lab_rows = events[events.event_type == "LAB_RESULT"].copy()
    lab_rows["event_time"] = pd.to_datetime(lab_rows.event_time, errors="coerce", utc=True)
    for _, group in lab_rows.dropna(subset=["event_time"]).sort_values("event_time").groupby("concept_name"):
        ids = [event_nodes[str(event_id)] for event_id in group.event_id]
        for source, target in zip(ids, ids[1:]):
            add_edge(source, "next_same_test", target)
    return {"visit_id": visit_id, "split": visit.split, "nodes": nodes, "edges": edges}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sparse one-visit-per-graph GT-BEHRT inputs.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    visits = pd.read_parquet(args.input / "visits.parquet")
    events = pd.read_parquet(args.input / "events.parquet")
    relations = pd.read_parquet(args.input / "relations.parquet")
    vocab = json.loads((args.input / "concept_vocab.json").read_text(encoding="utf-8"))
    stats = json.loads((args.input / "numeric_stats.json").read_text(encoding="utf-8"))
    graphs_dir = args.output / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    # Materialize each visit group once. Repeated boolean filtering here would
    # scan the complete 760k-event table for every visit.
    events_by_visit = {str(visit_id): group for visit_id, group in events.groupby("visit_id", sort=False)}
    relations_by_visit = {str(visit_id): group for visit_id, group in relations.groupby("visit_id", sort=False)}
    for _, visit in visits.iterrows():
        visit_id = str(visit.visit_id)
        graph = graph_for_visit(
            visit,
            events_by_visit.get(visit_id, events.iloc[0:0]),
            relations_by_visit.get(visit_id, relations.iloc[0:0]),
            vocab,
            stats,
        )
        relative = Path("graphs") / f"{len(index):06d}.json"
        (args.output / relative).write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"visit_id": graph["visit_id"], "split": graph["split"], "graph_path": str(relative).replace("\\", "/"), "node_count": len(graph["nodes"]), "edge_count": len(graph["edges"])})
    pd.DataFrame(index).to_parquet(args.output / "graph_index.parquet", index=False)
    write_json(args.output / "graph_manifest.json", {"graph_unit": "SoBenhAn", "node_types": NODE_TYPES, "graph_count": len(index), "direct_identifier_features": False})
    print({"output": str(args.output), "graphs": len(index)})


if __name__ == "__main__":
    main()
