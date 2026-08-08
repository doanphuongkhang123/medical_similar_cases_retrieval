#!/usr/bin/env python3
"""Retrieve top-k admissions from a saved SCR embedding parquet file."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--embeddings", type=Path, required=True)
    p.add_argument("--query-hadm-id", type=int, required=True)
    p.add_argument("--embedding-column", default="fused_embedding", choices=("text_embedding", "lab_embedding", "fused_embedding"))
    p.add_argument("--candidate-split", default="train", choices=("train", "val", "test", "all"))
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--output", type=Path, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rows = pq.read_table(args.embeddings).to_pylist()
    query = next((row for row in rows if int(row["hadm_id"]) == args.query_hadm_id), None)
    if query is None:
        raise ValueError(f"hadm_id {args.query_hadm_id} is not present in {args.embeddings}")
    query_vector = np.asarray(query[args.embedding_column], dtype=np.float32)
    query_vector /= max(float(np.linalg.norm(query_vector)), 1e-8)
    candidates = [
        row for row in rows
        if int(row["hadm_id"]) != args.query_hadm_id
        and (args.candidate_split == "all" or str(row["split"]) == args.candidate_split)
    ]
    if not candidates:
        raise ValueError("Candidate set is empty; choose another --candidate-split")
    matrix = np.asarray([row[args.embedding_column] for row in candidates], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True).clip(min=1e-8)
    scores = matrix @ query_vector
    order = np.argsort(-scores)[: args.top_k]
    result = []
    for rank, index in enumerate(order, start=1):
        row = candidates[int(index)]
        result.append({
            "query_hadm_id": args.query_hadm_id,
            "rank": rank,
            "candidate_hadm_id": int(row["hadm_id"]),
            "candidate_subject_id": int(row["subject_id"]),
            "candidate_split": str(row["split"]),
            "has_lab_events": bool(row.get("has_lab_events", False)),
            "cosine_similarity": float(scores[int(index)]),
        })
    for row in result:
        print(f"{row['rank']:>3}  hadm_id={row['candidate_hadm_id']}  cosine={row['cosine_similarity']:.5f}  has_lab={row['has_lab_events']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.unlink(missing_ok=True)
        pq.write_table(pa.Table.from_pylist(result), args.output, compression="zstd")


if __name__ == "__main__":
    main()
