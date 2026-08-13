"""Create a deterministic, relationally consistent preview of EHR CSV tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd


TABLES_BY_VISIT_KEY = (
    "visit_ehr.csv",
    "diagnoses.csv",
    "medicines.csv",
    "procedures.csv",
    "clinical_notes.csv",
    "observations.csv",
)
TABLES_BY_GRAPH_ID = ("graph_nodes.csv", "graph_edges.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sample visits from canonical EHR CSVs and retain every related row "
            "and graph element for those visits."
        )
    )
    parser.add_argument("--input", required=True, type=Path, help="Full CSV directory")
    parser.add_argument("--output", required=True, type=Path, help="New preview directory")
    parser.add_argument("--n-visits", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--chunksize", type=int, default=100_000)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(frame: pd.DataFrame, path: Path, *, mode: str = "w", header: bool = True) -> None:
    frame.to_csv(
        path,
        mode=mode,
        header=header,
        index=False,
        encoding="utf-8",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )


def filter_table(
    source: Path,
    destination: Path,
    selected_pairs: set[tuple[str, str]],
    selected_graph_ids: set[str],
    chunksize: int,
) -> tuple[int, int]:
    rows_written = 0
    column_count = 0
    wrote_header = False

    for chunk in pd.read_csv(
        source,
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
        encoding="utf-8",
    ):
        column_count = len(chunk.columns)
        if "graph_id" in chunk.columns:
            keep = chunk["graph_id"].isin(selected_graph_ids)
        else:
            pairs = pd.Series(
                zip(chunk["patient_id"], chunk["visit_id"]), index=chunk.index
            )
            keep = pairs.isin(selected_pairs)

        filtered = chunk.loc[keep]
        if not filtered.empty:
            write_csv(
                filtered,
                destination,
                mode="a" if wrote_header else "w",
                header=not wrote_header,
            )
            wrote_header = True
            rows_written += len(filtered)

    if not wrote_header:
        header = pd.read_csv(source, dtype=str, keep_default_na=False, nrows=0)
        write_csv(header, destination)
        column_count = len(header.columns)

    return rows_written, column_count


def collect_manifest(output: Path, row_counts: dict[str, int]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for path in sorted(output.glob("*.csv")):
        if path.name == "manifest.csv":
            continue
        header = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=0)
        records.append(
            {
                "file": path.name,
                "rows": row_counts[path.name],
                "columns": len(header.columns),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "encoding": "utf-8",
                "delimiter": ",",
                "header": True,
                "index_written": False,
            }
        )
    return pd.DataFrame(records)


def validate_preview(
    output: Path,
    selected_pairs: set[tuple[str, str]],
    selected_graph_ids: set[str],
    chunksize: int,
) -> dict[str, object]:
    visits = pd.read_csv(output / "visits.csv", dtype=str, keep_default_na=False)
    visit_pairs = set(zip(visits["patient_id"], visits["visit_id"]))
    if visit_pairs != selected_pairs or len(visits) != len(selected_pairs):
        raise RuntimeError("visits.csv does not contain exactly the sampled visit keys")
    if visits[["patient_id", "visit_id"]].duplicated().any():
        raise RuntimeError("Duplicate (patient_id, visit_id) found in visits.csv")

    table_graph_ids: dict[str, int] = {}
    for filename in TABLES_BY_VISIT_KEY:
        observed_pairs: set[tuple[str, str]] = set()
        for chunk in pd.read_csv(
            output / filename,
            dtype=str,
            keep_default_na=False,
            chunksize=chunksize,
            encoding="utf-8",
        ):
            observed_pairs.update(zip(chunk["patient_id"], chunk["visit_id"]))
        if not observed_pairs.issubset(selected_pairs):
            raise RuntimeError(f"{filename} contains rows outside the sampled visits")

    node_ids: dict[str, set[str]] = {}
    duplicate_node_count = 0
    for chunk in pd.read_csv(
        output / "graph_nodes.csv",
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
        encoding="utf-8",
    ):
        if not set(chunk["graph_id"]).issubset(selected_graph_ids):
            raise RuntimeError("graph_nodes.csv contains an unexpected graph_id")
        for graph_id, node_id in zip(chunk["graph_id"], chunk["node_id"]):
            graph_nodes = node_ids.setdefault(graph_id, set())
            if node_id in graph_nodes:
                duplicate_node_count += 1
            graph_nodes.add(node_id)
    if duplicate_node_count:
        raise RuntimeError(f"Found {duplicate_node_count} duplicate graph node IDs")

    missing_edge_endpoints = 0
    edge_graph_ids: set[str] = set()
    for chunk in pd.read_csv(
        output / "graph_edges.csv",
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
        encoding="utf-8",
    ):
        edge_graph_ids.update(chunk["graph_id"])
        if not set(chunk["graph_id"]).issubset(selected_graph_ids):
            raise RuntimeError("graph_edges.csv contains an unexpected graph_id")
        for graph_id, source, target in zip(
            chunk["graph_id"], chunk["source_node_id"], chunk["target_node_id"]
        ):
            graph_nodes = node_ids.get(graph_id, set())
            missing_edge_endpoints += int(source not in graph_nodes)
            missing_edge_endpoints += int(target not in graph_nodes)
    if missing_edge_endpoints:
        raise RuntimeError(f"Found {missing_edge_endpoints} missing edge endpoints")

    table_graph_ids["graph_nodes"] = len(node_ids)
    table_graph_ids["graph_edges"] = len(edge_graph_ids)
    if set(node_ids) != selected_graph_ids or edge_graph_ids != selected_graph_ids:
        raise RuntimeError("Not every sampled visit has both graph nodes and graph edges")

    return {
        "visit_count": len(visits),
        "unique_patient_count": int(visits["patient_id"].nunique()),
        "graph_counts": table_graph_ids,
        "duplicate_visit_keys": 0,
        "duplicate_graph_node_ids": 0,
        "missing_edge_endpoints": 0,
        "all_related_keys_within_sample": True,
    }


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {args.output}")
    if args.n_visits <= 0:
        raise ValueError("--n-visits must be positive")

    visits_path = args.input / "visits.csv"
    visits = pd.read_csv(visits_path, dtype=str, keep_default_na=False, encoding="utf-8")
    if args.n_visits > len(visits):
        raise ValueError(f"Requested {args.n_visits} visits from only {len(visits)} rows")
    if visits[["patient_id", "visit_id"]].duplicated().any():
        raise RuntimeError("Source visits.csv has duplicate (patient_id, visit_id) keys")

    sampled = visits.sample(n=args.n_visits, random_state=args.seed)
    sampled = sampled.sort_values(["patient_id", "visit_id"], kind="stable").reset_index(drop=True)
    selected_pairs = set(zip(sampled["patient_id"], sampled["visit_id"]))
    selected_graph_ids = set(sampled["primary_key"])

    args.output.mkdir(parents=True)
    write_csv(sampled, args.output / "visits.csv")
    key_frame = sampled[["patient_id", "visit_id", "primary_key"]].copy()
    key_frame = key_frame.rename(columns={"primary_key": "graph_id"})
    write_csv(key_frame, args.output / "sampled_visit_keys.csv")

    row_counts = {
        "visits.csv": len(sampled),
        "sampled_visit_keys.csv": len(key_frame),
    }
    for filename in TABLES_BY_VISIT_KEY + TABLES_BY_GRAPH_ID:
        rows, _ = filter_table(
            args.input / filename,
            args.output / filename,
            selected_pairs,
            selected_graph_ids,
            args.chunksize,
        )
        row_counts[filename] = rows

    validation = validate_preview(
        args.output, selected_pairs, selected_graph_ids, args.chunksize
    )
    manifest = collect_manifest(args.output, row_counts)
    write_csv(manifest, args.output / "manifest.csv")
    row_counts["manifest.csv"] = len(manifest)

    metadata = {
        "sampling_unit": "visit",
        "source_visit_count": len(visits),
        "sampled_visit_count": args.n_visits,
        "random_seed": args.seed,
        "sampling_method": "pandas.DataFrame.sample without replacement",
        "source_directory": str(args.input.resolve()),
        "row_counts": row_counts,
        "validation": validation,
    }
    (args.output / "preview_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
