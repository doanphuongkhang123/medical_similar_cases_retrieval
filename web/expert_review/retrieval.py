"""Exact retrieval over full-dataset fused EHR and clinical-note embeddings.

The fusion contract follows ``multimodal_retrieval/retrieve_similar_cases.py``:
each modality is L2-normalized, weighted, concatenated, and normalized again.
The web app intentionally omits image embeddings so every EHR visit remains
eligible instead of restricting the pool to visits with linked images.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def clean_id(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _normalize_rows(matrix: np.ndarray, source: str) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError(f"{source} must be a two-dimensional matrix")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or np.any(norms <= 1e-12):
        raise ValueError(f"{source} contains zero or non-finite embeddings")
    return matrix / norms


def _parse_vector(value: Any, source: str) -> np.ndarray:
    if isinstance(value, str):
        text = value.strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = ast.literal_eval(text)
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError(f"Invalid embedding in {source}")
    return vector


def _stack_vectors(values: list[Any], source: str) -> np.ndarray:
    vectors = [_parse_vector(value, source) for value in values]
    if not vectors:
        raise ValueError(f"No embeddings found in {source}")
    dimensions = {vector.size for vector in vectors}
    if len(dimensions) != 1:
        raise ValueError(f"Inconsistent embedding dimensions in {source}")
    return np.stack(vectors).astype(np.float32, copy=False)


def _load_ehr(path: Path) -> tuple[np.ndarray, np.ndarray]:
    frame = pd.read_parquet(path, columns=["visit_id", "embedding"])
    ids = frame["visit_id"].map(clean_id).to_numpy(dtype=object)
    if np.any(ids == "") or len(set(ids.tolist())) != len(ids):
        raise ValueError(f"Invalid or duplicate visit_id in {path}")
    matrix = _stack_vectors(frame["embedding"].tolist(), str(path))
    return ids, _normalize_rows(matrix, str(path))


def _wide_embedding_columns(columns: list[str]) -> list[str]:
    numbered: list[tuple[int, str]] = []
    for column in columns:
        if not column.startswith("embedding_"):
            continue
        suffix = column.removeprefix("embedding_")
        if suffix.isdigit():
            numbered.append((int(suffix), column))
    return [column for _, column in sorted(numbered)]


def _load_text(path: Path) -> tuple[np.ndarray, np.ndarray]:
    if path.suffix.casefold() == ".parquet":
        frame = pd.read_parquet(path)
    else:
        header = pd.read_csv(path, nrows=0)
        wide_columns = _wide_embedding_columns([str(c) for c in header.columns])
        use_columns = ["visit_id", *wide_columns]
        if not wide_columns and "embedding" in header.columns:
            use_columns.append("embedding")
        frame = pd.read_csv(path, usecols=use_columns, dtype={"visit_id": str})

    if "visit_id" not in frame.columns:
        raise ValueError(f"{path} is missing visit_id")
    frame["visit_id"] = frame["visit_id"].map(clean_id)
    if (frame["visit_id"] == "").any():
        raise ValueError(f"Empty visit_id in {path}")

    wide_columns = _wide_embedding_columns([str(c) for c in frame.columns])
    if wide_columns:
        numeric = frame[wide_columns].apply(pd.to_numeric, errors="raise")
        numeric.insert(0, "visit_id", frame["visit_id"])
        grouped = numeric.groupby("visit_id", sort=True, as_index=False).mean()
        ids = grouped["visit_id"].to_numpy(dtype=object)
        matrix = grouped[wide_columns].to_numpy(dtype=np.float32)
    elif "embedding" in frame.columns:
        grouped_vectors: dict[str, list[np.ndarray]] = {}
        for visit_id, value in zip(frame["visit_id"], frame["embedding"]):
            grouped_vectors.setdefault(visit_id, []).append(
                _parse_vector(value, str(path))
            )
        ids = np.asarray(sorted(grouped_vectors), dtype=object)
        pooled = [
            np.mean(np.stack(grouped_vectors[visit_id]), axis=0, dtype=np.float32)
            for visit_id in ids.tolist()
        ]
        matrix = np.stack(pooled)
    else:
        raise ValueError(f"{path} has no embedding column")
    return ids, _normalize_rows(matrix, str(path))


@dataclass(frozen=True)
class RetrievalResult:
    rank: int
    candidate_visit_id: str
    score: float


class FusedRetrievalIndex:
    def __init__(self, ids: np.ndarray, matrix: np.ndarray, *, config: dict[str, Any]):
        self.ids = np.asarray(ids, dtype=object)
        self.matrix = np.asarray(matrix, dtype=np.float32)
        if self.matrix.shape[0] != len(self.ids):
            raise ValueError("IDs and fused matrix have incompatible shapes")
        self._id_to_index = {
            str(visit_id): index for index, visit_id in enumerate(self.ids.tolist())
        }
        self.config = dict(config)

    @classmethod
    def from_files(
        cls,
        ehr_path: Path,
        text_path: Path,
        *,
        ehr_weight: float = 1.0,
        text_weight: float = 1.0,
    ) -> "FusedRetrievalIndex":
        if ehr_weight <= 0 or text_weight <= 0:
            raise ValueError("Fusion weights must be positive")
        ehr_ids, ehr_matrix = _load_ehr(ehr_path)
        text_ids, text_matrix = _load_text(text_path)
        text_index = {
            str(visit_id): index for index, visit_id in enumerate(text_ids.tolist())
        }
        common_ids = [
            str(visit_id) for visit_id in ehr_ids.tolist() if str(visit_id) in text_index
        ]
        if not common_ids:
            raise ValueError("EHR and text embeddings share no visit IDs")
        ehr_index = {
            str(visit_id): index for index, visit_id in enumerate(ehr_ids.tolist())
        }
        ehr_block = ehr_matrix[[ehr_index[visit_id] for visit_id in common_ids]]
        text_block = text_matrix[[text_index[visit_id] for visit_id in common_ids]]
        fused = np.concatenate(
            [ehr_block * ehr_weight, text_block * text_weight], axis=1
        )
        fused = _normalize_rows(fused, "fused EHR+text embedding")
        return cls(
            np.asarray(common_ids, dtype=object),
            fused,
            config={
                "algorithm": "exact_cosine",
                "modalities": ["ehr_graph", "clinical_note"],
                "ehr_weight": float(ehr_weight),
                "text_weight": float(text_weight),
                "ehr_dimension": int(ehr_block.shape[1]),
                "text_dimension": int(text_block.shape[1]),
                "fused_dimension": int(fused.shape[1]),
                "visit_count": len(common_ids),
                "ehr_source": str(ehr_path),
                "text_source": str(text_path),
            },
        )

    def __contains__(self, visit_id: str) -> bool:
        return clean_id(visit_id) in self._id_to_index

    def retrieve(self, query_visit_id: str, *, k: int = 20) -> list[RetrievalResult]:
        query_visit_id = clean_id(query_visit_id)
        if query_visit_id not in self._id_to_index:
            raise KeyError(
                f"Visit {query_visit_id!r} is not in the fused full-dataset index"
            )
        if k <= 0:
            raise ValueError("k must be positive")
        query_index = self._id_to_index[query_visit_id]
        scores = self.matrix @ self.matrix[query_index]
        scores[query_index] = -np.inf
        count = min(k, len(self.ids) - 1)
        shortlist = np.argpartition(-scores, count - 1)[:count]
        order = np.lexsort((self.ids[shortlist].astype(str), -scores[shortlist]))
        return [
            RetrievalResult(
                rank=rank,
                candidate_visit_id=str(self.ids[int(shortlist[local_index])]),
                score=float(scores[int(shortlist[local_index])]),
            )
            for rank, local_index in enumerate(order, start=1)
        ]
