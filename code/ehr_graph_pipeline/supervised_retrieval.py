"""Label-aware visit retrieval utilities.

This module deliberately does not infer clinical similarity from diagnosis,
outcome, or code overlap.  Reviewed pair labels are supplied separately and
used only in the explicitly requested split.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from ehr_common import write_json

PAIR_COLUMNS = {"query_visit_id", "candidate_visit_id", "relevance", "partition"}


def _vectors(frame: pd.DataFrame) -> np.ndarray:
    vectors = np.asarray(frame.embedding.tolist(), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(frame):
        raise ValueError("embedding must contain one same-length numeric vector per visit")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("zero-norm embeddings cannot be used for cosine retrieval")
    return vectors / norms


def load_embeddings(path: Path) -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.read_parquet(path).copy()
    required = {"visit_id", "split", "embedding"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"embedding file is missing columns: {sorted(missing)}")
    if frame.visit_id.duplicated().any():
        raise ValueError("visit_id must be unique in the embedding file")
    return frame, _vectors(frame)


def load_pairs(path: Path) -> pd.DataFrame:
    pairs = pd.read_parquet(path).copy()
    missing = PAIR_COLUMNS.difference(pairs.columns)
    if missing:
        raise ValueError(f"reviewed pair file is missing columns: {sorted(missing)}")
    if pairs.relevance.isna().any() or (pairs.relevance < 0).any():
        raise ValueError("relevance must be a non-negative reviewed numeric label")
    if (pairs.query_visit_id == pairs.candidate_visit_id).any():
        raise ValueError("a visit cannot be judged against itself")
    return pairs


def candidate_frame(frame: pd.DataFrame, vectors: np.ndarray, query_split: str, reference_split: str, top_k: int, random_k: int, seed: int) -> pd.DataFrame:
    queries = np.flatnonzero(frame.split.to_numpy() == query_split)
    references = np.flatnonzero(frame.split.to_numpy() == reference_split)
    if not len(queries) or not len(references):
        raise ValueError("query and reference splits must both contain embeddings")
    rng = random.Random(seed)
    rows: list[dict] = []
    for query_index in queries:
        usable = references[references != query_index]
        scores = vectors[usable] @ vectors[query_index]
        order = np.argsort(-scores)
        chosen = order[: min(top_k, len(order))]
        used = set(chosen.tolist())
        remaining = [index for index in order.tolist() if index not in used]
        sampled = rng.sample(remaining, min(random_k, len(remaining)))
        for rank, local_index in enumerate(chosen, start=1):
            candidate_index = usable[local_index]
            rows.append({"query_visit_id": frame.visit_id.iloc[query_index], "candidate_visit_id": frame.visit_id.iloc[candidate_index], "source": "baseline_top_k", "candidate_rank": rank, "baseline_cosine": float(scores[local_index])})
        for local_index in sampled:
            candidate_index = usable[local_index]
            rows.append({"query_visit_id": frame.visit_id.iloc[query_index], "candidate_visit_id": frame.visit_id.iloc[candidate_index], "source": "random_control", "candidate_rank": None, "baseline_cosine": float(scores[local_index])})
    return pd.DataFrame(rows)


def _pair_arrays(pairs: pd.DataFrame, frame: pd.DataFrame, vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    positions = pd.Series(np.arange(len(frame)), index=frame.visit_id)
    unknown = set(pairs.query_visit_id).union(pairs.candidate_visit_id).difference(positions.index)
    if unknown:
        raise ValueError(f"pair file references visits missing from embeddings ({len(unknown)} IDs)")
    return (
        vectors[positions.loc[pairs.query_visit_id].to_numpy()],
        vectors[positions.loc[pairs.candidate_visit_id].to_numpy()],
        pairs.relevance.to_numpy(dtype=np.float32),
    )


def fit_projection(frame: pd.DataFrame, vectors: np.ndarray, pairs: pd.DataFrame, dimension: int, epochs: int, learning_rate: float, seed: int, device: str) -> tuple[dict, dict]:
    train_pairs = pairs[pairs.partition == "train"].copy()
    if train_pairs.empty:
        raise ValueError("pair labels must contain partition=train for supervised fine-tuning")
    split_lookup = frame.set_index("visit_id").split
    if not (split_lookup.loc[train_pairs.query_visit_id].eq("train").all() and split_lookup.loc[train_pairs.candidate_visit_id].eq("train").all()):
        raise ValueError("partition=train pairs must use only train embeddings")
    left, right, relevance = _pair_arrays(train_pairs, frame, vectors)
    maximum = float(relevance.max())
    if maximum <= 0:
        raise ValueError("training requires at least one positive reviewed relevance label")
    if not 0 < dimension <= vectors.shape[1]:
        raise ValueError("projection dimension must be positive and no larger than embedding dimension")
    torch.manual_seed(seed)
    projection = torch.nn.Linear(vectors.shape[1], dimension, bias=False).to(device)
    with torch.no_grad():
        projection.weight.zero_()
        projection.weight[:, :dimension] = torch.eye(dimension, device=device)
    optimizer = torch.optim.AdamW(projection.parameters(), lr=learning_rate)
    left_t, right_t, target_t = (torch.tensor(value, dtype=torch.float32, device=device) for value in (left, right, relevance / maximum))
    history = []
    for epoch in range(1, epochs + 1):
        projected_left = F.normalize(projection(left_t), dim=1)
        projected_right = F.normalize(projection(right_t), dim=1)
        loss = F.mse_loss((projected_left * projected_right).sum(dim=1), target_t)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        history.append({"epoch": epoch, "pair_mse": float(loss.detach().cpu())})
    checkpoint = {"projection": projection.state_dict(), "input_dimension": int(vectors.shape[1]), "output_dimension": dimension, "maximum_relevance": maximum}
    manifest = {"objective": "graded_pairwise_cosine_regression", "label_source": "externally_reviewed_pair_labels", "seed": seed, "epochs": epochs, "learning_rate": learning_rate, "train_pairs": len(train_pairs), "relevance_counts": {str(key): int(value) for key, value in train_pairs.relevance.value_counts().sort_index().items()}, "history": history, "patient_disjoint_status": "must be verified by the supplied split; visit_id alone cannot prove this"}
    return checkpoint, manifest


def project(frame: pd.DataFrame, vectors: np.ndarray, checkpoint: dict, device: str) -> pd.DataFrame:
    if vectors.shape[1] != checkpoint["input_dimension"]:
        raise ValueError("projection checkpoint dimension does not match embeddings")
    layer = torch.nn.Linear(checkpoint["input_dimension"], checkpoint["output_dimension"], bias=False).to(device)
    layer.load_state_dict(checkpoint["projection"])
    with torch.inference_mode():
        output = F.normalize(layer(torch.tensor(vectors, dtype=torch.float32, device=device)), dim=1).cpu().numpy().astype(np.float32)
    result = frame.copy()
    result["embedding"] = output.tolist()
    result["embedding_version"] = "supervised_pair_projection_v0.1"
    return result


def ranking_metrics(frame: pd.DataFrame, vectors: np.ndarray, pairs: pd.DataFrame, partition: str, ks: list[int]) -> dict:
    judged = pairs[pairs.partition == partition].copy()
    if judged.empty:
        raise ValueError(f"no judged pairs found for partition={partition}")
    positions = pd.Series(np.arange(len(frame)), index=frame.visit_id)
    metrics = {name: [] for k in ks for name in (f"precision_at_{k}", f"map_at_{k}", f"ndcg_at_{k}")}
    for _, group in judged.groupby("query_visit_id", sort=False):
        query = positions.loc[group.query_visit_id.iloc[0]]
        candidates = positions.loc[group.candidate_visit_id].to_numpy()
        scores = vectors[candidates] @ vectors[query]
        relevance = group.relevance.to_numpy(dtype=np.float32)[np.argsort(-scores)]
        for k in ks:
            at_k = relevance[:k]
            metrics[f"precision_at_{k}"].append(float(np.count_nonzero(at_k > 0) / k))
            hits = (at_k > 0).astype(np.float32)
            precision = np.cumsum(hits) / np.arange(1, len(hits) + 1)
            denominator = min(np.count_nonzero(relevance > 0), k)
            metrics[f"map_at_{k}"].append(float((precision * hits).sum() / denominator) if denominator else 0.0)
            discounts = np.log2(np.arange(2, len(at_k) + 2))
            dcg = float(((2 ** at_k - 1) / discounts).sum())
            ideal = np.sort(relevance)[::-1][:k]
            idcg = float(((2 ** ideal - 1) / np.log2(np.arange(2, len(ideal) + 2))).sum())
            metrics[f"ndcg_at_{k}"].append(dcg / idcg if idcg else 0.0)
    return {"evaluation_scope": "judged_candidate_set_only", "partition": partition, "queries": int(judged.query_visit_id.nunique()), "judged_pairs": len(judged), "metrics": {name: float(np.mean(values)) for name, values in metrics.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, fine-tune, and evaluate label-aware visit retrieval.")
    sub = parser.add_subparsers(dest="command", required=True)
    candidates = sub.add_parser("candidates", help="Create annotation candidates; this command creates no labels.")
    candidates.add_argument("--embeddings", type=Path, required=True); candidates.add_argument("--output", type=Path, required=True)
    candidates.add_argument("--query-split", default="validation"); candidates.add_argument("--reference-split", default="train")
    candidates.add_argument("--top-k", type=int, default=20); candidates.add_argument("--random-k", type=int, default=10); candidates.add_argument("--seed", type=int, default=20260814)
    fit = sub.add_parser("fit", help="Fit a projection only from externally reviewed train pairs.")
    fit.add_argument("--embeddings", type=Path, required=True); fit.add_argument("--pairs", type=Path, required=True); fit.add_argument("--output", type=Path, required=True)
    fit.add_argument("--dimension", type=int, default=128); fit.add_argument("--epochs", type=int, default=100); fit.add_argument("--learning-rate", type=float, default=1e-3); fit.add_argument("--seed", type=int, default=20260814); fit.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    project_parser = sub.add_parser("project", help="Apply the trained projection to all embeddings.")
    project_parser.add_argument("--embeddings", type=Path, required=True); project_parser.add_argument("--checkpoint", type=Path, required=True); project_parser.add_argument("--output", type=Path, required=True); project_parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    evaluate = sub.add_parser("evaluate", help="Evaluate rankings only among explicitly judged candidates.")
    evaluate.add_argument("--embeddings", type=Path, required=True); evaluate.add_argument("--pairs", type=Path, required=True); evaluate.add_argument("--output", type=Path, required=True); evaluate.add_argument("--partition", default="test"); evaluate.add_argument("--ks", default="1,3,5,10")
    args = parser.parse_args()
    frame, vectors = load_embeddings(args.embeddings)
    if args.command == "candidates":
        result = candidate_frame(frame, vectors, args.query_split, args.reference_split, args.top_k, args.random_k, args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True); result.to_parquet(args.output, index=False)
        write_json(args.output.with_suffix(".manifest.json"), {"purpose": "annotation_candidate_generation", "labels_created": False, "query_split": args.query_split, "reference_split": args.reference_split, "top_k": args.top_k, "random_k": args.random_k, "seed": args.seed, "pairs": len(result)})
    elif args.command == "fit":
        checkpoint, manifest = fit_projection(frame, vectors, load_pairs(args.pairs), args.dimension, args.epochs, args.learning_rate, args.seed, args.device)
        args.output.parent.mkdir(parents=True, exist_ok=True); torch.save(checkpoint, args.output); write_json(args.output.with_suffix(".manifest.json"), manifest)
    elif args.command == "project":
        checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True); result = project(frame, vectors, checkpoint, args.device)
        args.output.parent.mkdir(parents=True, exist_ok=True); result.to_parquet(args.output, index=False)
        write_json(args.output.with_suffix(".manifest.json"), {"checkpoint": str(args.checkpoint), "embedding_dimension": checkpoint["output_dimension"], "l2_normalized": True, "clinical_retrieval_validated": False})
    else:
        report = ranking_metrics(frame, vectors, load_pairs(args.pairs), args.partition, [int(value) for value in args.ks.split(",")])
        args.output.parent.mkdir(parents=True, exist_ok=True); write_json(args.output, report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
