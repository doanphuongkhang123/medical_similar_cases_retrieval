#!/usr/bin/env python3
"""Rank patient candidates by agreement of three existing Top-20 retrievers."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
from typing import Any

import numpy as np

from common import sha256, write_json, write_jsonl


TOP_K = 20
QUERY_COUNT = 50
SELECTION_SEED = "terra_rerank_v1"
MODELS = ("fusion", "openai", "qwen3")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"Invalid JSONL object at {path}:{line_number}")
                yield value


def select_queries(ids: list[str], previous: list[str]) -> list[str]:
    selected = sorted(
        ids, key=lambda patient_id: hashlib.sha256(
            f"{SELECTION_SEED}:{patient_id}".encode()
        ).digest(),
    )[:QUERY_COUNT]
    if selected[:len(previous)] != previous or len(previous) != 10:
        raise ValueError("Previous ten queries do not match the pinned selection seed")
    return selected


def validate_top20(query_id: str, candidates: list[dict[str, Any]]) -> None:
    if len(candidates) != TOP_K:
        raise ValueError(f"{query_id}: expected 20 candidates")
    if [item.get("rank") for item in candidates] != list(range(1, TOP_K + 1)):
        raise ValueError(f"{query_id}: invalid ranks")
    ids = [item.get("patient_id") for item in candidates]
    if query_id in ids or len(set(ids)) != TOP_K:
        raise ValueError(f"{query_id}: self-match or duplicate candidate")
    scores = [item.get("cosine_similarity") for item in candidates]
    if any(type(score) not in (int, float) or not math.isfinite(score) for score in scores):
        raise ValueError(f"{query_id}: invalid cosine score")
    if any(left < right for left, right in zip(scores, scores[1:])):
        raise ValueError(f"{query_id}: Top 20 is not cosine-descending")


def rank_query(query_id: str, sources: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if set(sources) != set(MODELS):
        raise ValueError("Exactly three models are required")
    votes: dict[str, dict[str, dict[str, float | int]]] = {}
    for model in MODELS:
        candidates = sources[model]
        validate_top20(query_id, candidates)
        high = float(candidates[0]["cosine_similarity"])
        low = float(candidates[-1]["cosine_similarity"])
        for item in candidates:
            score = float(item["cosine_similarity"])
            normalized = (score - low) / (high - low) if high > low else 0.5
            votes.setdefault(item["patient_id"], {})[model] = {
                "rank": item["rank"],
                "cosine_similarity": score,
                "normalized_cosine": normalized,
            }

    def key(entry: tuple[str, dict[str, dict[str, float | int]]]):
        patient_id, by_model = entry
        vote_count = len(by_model)
        mean_rank = sum(item["rank"] for item in by_model.values()) / vote_count
        # Within the one-vote tier, compare normalized cosine. Exact ties use ID.
        one_vote_score = next(iter(by_model.values()))["normalized_cosine"] if vote_count == 1 else 0.0
        return (-vote_count, mean_rank if vote_count > 1 else -one_vote_score, patient_id)

    ordered = sorted(votes.items(), key=key)[:TOP_K]
    top20 = []
    for rank, (patient_id, by_model) in enumerate(ordered, 1):
        top20.append({
            "rank": rank,
            "patient_id": patient_id,
            "vote_count": len(by_model),
            "mean_source_rank": sum(item["rank"] for item in by_model.values()) / len(by_model),
            "model_scores": by_model,
        })
    return {
        "query_patient_id": query_id,
        "top20": top20,
        "unique_candidate_count": len(votes),
        "vote_counts_in_union": dict(sorted(Counter(len(value) for value in votes.values()).items())),
    }


def checked_manifest(root: Path, expected_status: str, expected_patients: int, raw_sha: str) -> dict[str, Any]:
    manifest = read_json(root / "manifest.json")
    if (manifest.get("status") != expected_status or
            manifest.get("patients") != expected_patients or
            manifest.get("raw_sha256") != raw_sha):
        raise ValueError(f"Unexpected source contract at {root}")
    return manifest


def run(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    qwen_root = args.qwen_root.resolve()
    openai_root = args.openai_root.resolve()
    terra_root = args.terra_root.resolve()
    fusion_root = args.fusion_root.resolve()
    identity_map = args.identity_map.resolve()
    raw_path = args.raw_workbook.resolve()
    ids = read_json(qwen_root / "patient_ids.json")
    if not isinstance(ids, list) or ids != sorted(ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid Qwen3 patient IDs")
    n = len(ids)
    raw_hash = sha256(raw_path)
    qwen_manifest = checked_manifest(qwen_root, "complete_not_clinically_validated", n, raw_hash)
    openai_manifest = checked_manifest(openai_root, "complete_not_clinically_validated", n, raw_hash)
    terra_manifest = checked_manifest(terra_root, "prepared_not_sent", n, raw_hash)
    if (qwen_manifest.get("model_id") != "Qwen/Qwen3-Embedding-0.6B" or
            openai_manifest.get("model") != "text-embedding-3-large" or
            qwen_manifest.get("input_sha256") != openai_manifest.get("input_sha256")):
        raise ValueError("Text embedding sources do not share the expected contract")
    for root, manifest in ((qwen_root, qwen_manifest), (openai_root, openai_manifest)):
        for filename, expected in manifest["outputs"].items():
            if sha256(root / filename) != expected:
                raise ValueError(f"Source SHA-256 mismatch: {root / filename}")
    if read_json(openai_root / "patient_ids.json") != ids:
        raise ValueError("Qwen3 and OpenAI patient IDs differ")

    selected_path = terra_root / "selected_queries.json"
    top100_path = terra_root / "top100_candidates.jsonl"
    for path in (selected_path, top100_path):
        if sha256(path) != terra_manifest["outputs"][path.name]:
            raise ValueError(f"Source SHA-256 mismatch: {path}")
    selected = select_queries(ids, read_json(selected_path))
    selected_set = set(selected)
    id_set = set(ids)
    id_to_index = {value: index for index, value in enumerate(ids)}

    input_bundle = qwen_root / "input_bundle"
    input_manifest = read_json(input_bundle / "manifest.json")
    if (input_manifest.get("raw_sha256") != raw_hash or
            input_manifest.get("raw_input") != str(raw_path) or
            input_manifest.get("output_sha256") != qwen_manifest.get("input_sha256")):
        raise ValueError("Raw workbook and patient bundle lineage differ")
    source_profiles = input_bundle / "source_profiles"
    profile_manifest = read_json(source_profiles / "manifest.json")
    if sha256(identity_map) != profile_manifest["artifacts"]["identity_map.jsonl"]:
        raise ValueError("Identity map SHA-256 mismatch")
    identity_rows = list(read_jsonl(identity_map))
    raw_to_profile = {str(row["patient_id"]): row["profile_id"] for row in identity_rows}
    if (len(identity_rows) != n or len(raw_to_profile) != n or
            set(raw_to_profile.values()) != id_set):
        raise ValueError("Identity map is not one-to-one")
    profile_to_raw = {profile: raw for raw, profile in raw_to_profile.items()}

    fusion_manifest = read_json(fusion_root / "manifest.json")
    fusion_path = fusion_root / "top20_related_patients.parquet"
    if (fusion_manifest.get("status") != "pass" or fusion_manifest.get("patients") != n or
            fusion_manifest.get("top_k") != TOP_K or
            fusion_manifest.get("self_matches_excluded") is not True or
            Path(fusion_manifest["outputs"]["parquet"]["path"]).resolve() != fusion_path or
            sha256(fusion_path) != fusion_manifest["outputs"]["parquet"]["sha256"]):
        raise ValueError("Fusion Top-20 artifact is invalid")
    import pandas as pd
    frame = pd.read_parquet(fusion_path, columns=[
        "query_patient_id", "rank", "related_patient_id", "cosine_similarity"
    ])
    if len(frame) != n * TOP_K:
        raise ValueError("Fusion artifact does not cover all patients")
    frame["query_patient_id"] = frame["query_patient_id"].astype(str)
    frame["related_patient_id"] = frame["related_patient_id"].astype(str)
    frame = frame[frame["query_patient_id"].isin({profile_to_raw[value] for value in selected})]
    fusion_by_query = {}
    for raw_query, group in frame.groupby("query_patient_id"):
        query_id = raw_to_profile[raw_query]
        candidates = [{
            "rank": int(row.rank),
            "patient_id": raw_to_profile[row.related_patient_id],
            "cosine_similarity": float(row.cosine_similarity),
        } for row in group.sort_values("rank").itertuples(index=False)]
        validate_top20(query_id, candidates)
        fusion_by_query[query_id] = candidates
    if set(fusion_by_query) != selected_set:
        raise ValueError("Fusion query set differs from selected queries")

    openai_by_query = {}
    seen_queries = set()
    for row in read_jsonl(top100_path):
        query_id = row["query_patient_id"]
        if query_id in seen_queries:
            raise ValueError("Duplicate OpenAI query")
        seen_queries.add(query_id)
        if query_id in selected_set:
            candidates = row["candidates"][:TOP_K]
            validate_top20(query_id, candidates)
            openai_by_query[query_id] = candidates
    if seen_queries != id_set or set(openai_by_query) != selected_set:
        raise ValueError("OpenAI Top-100 query coverage differs")

    queries = np.load(qwen_root / "query_embeddings.npy", allow_pickle=False)
    documents = np.load(qwen_root / "document_embeddings.npy", allow_pickle=False)
    if (queries.shape != (n, 1024) or documents.shape != (n, 1024) or
            queries.dtype != np.float32 or documents.dtype != np.float32 or
            not np.isfinite(queries).all() or not np.isfinite(documents).all() or
            not np.allclose(np.linalg.norm(queries, axis=1), 1, atol=1e-4) or
            not np.allclose(np.linalg.norm(documents, axis=1), 1, atol=1e-4)):
        raise ValueError("Qwen3 vector contract failed")
    results = []
    for query_id in selected:
        index = id_to_index[query_id]
        scores = documents @ queries[index]
        scores[index] = -np.inf
        order = np.argsort(-scores, kind="stable")[:TOP_K]
        qwen_candidates = [{
            "rank": rank, "patient_id": ids[candidate_index],
            "cosine_similarity": float(scores[candidate_index]),
        } for rank, candidate_index in enumerate(order.tolist(), 1)]
        results.append(rank_query(query_id, {
            "fusion": fusion_by_query[query_id],
            "openai": openai_by_query[query_id],
            "qwen3": qwen_candidates,
        }))

    output.mkdir(parents=True)
    results_path = output / "moe_vote_top20.jsonl"
    csv_path = output / "moe_vote_top20.csv"
    selected_out = output / "selected_queries.json"
    write_jsonl(results_path, results)
    write_json(selected_out, selected)
    fields = ["query_patient_id", "rank", "patient_id", "vote_count", "mean_source_rank"]
    for model in MODELS:
        fields.extend((f"{model}_rank", f"{model}_cosine", f"{model}_normalized_cosine"))
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            for item in result["top20"]:
                record = {key: item[key] for key in ("rank", "patient_id", "vote_count", "mean_source_rank")}
                record["query_patient_id"] = result["query_patient_id"]
                for model, score in item["model_scores"].items():
                    record[f"{model}_rank"] = score["rank"]
                    record[f"{model}_cosine"] = score["cosine_similarity"]
                    record[f"{model}_normalized_cosine"] = score["normalized_cosine"]
                writer.writerow(record)
    manifest = {
        "schema_version": 1,
        "status": "complete_not_clinically_validated",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "raw_input": str(raw_path), "raw_sha256": raw_hash,
        "query_count": QUERY_COUNT, "top_k_per_model": TOP_K, "top_k_output": TOP_K,
        "selection_seed": SELECTION_SEED, "previous_ten_queries": read_json(selected_path),
        "ranking": "vote_count descending; mean source rank ascending for multi-vote; min-max normalized cosine descending for one-vote; patient_id ascending for ties",
        "normalization": "Per query and model: (cosine - Top20 minimum) / (Top20 maximum - Top20 minimum); constant Top20 scores map to 0.5",
        "sources": {name: {"path": str(path), "sha256": sha256(path)} for name, path in {
            "fusion_manifest": fusion_root / "manifest.json",
            "fusion_parquet": fusion_path,
            "qwen_manifest": qwen_root / "manifest.json",
            "openai_manifest": openai_root / "manifest.json",
            "openai_top100": top100_path,
            "terra_manifest": terra_root / "manifest.json",
            "previous_selected_queries": selected_path,
            "identity_map": identity_map,
            "input_bundle_manifest": input_bundle / "manifest.json",
        }.items()},
        "code_sha256": sha256(Path(__file__)),
        "outputs": {path.name: sha256(path) for path in (results_path, csv_path, selected_out)},
    }
    write_json(output / "manifest.json", manifest)
    print(json.dumps({"output": str(output), "queries": len(results), "rows": sum(len(row["top20"]) for row in results), "vote_counts": dict(Counter(item["vote_count"] for row in results for item in row["top20"]))}))


def verify(output: Path) -> None:
    manifest = read_json(output / "manifest.json")
    if manifest.get("status") != "complete_not_clinically_validated" or manifest.get("query_count") != QUERY_COUNT:
        raise ValueError("Invalid output manifest")
    if sha256(Path(manifest["raw_input"])) != manifest["raw_sha256"]:
        raise ValueError("Raw input SHA-256 mismatch")
    for source in manifest["sources"].values():
        if sha256(Path(source["path"])) != source["sha256"]:
            raise ValueError(f"Source SHA-256 mismatch: {source['path']}")
    for filename, expected in manifest["outputs"].items():
        if sha256(output / filename) != expected:
            raise ValueError(f"Output SHA-256 mismatch: {filename}")
    selected = read_json(output / "selected_queries.json")
    results = list(read_jsonl(output / "moe_vote_top20.jsonl"))
    if len(selected) != QUERY_COUNT or [row["query_patient_id"] for row in results] != selected:
        raise ValueError("Query IDs or order differ")
    if selected[:10] != manifest["previous_ten_queries"]:
        raise ValueError("Previous ten queries differ")
    for row in results:
        candidates = row["top20"]
        if (len(candidates) != TOP_K or
                [item["rank"] for item in candidates] != list(range(1, TOP_K + 1)) or
                len({item["patient_id"] for item in candidates}) != TOP_K or
                row["query_patient_id"] in {item["patient_id"] for item in candidates}):
            raise ValueError("Invalid output candidate count, rank, or ID")
        previous_key = None
        for item in candidates:
            scores = item["model_scores"]
            if (set(scores) - set(MODELS) or len(scores) != item["vote_count"] or
                    not 1 <= item["vote_count"] <= 3 or
                    any(not math.isfinite(data["cosine_similarity"]) or
                            not 0 <= data["normalized_cosine"] <= 1 or
                            not 1 <= data["rank"] <= TOP_K for data in scores.values())):
                raise ValueError("Invalid model votes or scores")
            mean_rank = sum(data["rank"] for data in scores.values()) / len(scores)
            if item["mean_source_rank"] != mean_rank:
                raise ValueError("Mean source rank differs")
            singleton_score = next(iter(scores.values()))["normalized_cosine"] if len(scores) == 1 else 0
            key = (-len(scores), mean_rank if len(scores) > 1 else -singleton_score, item["patient_id"])
            if previous_key is not None and key < previous_key:
                raise ValueError("Voting order differs")
            previous_key = key
    with (output / "moe_vote_top20.csv").open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    if len(csv_rows) != QUERY_COUNT * TOP_K:
        raise ValueError("CSV row count differs")
    print(json.dumps({"status": "pass", "queries": len(results), "rows": len(results) * TOP_K, "output": str(output)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    for name in ("qwen-root", "openai-root", "terra-root", "fusion-root", "identity-map", "raw-workbook", "output"):
        run_parser.add_argument(f"--{name}", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args)
    else:
        verify(args.output.resolve())


if __name__ == "__main__":
    main()
