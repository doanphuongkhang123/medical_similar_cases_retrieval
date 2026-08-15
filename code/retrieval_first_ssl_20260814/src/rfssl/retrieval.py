"""Exact/FAISS candidate-pool construction for validated visit embeddings.

This module deliberately stops at an unlabeled candidate pool. It does not
infer clinical relevance, create pseudo-labels, or expose raw EHR text.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd


REQUIRED_EMBEDDING_COLUMNS = {
    "visit_id",
    "split",
    "snapshot_mode",
    "embedding_version",
    "embedding",
    "node_count_by_type",
    "node_count",
    "augmentation_policy_version",
    "model_revision",
}


@dataclass(frozen=True)
class NeighborResult:
    indices: np.ndarray
    scores: np.ndarray
    backend: str


def load_passing_embeddings(embeddings_path: Path, quality_report_path: Path) -> tuple[pd.DataFrame, np.ndarray]:
    """Read one validated embedding artifact and reject a failed quality gate."""
    quality = json.loads(quality_report_path.read_text(encoding="utf-8"))
    if not quality.get("engineering_gate_pass", False):
        raise ValueError(
            "Refusing candidate generation: embedding_quality_report does not pass engineering gates"
        )
    frame = pd.read_parquet(embeddings_path)
    missing = REQUIRED_EMBEDDING_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"embedding artifact is missing required columns: {sorted(missing)}")
    if frame.visit_id.duplicated().any():
        raise ValueError("embedding artifact contains duplicate visit_id values")
    if frame.embedding_version.nunique() != 1 or frame.snapshot_mode.nunique() != 1:
        raise ValueError("candidate pool must contain one embedding version and one snapshot mode")
    vectors = np.asarray(frame.embedding.tolist(), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] < 2 or not np.isfinite(vectors).all():
        raise ValueError("embedding matrix must be finite and contain at least two visits")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.all(np.abs(norms - 1.0) <= 1e-4):
        raise ValueError("embeddings must be L2-normalized before cosine/IP retrieval")
    return frame, vectors


def _topk_numpy(vectors: np.ndarray, top_k: int, chunk_size: int = 512) -> NeighborResult:
    count = len(vectors)
    k = min(top_k, count - 1)
    result_indices = np.empty((count, k), dtype=np.int64)
    result_scores = np.empty((count, k), dtype=np.float32)
    for start in range(0, count, chunk_size):
        end = min(count, start + chunk_size)
        scores = vectors[start:end] @ vectors.T
        scores[np.arange(end - start), np.arange(start, end)] = -np.inf
        candidates = np.argpartition(-scores, kth=k - 1, axis=1)[:, :k]
        candidate_scores = np.take_along_axis(scores, candidates, axis=1)
        order = np.argsort(-candidate_scores, axis=1, kind="stable")
        result_indices[start:end] = np.take_along_axis(candidates, order, axis=1)
        result_scores[start:end] = np.take_along_axis(candidate_scores, order, axis=1)
    return NeighborResult(indices=result_indices, scores=result_scores, backend="numpy_exact_ip")


def _topk_faiss(vectors: np.ndarray, top_k: int, index_path: Path) -> NeighborResult:
    try:
        import faiss
    except ImportError as error:
        raise RuntimeError(
            "FAISS is not installed in scr_env. Install a compatible faiss package or use --allow-exact-numpy."
        ) from error
    count, dimension = vectors.shape
    k = min(top_k, count - 1)
    index = faiss.IndexFlatIP(dimension)
    index.add(np.ascontiguousarray(vectors))
    search_scores, search_indices = index.search(np.ascontiguousarray(vectors), k + 1)
    result_indices = np.empty((count, k), dtype=np.int64)
    result_scores = np.empty((count, k), dtype=np.float32)
    for row in range(count):
        keep = [position for position, candidate in enumerate(search_indices[row]) if candidate != row][:k]
        if len(keep) != k:
            raise RuntimeError("FAISS search did not return enough non-self candidates")
        result_indices[row] = search_indices[row, keep]
        result_scores[row] = search_scores[row, keep]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))
    return NeighborResult(indices=result_indices, scores=result_scores, backend="faiss_index_flat_ip")


def nearest_neighbors(
    vectors: np.ndarray,
    *,
    top_k: int,
    backend: Literal["faiss", "numpy"] = "faiss",
    index_path: Path | None = None,
) -> NeighborResult:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if len(vectors) <= 1:
        raise ValueError("at least two vectors are required")
    if backend == "numpy":
        return _topk_numpy(vectors, top_k)
    if index_path is None:
        raise ValueError("index_path is required for the FAISS backend")
    return _topk_faiss(vectors, top_k, index_path)


def _counts(value: str) -> dict[str, int]:
    parsed = json.loads(value)
    return {str(key): int(number) for key, number in parsed.items()}


def candidate_frame(frame: pd.DataFrame, neighbors: NeighborResult) -> pd.DataFrame:
    """Materialize top-k candidates plus explanation metadata, never self hits."""
    rows: list[dict[str, Any]] = []
    count_maps = [_counts(value) for value in frame.node_count_by_type]
    for query_index, (candidate_indices, scores) in enumerate(zip(neighbors.indices, neighbors.scores)):
        query = frame.iloc[query_index]
        for rank, (candidate_index, score) in enumerate(zip(candidate_indices, scores), start=1):
            if int(candidate_index) == query_index:
                raise RuntimeError("self candidate escaped retrieval filtering")
            candidate = frame.iloc[int(candidate_index)]
            shared = {
                node_type: min(count_maps[query_index].get(node_type, 0), count_maps[int(candidate_index)].get(node_type, 0))
                for node_type in ("DIAGNOSIS", "MEDICINE", "PROCEDURE", "OBSERVATION")
            }
            rows.append({
                "query_visit_id": query.visit_id,
                "candidate_visit_id": candidate.visit_id,
                "rank": rank,
                "cosine_similarity": float(score),
                "embedding_version": query.embedding_version,
                "snapshot_mode": query.snapshot_mode,
                "shared_node_type_counts": json.dumps(shared, sort_keys=True),
                "graph_size_query": int(query.node_count),
                "graph_size_candidate": int(candidate.node_count),
            })
    return pd.DataFrame(rows)

