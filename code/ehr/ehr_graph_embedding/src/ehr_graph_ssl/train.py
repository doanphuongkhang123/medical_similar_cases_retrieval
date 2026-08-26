"""Train three structured-EHR graph self-supervised stages and export embeddings.

Stage 1: GT-BEHRT typed NAM + AID-MAE-style numeric dual masking.
Stage 2: Stage 1 plus GT-BEHRT Missing Node Prediction (MNP).
Stage 3: Stage 2 plus InfEHR-style VICReg and local-to-global MI.

This runner intentionally excludes clinical-note features and does not create
clinical similarity labels. It is designed for a single GPU with limited free
VRAM: graphs are processed sparsely and stage 3 uses dynamic small groups.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch
from torch import Tensor
import torch.nn.functional as F

from .data import GraphExample, RELATIONS, StructuredDataset, load_structured_dataset
from .model import StructuredGraphSSL
from .objectives import (
    choose_mask_indices,
    choose_mnp_index,
    corrupt_graph_for_mi,
    local_global_mi_loss,
    numeric_mask_loss,
    typed_nam_loss,
    VICRegStatisticsQueue,
    vicreg_mi_loss,
)


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _stable_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dataset_fingerprint(dataset: StructuredDataset) -> str:
    return _stable_fingerprint({
        "manifest": dataset.manifest,
        "vocab": dataset.vocab,
        "numeric_stats": dataset.numeric_stats,
        "idf": dataset.idf,
    })


def _device(value: str) -> torch.device:
    if value == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(value)


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _model_config(args: argparse.Namespace, dataset: StructuredDataset) -> dict[str, Any]:
    return {
        "vocab_size": len(dataset.vocab),
        "node_type_count": 5,
        "relation_count": len(RELATIONS),
        "hidden_dim": args.hidden_dim,
        "output_dim": args.output_dim,
        "layers": args.layers,
        "heads": args.heads,
        "dropout": args.dropout,
    }


def _autocast(device: torch.device, enabled: bool):
    if device.type == "cuda":
        return torch.autocast(device_type="cuda", dtype=torch.float16, enabled=enabled)
    return nullcontext()


def _base_objective(
    model: StructuredGraphSSL,
    example: GraphExample,
    dataset: StructuredDataset,
    args: argparse.Namespace,
    device: torch.device,
    rng: random.Random,
) -> tuple[Tensor, dict[str, float]]:
    concept_indices = choose_mask_indices(example, ratio=args.concept_mask_ratio, numeric_only=False, rng=rng)
    numeric_indices = choose_mask_indices(example, ratio=args.numeric_mask_ratio, numeric_only=True, rng=rng)
    graph = example.tensors(
        dataset.vocab, dataset.numeric_stats, device,
        concept_mask=concept_indices, numeric_mask=numeric_indices,
    )
    with _autocast(device, args.amp):
        hidden, _, _ = model(return_raw=True, **graph)
        nam = hidden.new_zeros(())
        numeric = hidden.new_zeros(())
        mnp = hidden.new_zeros(())
        if concept_indices:
            positions = torch.tensor(concept_indices, dtype=torch.long, device=device)
            targets = torch.tensor(
                [dataset.vocab.get(example.tokens[index], dataset.vocab["<UNK>"]) for index in concept_indices],
                dtype=torch.long,
                device=device,
            )
            nam = typed_nam_loss(model.concept_head(hidden[positions]), targets)
        if numeric_indices:
            positions = torch.tensor(numeric_indices, dtype=torch.long, device=device)
            numeric = numeric_mask_loss(model.numeric_head(hidden[positions]).squeeze(-1), graph["numeric_targets"][positions])
        if args.stage >= 2:
            removed = choose_mnp_index(example, dataset.idf, rng)
            if removed is not None:
                mnp_graph = example.tensors(dataset.vocab, dataset.numeric_stats, device, remove_index=removed)
                _, _, mnp_raw_embedding = model(return_raw=True, **mnp_graph)
                target = torch.tensor([dataset.vocab.get(example.tokens[removed], dataset.vocab["<UNK>"])], device=device)
                mnp = F.cross_entropy(model.mnp_head(mnp_raw_embedding).unsqueeze(0), target)
        loss = nam + args.numeric_weight * numeric + (args.mnp_weight * mnp if args.stage >= 2 else 0.0)
    return loss, {"nam": float(nam.detach()), "numeric": float(numeric.detach()), "mnp": float(mnp.detach())}


def _view_objective_inputs(
    example: GraphExample,
    dataset: StructuredDataset,
    args: argparse.Namespace,
    device: torch.device,
    rng: random.Random,
) -> tuple[dict[str, Tensor], dict[str, Tensor]]:
    # Feature masking is safe here because we retain all event nodes and all
    # business edges. Thus augmentation never removes the D/M/P core.
    one = example.tensors(
        dataset.vocab, dataset.numeric_stats, device,
        concept_mask=choose_mask_indices(example, ratio=args.view_mask_ratio, numeric_only=False, rng=rng),
        numeric_mask=choose_mask_indices(example, ratio=args.view_numeric_mask_ratio, numeric_only=True, rng=rng),
    )
    two = example.tensors(
        dataset.vocab, dataset.numeric_stats, device,
        concept_mask=choose_mask_indices(example, ratio=args.view_mask_ratio, numeric_only=False, rng=rng),
        numeric_mask=choose_mask_indices(example, ratio=args.view_numeric_mask_ratio, numeric_only=True, rng=rng),
    )
    return one, two


def _graph_groups(examples: Iterable[GraphExample], max_graphs: int, max_nodes: int) -> Iterable[list[GraphExample]]:
    group: list[GraphExample] = []
    total_nodes = 0
    for example in examples:
        if group and (len(group) >= max_graphs or total_nodes + example.node_count > max_nodes):
            yield group
            group, total_nodes = [], 0
        group.append(example)
        total_nodes += example.node_count
    if group:
        yield group


def _optimizer_step(
    optimizer: torch.optim.Optimizer,
    scaler: torch.amp.GradScaler | None,
    model: StructuredGraphSSL,
    loss: Tensor,
    args: argparse.Namespace,
) -> None:
    if scaler is not None:
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.gradient_clip)
        scaler.step(optimizer)
        scaler.update()
    else:
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.gradient_clip)
        optimizer.step()
    optimizer.zero_grad(set_to_none=True)


def _train_epoch(
    model: StructuredGraphSSL,
    dataset: StructuredDataset,
    optimizer: torch.optim.Optimizer,
    scaler: torch.amp.GradScaler | None,
    args: argparse.Namespace,
    device: torch.device,
    epoch: int,
) -> dict[str, float]:
    model.train()
    if device.type == "cuda":
        # Per-epoch process-local peak, used to make the bounded VRAM search
        # reproducible.  It does not include memory owned by other users.
        torch.cuda.reset_peak_memory_stats(device)
    examples = dataset.split_examples("train")
    rng = random.Random(args.seed + epoch)
    rng.shuffle(examples)
    totals: dict[str, float] = {
        "loss": 0.0, "nam": 0.0, "numeric": 0.0, "mnp": 0.0,
        "ssl": 0.0, "similarity": 0.0, "variance": 0.0,
        "covariance": 0.0, "mi": 0.0,
        "vicreg_stat_vector_count": 0.0,
        "vicreg_history_vector_count": 0.0,
        "vicreg_queue_warmup_group": 0.0,
        "vicreg_singleton_group": 0.0,
    }
    steps = 0
    if args.stage < 3:
        optimizer.zero_grad(set_to_none=True)
        for index, example in enumerate(examples, start=1):
            loss, components = _base_objective(model, example, dataset, args, device, rng)
            scaled_loss = loss / args.gradient_accumulation
            if scaler is not None:
                scaler.scale(scaled_loss).backward()
            else:
                scaled_loss.backward()
            totals["loss"] += float(loss.detach())
            for key, value in components.items():
                totals[key] += value
            if index % args.gradient_accumulation == 0 or index == len(examples):
                if scaler is not None:
                    scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.gradient_clip)
                if scaler is not None:
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            steps += 1
    else:
        # Reset each epoch: history is only a short-lived, detached FP32
        # moment estimator, not a persisted patient-level representation.
        statistics_queue = VICRegStatisticsQueue(args.vicreg_history_size, args.vicreg_max_stat_vectors)
        for group in _graph_groups(examples, args.ssl_max_graphs, args.ssl_max_nodes):
            optimizer.zero_grad(set_to_none=True)
            base_losses: list[Tensor] = []
            embeddings_one: list[Tensor] = []
            embeddings_two: list[Tensor] = []
            mi_losses: list[Tensor] = []
            group_components = {key: 0.0 for key in ("nam", "numeric", "mnp")}
            with _autocast(device, args.amp):
                for example in group:
                    base, components = _base_objective(model, example, dataset, args, device, rng)
                    base_losses.append(base)
                    for key, value in components.items():
                        group_components[key] += value
                    view_one, view_two = _view_objective_inputs(example, dataset, args, device, rng)
                    hidden_one, _, raw_one = model(return_raw=True, **view_one)
                    hidden_two, _, raw_two = model(return_raw=True, **view_two)
                    # The embedding contract discards any projector.
                    # Regularize the unnormalised encoder readout directly so
                    # VICReg's anti-collapse gradients govern what is exported.
                    embeddings_one.append(raw_one)
                    embeddings_two.append(raw_two)
                    corrupted_one = corrupt_graph_for_mi(view_one)
                    if corrupted_one is not None:
                        _, _, corrupted_raw_one = model(return_raw=True, **corrupted_one)
                        mi_losses.append(local_global_mi_loss(model, hidden_one, raw_one, corrupted_raw_one))
                    corrupted_two = corrupt_graph_for_mi(view_two)
                    if corrupted_two is not None:
                        _, _, corrupted_raw_two = model(return_raw=True, **corrupted_two)
                        mi_losses.append(local_global_mi_loss(model, hidden_two, raw_two, corrupted_raw_two))
            current_one = torch.stack(embeddings_one).float()
            current_two = torch.stack(embeddings_two).float()
            statistics_one, statistics_two, history_count = statistics_queue.statistics(current_one, current_two)
            # Moment estimates run in FP32 outside autocast.  Gradients still
            # flow through the current raw encoder readouts only.
            ssl, ssl_components = vicreg_mi_loss(
                current_one, current_two, mi_losses,
                statistics_one=statistics_one,
                statistics_two=statistics_two,
                similarity_weight=args.similarity_weight,
                variance_weight=args.variance_weight,
                covariance_weight=args.covariance_weight,
                mi_weight=args.mi_weight,
            )
            loss = torch.stack(base_losses).mean() + ssl
            _optimizer_step(optimizer, scaler, model, loss, args)
            statistics_queue.enqueue(current_one, current_two)
            totals["loss"] += float(loss.detach())
            totals["ssl"] += float(ssl.detach())
            for key, value in group_components.items():
                totals[key] += value / len(group)
            for key, value in ssl_components.items():
                totals[key] += float(value.detach())
            totals["vicreg_stat_vector_count"] += float(statistics_one.shape[0])
            totals["vicreg_history_vector_count"] += float(history_count)
            totals["vicreg_queue_warmup_group"] += float(
                args.vicreg_history_size > 0 and history_count < min(args.vicreg_history_size, max(0, args.vicreg_max_stat_vectors - len(group)))
            )
            totals["vicreg_singleton_group"] += float(len(group) == 1)
            steps += 1
    metrics = {key: value / max(1, steps) for key, value in totals.items()}
    if device.type == "cuda":
        metrics["cuda_peak_allocated_mib"] = torch.cuda.max_memory_allocated(device) / (1024**2)
        metrics["cuda_peak_reserved_mib"] = torch.cuda.max_memory_reserved(device) / (1024**2)
    return metrics


@torch.inference_mode()
def _validation_reconstruction(
    model: StructuredGraphSSL,
    dataset: StructuredDataset,
    args: argparse.Namespace,
    device: torch.device,
    epoch: int,
) -> dict[str, Any]:
    """Evaluate masked reconstruction on validation visits without optimization."""
    model.eval()
    rng = random.Random(args.seed + 1_000_000 + epoch)
    totals = {
        "loss": 0.0,
        "nam_loss": 0.0,
        "numeric_huber": 0.0,
        "numeric_absolute_error": 0.0,
        "mnp_loss": 0.0,
        "nam_count": 0,
        "nam_top1": 0,
        "nam_top5": 0,
        "numeric_count": 0,
        "mnp_count": 0,
        "mnp_top1": 0,
        "mnp_top5": 0,
    }
    examples = dataset.split_examples("validation")
    for example in examples:
        concept_indices = choose_mask_indices(example, ratio=args.concept_mask_ratio, numeric_only=False, rng=rng)
        numeric_indices = choose_mask_indices(example, ratio=args.numeric_mask_ratio, numeric_only=True, rng=rng)
        graph = example.tensors(
            dataset.vocab, dataset.numeric_stats, device,
            concept_mask=concept_indices, numeric_mask=numeric_indices,
        )
        with _autocast(device, args.amp):
            hidden, _, _ = model(return_raw=True, **graph)
            nam = hidden.new_zeros(())
            numeric = hidden.new_zeros(())
            mnp = hidden.new_zeros(())
            if concept_indices:
                positions = torch.tensor(concept_indices, dtype=torch.long, device=device)
                targets = torch.tensor(
                    [dataset.vocab.get(example.tokens[index], dataset.vocab["<UNK>"]) for index in concept_indices],
                    dtype=torch.long,
                    device=device,
                )
                logits = model.concept_head(hidden[positions])
                nam = typed_nam_loss(logits, targets)
                top = logits.topk(min(5, logits.shape[-1]), dim=-1).indices
                totals["nam_count"] += int(targets.numel())
                totals["nam_top1"] += int((top[:, 0] == targets).sum())
                totals["nam_top5"] += int((top == targets.unsqueeze(-1)).any(dim=-1).sum())
            if numeric_indices:
                positions = torch.tensor(numeric_indices, dtype=torch.long, device=device)
                predictions = model.numeric_head(hidden[positions]).squeeze(-1)
                targets = graph["numeric_targets"][positions]
                numeric = numeric_mask_loss(predictions, targets)
                totals["numeric_count"] += int(targets.numel())
                totals["numeric_absolute_error"] += float((predictions - targets).abs().sum())
            if args.stage >= 2:
                removed = choose_mnp_index(example, dataset.idf, rng)
                if removed is not None:
                    mnp_graph = example.tensors(dataset.vocab, dataset.numeric_stats, device, remove_index=removed)
                    _, _, raw_embedding = model(return_raw=True, **mnp_graph)
                    target = torch.tensor([dataset.vocab.get(example.tokens[removed], dataset.vocab["<UNK>"])], device=device)
                    logits = model.mnp_head(raw_embedding).unsqueeze(0)
                    mnp = F.cross_entropy(logits, target)
                    top = logits.topk(min(5, logits.shape[-1]), dim=-1).indices
                    totals["mnp_count"] += 1
                    totals["mnp_top1"] += int(top[0, 0] == target[0])
                    totals["mnp_top5"] += int((top[0] == target[0]).any())
            loss = nam + args.numeric_weight * numeric + (args.mnp_weight * mnp if args.stage >= 2 else 0.0)
        totals["loss"] += float(loss)
        totals["nam_loss"] += float(nam)
        totals["numeric_huber"] += float(numeric)
        totals["mnp_loss"] += float(mnp)
    count = max(1, len(examples))
    return {
        "reconstruction_loss": totals["loss"] / count,
        "nam_loss": totals["nam_loss"] / count,
        "numeric_huber_loss": totals["numeric_huber"] / count,
        "numeric_mae": totals["numeric_absolute_error"] / max(1, totals["numeric_count"]),
        "nam_accuracy_at_1": totals["nam_top1"] / max(1, totals["nam_count"]),
        "nam_recall_at_5": totals["nam_top5"] / max(1, totals["nam_count"]),
        "mnp_loss": totals["mnp_loss"] / count,
        "mnp_recall_at_1": None if totals["mnp_count"] == 0 else totals["mnp_top1"] / totals["mnp_count"],
        "mnp_recall_at_5": None if totals["mnp_count"] == 0 else totals["mnp_top5"] / totals["mnp_count"],
        "validation_graph_count": len(examples),
    }


def _ranks_from_scores(scores: np.ndarray, target_indices: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, axis=1, kind="stable")
    return (order == target_indices[:, None]).argmax(axis=1) + 1


def _export_embedding(
    model: StructuredGraphSSL,
    graph: dict[str, Tensor],
) -> Tensor:
    """Return the L2-normalized encoder readout exported for each visit."""
    _, embedding = model(**graph)
    return embedding


@torch.inference_mode()
def _validation_cross_view(
    model: StructuredGraphSSL,
    dataset: StructuredDataset,
    args: argparse.Namespace,
    device: torch.device,
    epoch: int,
) -> dict[str, Any]:
    """Cross-view retrieval against validation visits and a shuffled null."""
    model.eval()
    examples = dataset.split_examples("validation")
    if len(examples) < 2:
        return {
            "cross_view_recall_at_1": None,
            "cross_view_recall_at_5": None,
            "cross_view_recall_at_10": None,
            "cross_view_median_rank": None,
            "cross_view_shuffled_null_recall_at_1": None,
            "cross_view_recall_at_1_delta": None,
        }
    rng = random.Random(args.seed + 2_000_000 + epoch)
    first: list[np.ndarray] = []
    second: list[np.ndarray] = []
    for example in examples:
        one, two = _view_objective_inputs(example, dataset, args, device, rng)
        with _autocast(device, args.amp):
            embedding_one = _export_embedding(model, one)
            embedding_two = _export_embedding(model, two)
        first.append(embedding_one.float().cpu().numpy())
        second.append(embedding_two.float().cpu().numpy())
    scores = np.stack(first) @ np.stack(second).T
    targets = np.arange(len(examples), dtype=np.int64)
    ranks = _ranks_from_scores(scores, targets)
    # This has no fixed point, so it is an actual mismatched visit null.
    shift = 1 + ((args.seed + epoch) % (len(examples) - 1))
    shuffled_targets = np.roll(targets, shift)
    null_ranks = _ranks_from_scores(scores, shuffled_targets)
    recall_at_1 = float(np.mean(ranks <= 1))
    return {
        "cross_view_recall_at_1": recall_at_1,
        "cross_view_recall_at_5": float(np.mean(ranks <= 5)),
        "cross_view_recall_at_10": float(np.mean(ranks <= 10)),
        "cross_view_median_rank": float(np.median(ranks)),
        "cross_view_shuffled_null_recall_at_1": float(np.mean(null_ranks <= 1)),
        "cross_view_recall_at_1_delta": recall_at_1 - float(np.mean(null_ranks <= 1)),
    }


@torch.inference_mode()
def _embedding_frame(
    model: StructuredGraphSSL,
    dataset: StructuredDataset,
    device: torch.device,
    *,
    model_revision: str,
) -> pd.DataFrame:
    model.eval()
    rows: list[dict[str, Any]] = []
    for example in dataset.examples:
        graph = example.tensors(dataset.vocab, dataset.numeric_stats, device)
        embedding = _export_embedding(model, graph)
        counts = {name: sum(node == index for node in example.node_types) for index, name in enumerate(("VISIT", "DIAGNOSIS", "MEDICINE", "PROCEDURE", "OBSERVATION"))}
        rows.append({
            "visit_id": example.visit_id,
            "split": example.split,
            "snapshot_mode": "full_visit",
            "embedding_version": "ehr_graph_ssl_v1_structured",
            "embedding": embedding.detach().float().cpu().tolist(),
            "node_count_by_type": json.dumps(counts, sort_keys=True),
            "node_count": example.node_count,
            "augmentation_policy_version": "typed_masking_and_observation_dual_mask_v3_exact_time_bucket",
            "model_revision": model_revision,
        })
    return pd.DataFrame(rows)


def _finite_correlation(first: np.ndarray, second: np.ndarray) -> float | None:
    if len(first) < 2 or np.std(first) < 1e-12 or np.std(second) < 1e-12:
        return None
    return float(np.corrcoef(first, second)[0, 1])


def _embedding_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    """Compute representation diagnostics without deciding whether to accept it."""
    if frame.empty:
        raise ValueError("cannot compute embedding diagnostics from an empty frame")
    vectors = np.asarray(frame.embedding.tolist(), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1)
    finite = bool(np.isfinite(vectors).all())
    if finite:
        centered = vectors - vectors.mean(axis=0, keepdims=True)
        singular = np.linalg.svd(centered, compute_uv=False)
        energy = singular**2
        probabilities = energy / max(float(energy.sum()), 1e-12)
        effective_rank = float(np.exp(-(probabilities * np.log(np.maximum(probabilities, 1e-12))).sum()))
    else:
        effective_rank = 0.0
    node_counts = frame.node_count.to_numpy(dtype=np.float64)
    top1 = np.empty(len(vectors), dtype=np.int64)
    mean_similarity = np.empty(len(vectors), dtype=np.float64)
    all_similarity_sum = 0.0
    all_similarity_sq_sum = 0.0
    pair_count = 0
    for start in range(0, len(vectors), 512):
        end = min(len(vectors), start + 512)
        scores = vectors[start:end] @ vectors.T
        local_rows = np.arange(end - start)
        global_rows = np.arange(start, end)
        scores[local_rows, global_rows] = -np.inf
        top1[start:end] = scores.argmax(axis=1)
        finite_scores = scores[np.isfinite(scores)]
        all_similarity_sum += float(finite_scores.sum())
        all_similarity_sq_sum += float(np.square(finite_scores).sum())
        pair_count += int(finite_scores.size)
        mean_similarity[start:end] = np.where(np.isfinite(scores), scores, 0.0).sum(axis=1) / max(1, len(vectors) - 1)
    hub_counts = np.bincount(top1, minlength=len(vectors))
    top1_hub_fraction = float(hub_counts.max() / max(1, len(vectors)))
    similarity_mean = all_similarity_sum / max(1, pair_count)
    similarity_std = math.sqrt(max(0.0, all_similarity_sq_sum / max(1, pair_count) - similarity_mean**2))
    graph_size_correlation = _finite_correlation(mean_similarity, np.log1p(node_counts))
    effective_rank_target = vectors.shape[1] * 0.25
    return {
        "embedding_count": int(len(frame)),
        "finite": finite,
        "l2_norm_min": float(norms.min()),
        "l2_norm_max": float(norms.max()),
        "effective_rank": effective_rank,
        "effective_rank_target": effective_rank_target,
        "top1_hub_fraction": top1_hub_fraction,
        "cosine_pair_mean": similarity_mean,
        "cosine_pair_std": similarity_std,
        "graph_size_mean_similarity_correlation": graph_size_correlation,
    }


def _quality_report(frame: pd.DataFrame, validation: dict[str, Any]) -> dict[str, Any]:
    """Gate the export from validation only; retain all-split diagnostics separately."""
    validation_frame = frame.loc[frame.split.eq("validation")].reset_index(drop=True)
    if validation_frame.empty:
        raise ValueError("cannot gate embeddings without validation visits")
    validation_diagnostics = _embedding_diagnostics(validation_frame)
    all_split_diagnostics = _embedding_diagnostics(frame)
    cross_view_delta = validation.get("cross_view_recall_at_1_delta")
    gates = {
        "finite": validation_diagnostics["finite"],
        "l2_norm": bool(
            validation_diagnostics["l2_norm_min"] >= 1.0 - 1e-4
            and validation_diagnostics["l2_norm_max"] <= 1.0 + 1e-4
        ),
        "effective_rank": bool(
            validation_diagnostics["effective_rank"] >= validation_diagnostics["effective_rank_target"]
        ),
        "top1_hub": bool(validation_diagnostics["top1_hub_fraction"] <= 0.05),
        "graph_size_correlation": (
            validation_diagnostics["graph_size_mean_similarity_correlation"] is not None
            and abs(validation_diagnostics["graph_size_mean_similarity_correlation"]) < 0.20
        ),
        "cross_view_beats_shuffled_null": cross_view_delta is not None and cross_view_delta > 0.05,
        "note_length_correlation": "not_applicable_structured_only",
    }
    return {
        **validation_diagnostics,
        "quality_gate_split": "validation",
        "validation_embedding_diagnostics": validation_diagnostics,
        "all_split_descriptive": all_split_diagnostics,
        "validation_cross_view": {
            key: value for key, value in validation.items() if key.startswith("cross_view_")
        },
        "engineering_gates": gates,
        "engineering_gate_pass": all(value for value in gates.values() if isinstance(value, bool)),
        "scope": "engineering_proxy_only_not_clinical_validation",
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _save_checkpoint(
    path: Path,
    model: StructuredGraphSSL,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.ReduceLROnPlateau,
    dataset: StructuredDataset,
    config: dict[str, Any],
    stage: int,
    data_fingerprint: str,
    epoch: int,
    history: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "model_config": config,
        "stage": stage,
        "data_fingerprint": data_fingerprint,
        "vocab": dataset.vocab,
        "numeric_stats": dataset.numeric_stats,
        "idf": dataset.idf,
        "dataset_manifest": dataset.manifest,
        "epoch": epoch,
        "history": history,
    }, path)


def _load_checkpoint(path: Path, device: torch.device) -> dict[str, Any]:
    return torch.load(path, map_location=device, weights_only=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--epochs", type=int, default=20, help="maximum epochs; validation early stopping may finish sooner")
    parser.add_argument("--checkpoint", type=Path, help="required predecessor-stage checkpoint for stages 2 and 3")
    parser.add_argument("--limit-visits", type=int, default=0, help="deterministic smoke-test limit")
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--output-dim", type=int, default=256)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--heads", type=int, default=8)
    parser.add_argument("--dropout", type=float, default=0.15)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--scheduler-factor", type=float, default=0.5, help="ReduceLROnPlateau learning-rate multiplier")
    parser.add_argument("--scheduler-patience", type=int, default=2, help="validation plateaus before reducing learning rate")
    parser.add_argument("--min-learning-rate", type=float, default=1e-6)
    parser.add_argument("--early-stopping-patience", type=int, default=5, help="consecutive non-improving validation epochs before stopping")
    parser.add_argument("--early-stopping-min-delta", type=float, default=1e-4, help="minimum validation-loss decrease counted as improvement")
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--gradient-clip", type=float, default=1.0)
    parser.add_argument("--concept-mask-ratio", type=float, default=0.15)
    parser.add_argument("--numeric-mask-ratio", type=float, default=0.15)
    parser.add_argument("--numeric-weight", type=float, default=0.5)
    parser.add_argument("--mnp-weight", type=float, default=0.5)
    parser.add_argument("--view-mask-ratio", type=float, default=0.15)
    parser.add_argument("--view-numeric-mask-ratio", type=float, default=0.15)
    parser.add_argument("--similarity-weight", type=float, default=0.5)
    parser.add_argument("--variance-weight", type=float, default=0.5)
    parser.add_argument("--covariance-weight", type=float, default=0.05)
    parser.add_argument("--mi-weight", type=float, default=0.25)
    parser.add_argument("--ssl-max-graphs", type=int, default=2)
    parser.add_argument("--ssl-max-nodes", type=int, default=1200)
    parser.add_argument("--vicreg-history-size", type=int, default=0, help="detached FP32 history per view for variance/covariance only")
    parser.add_argument("--vicreg-max-stat-vectors", type=int, default=32, help="cap current plus detached VICReg statistic vectors per view")
    parser.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--export-embeddings", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.epochs <= 0 or args.gradient_accumulation <= 0:
        raise ValueError("epochs and gradient accumulation must be positive")
    if not 0.0 < args.scheduler_factor < 1.0:
        raise ValueError("scheduler factor must be strictly between 0 and 1")
    if args.scheduler_patience < 0 or args.early_stopping_patience <= 0:
        raise ValueError("scheduler patience must be non-negative and early-stopping patience positive")
    if args.min_learning_rate <= 0 or args.early_stopping_min_delta < 0:
        raise ValueError("minimum learning rate must be positive and early-stopping min delta non-negative")
    if args.vicreg_history_size < 0 or args.vicreg_max_stat_vectors <= 0:
        raise ValueError("VICReg history size must be non-negative and max statistic vectors positive")
    if args.stage < 3 and args.vicreg_history_size:
        raise ValueError("VICReg history is only valid for stage 3")
    if args.stage == 1 and args.checkpoint:
        raise ValueError("stage 1 starts from random initialization; do not supply --checkpoint")
    if args.stage > 1 and not args.checkpoint:
        raise ValueError(f"stage {args.stage} requires the immediately preceding stage checkpoint")
    if args.output.exists():
        non_log_entries = [path for path in args.output.iterdir() if path.name != "logs"]
        if non_log_entries:
            raise FileExistsError(f"Refusing to overwrite non-empty output directory: {args.output}")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
    _seed_everything(args.seed)
    device = _device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    if device.type == "cuda":
        torch.set_float32_matmul_precision("high")
    dataset = load_structured_dataset(args.data_root, seed=20260812, limit_visits=args.limit_visits)
    data_fingerprint = _dataset_fingerprint(dataset)
    model_config = _model_config(args, dataset)
    model = StructuredGraphSSL(**model_config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=args.scheduler_factor,
        patience=args.scheduler_patience,
        threshold=args.early_stopping_min_delta,
        threshold_mode="abs",
        min_lr=args.min_learning_rate,
    )
    if args.checkpoint:
        checkpoint = _load_checkpoint(args.checkpoint, device)
        if checkpoint.get("stage") != args.stage - 1:
            raise ValueError(
                f"checkpoint stage {checkpoint.get('stage')} is not the predecessor of requested stage {args.stage}"
            )
        old_config = checkpoint["model_config"]
        if old_config != model_config:
            raise ValueError("checkpoint model config does not match this run")
        if checkpoint["vocab"] != dataset.vocab:
            raise ValueError("checkpoint vocabulary does not match current train split/data")
        if checkpoint.get("data_fingerprint") != data_fingerprint:
            raise ValueError("checkpoint dataset fingerprint does not match current data/split/statistics")
        if checkpoint.get("numeric_stats") != dataset.numeric_stats or checkpoint.get("idf") != dataset.idf:
            raise ValueError("checkpoint numeric statistics or IDF do not match current train split/data")
        if checkpoint.get("dataset_manifest") != dataset.manifest:
            raise ValueError("checkpoint dataset manifest does not match current data/split")
        model.load_state_dict(checkpoint["model_state"], strict=True)
    amp_enabled = bool(args.amp and device.type == "cuda")
    scaler = torch.amp.GradScaler(device.type, enabled=amp_enabled) if amp_enabled else None
    run_manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, *sys.argv],
        "stage": args.stage,
        "structured_only": True,
        "clinical_note_features": False,
        "export_representation": "l2_normalized_encoder_readout",
        "stage3_ssl_representation": "unnormalized_encoder_readout" if args.stage == 3 else None,
        "optimization": {
            "optimizer": "AdamW",
            "initial_learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "scheduler": "ReduceLROnPlateau",
            "scheduler_factor": args.scheduler_factor,
            "scheduler_patience": args.scheduler_patience,
            "min_learning_rate": args.min_learning_rate,
            "early_stopping_metric": "validation.reconstruction_loss",
            "early_stopping_patience": args.early_stopping_patience,
            "early_stopping_min_delta": args.early_stopping_min_delta,
            "maximum_epochs": args.epochs,
        },
        "vicreg_statistics": {
            "history_size_per_view": args.vicreg_history_size if args.stage == 3 else 0,
            "max_stat_vectors_per_view": args.vicreg_max_stat_vectors if args.stage == 3 else 0,
            "history_detached": True,
            "statistics_dtype": "float32",
            "reset_policy": "each_epoch",
            "similarity_source": "current_group_only",
            "mi_source": "current_group_only",
        },
        "device": str(device),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "model": model_config,
        "dataset": dataset.manifest,
        "dataset_fingerprint": data_fingerprint,
        "source_references": {
            "gt_behrt": "third_party/gt-behrt @ d3d8384e0bea485095050ddafd5eb85e8db4c1f1 (reference only; no upstream license)",
            "infehr": "third_party/infehr @ 4b4fee76a67bd43388ad42c563688f60e65dfeb1 (Apache-2.0 objective adapted)",
            "aid_mae": "third_party/aid-mae @ 0b5995efa6b775b3d867dadce34926bcb8a947e1 (MIT dual-mask design adapted)",
        },
    }
    _json_write(args.output / "run_manifest.json", run_manifest)
    history: list[dict[str, Any]] = []
    best_validation_loss = float("inf")
    best_validation: dict[str, Any] | None = None
    best_epoch: int | None = None
    non_improving_epochs = 0
    stopped_early = False
    for epoch in range(1, args.epochs + 1):
        train_metrics = _train_epoch(model, dataset, optimizer, scaler, args, device, epoch)
        validation = {
            **_validation_reconstruction(model, dataset, args, device, epoch),
            **_validation_cross_view(model, dataset, args, device, epoch),
        }
        validation_loss = float(validation["reconstruction_loss"])
        improved = validation_loss < best_validation_loss - args.early_stopping_min_delta
        if improved:
            best_validation_loss = validation_loss
            best_validation = dict(validation)
            best_epoch = epoch
            non_improving_epochs = 0
        else:
            non_improving_epochs += 1
        scheduler.step(validation_loss)
        learning_rates = [float(group["lr"]) for group in optimizer.param_groups]
        record = {
            "epoch": epoch,
            "train": train_metrics,
            "validation": validation,
            "optimization": {
                "learning_rates": learning_rates,
                "validation_improved": improved,
                "non_improving_epochs": non_improving_epochs,
            },
        }
        history.append(record)
        _json_write(args.output / "history.json", {"history": history})
        _json_write(args.output / "validation_metrics.json", {"history": [item["validation"] for item in history]})
        print(json.dumps(record, sort_keys=True), flush=True)
        _save_checkpoint(
            args.output / "last.pt", model, optimizer, scheduler, dataset, model_config,
            args.stage, data_fingerprint, epoch, history,
        )
        if improved:
            _save_checkpoint(
                args.output / "best.pt", model, optimizer, scheduler, dataset, model_config,
                args.stage, data_fingerprint, epoch, history,
            )
        if non_improving_epochs >= args.early_stopping_patience:
            stopped_early = True
            print(json.dumps({
                "early_stopping": True,
                "epoch": epoch,
                "best_epoch": best_epoch,
                "best_validation_reconstruction_loss": best_validation_loss,
                "non_improving_epochs": non_improving_epochs,
            }, sort_keys=True), flush=True)
            break
    _json_write(args.output / "training_summary.json", {
        "epochs_requested": args.epochs,
        "epochs_completed": len(history),
        "stopped_early": stopped_early,
        "best_epoch": best_epoch,
        "best_validation_reconstruction_loss": best_validation_loss,
        "early_stopping_patience": args.early_stopping_patience,
        "early_stopping_min_delta": args.early_stopping_min_delta,
    })
    if args.export_embeddings:
        if best_validation is None:
            raise RuntimeError("no validation checkpoint was produced")
        best_checkpoint = _load_checkpoint(args.output / "best.pt", device)
        model.load_state_dict(best_checkpoint["model_state"], strict=True)
        revision = _file_sha256(args.output / "best.pt")
        frame = _embedding_frame(model, dataset, device, model_revision=revision)
        frame.to_parquet(args.output / "visit_embeddings.parquet", index=False)
        _json_write(args.output / "embedding_quality_report.json", _quality_report(frame, best_validation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
