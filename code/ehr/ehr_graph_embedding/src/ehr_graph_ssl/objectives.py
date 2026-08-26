"""Self-supervised objectives adapted from the paper reference implementations.

* NAM/MNP follow GT-BEHRT's visit-graph pretraining tasks.
* ``vicreg_mi_loss`` follows the similarity, variance, covariance and
  node-to-graph MI components in the Apache-2.0 InfEHR implementation.
* Numeric masking preserves AID-MAE's intrinsic-vs-augmented distinction:
  losses are computed only for observed values intentionally hidden by us.
"""
from __future__ import annotations

from collections import deque
import math
import random
from typing import Iterable

import torch
from torch import Tensor
import torch.nn.functional as F

from .data import GraphExample, MISSING_TIME_BUCKET, TYPE_TO_ID
from .model import StructuredGraphSSL


CORE_TYPE_IDS = {
    TYPE_TO_ID["DIAGNOSIS"],
    TYPE_TO_ID["MEDICINE"],
    TYPE_TO_ID["PROCEDURE"],
}


class VICRegStatisticsQueue:
    """Bounded detached history used only to stabilize VICReg moments.

    Historical vectors never carry autograd state.  Consequently this is a
    stale conditional moment estimator, *not* a claim that all statistics were
    computed from one fully differentiable batch.  Similarity and local/global
    MI remain current-group objectives.
    """

    def __init__(self, history_size: int, max_stat_vectors: int) -> None:
        if history_size < 0:
            raise ValueError("history_size must be non-negative")
        if max_stat_vectors <= 0:
            raise ValueError("max_stat_vectors must be positive")
        self.history_size = history_size
        self.max_stat_vectors = max_stat_vectors
        self._one: deque[Tensor] = deque(maxlen=history_size)
        self._two: deque[Tensor] = deque(maxlen=history_size)

    @property
    def history_count(self) -> int:
        return len(self._one)

    def reset(self) -> None:
        self._one.clear()
        self._two.clear()

    def statistics(self, current_one: Tensor, current_two: Tensor) -> tuple[Tensor, Tensor, int]:
        """Append a paired FIFO prefix to the current differentiable vectors."""
        if current_one.ndim != 2 or current_two.ndim != 2 or current_one.shape != current_two.shape:
            raise ValueError("current VICReg views must be paired rank-2 tensors")
        history_budget = max(0, self.max_stat_vectors - current_one.shape[0])
        take = min(self.history_count, history_budget)
        current_one = current_one.float()
        current_two = current_two.float()
        if take == 0:
            return current_one, current_two, 0
        history_one = torch.stack(list(self._one)[-take:])
        history_two = torch.stack(list(self._two)[-take:])
        return (
            torch.cat([history_one, current_one], dim=0),
            torch.cat([history_two, current_two], dim=0),
            take,
        )

    def enqueue(self, current_one: Tensor, current_two: Tensor) -> None:
        """Store current raw readouts after the optimizer step, without graphs."""
        if self.history_size == 0:
            return
        if current_one.ndim != 2 or current_two.ndim != 2 or current_one.shape != current_two.shape:
            raise ValueError("current VICReg views must be paired rank-2 tensors")
        for one, two in zip(current_one.detach().float().clone(), current_two.detach().float().clone()):
            self._one.append(one)
            self._two.append(two)


def choose_mask_indices(
    example: GraphExample,
    *,
    ratio: float,
    numeric_only: bool,
    rng: random.Random,
) -> list[int]:
    """Sample approximately ratio nodes per type without erasing a core type."""
    if numeric_only:
        numeric_targets = example.numeric_targets or example.numeric_values
        candidates = [
            index
            for index, value in enumerate(numeric_targets)
            if index
            and example.node_types[index] == TYPE_TO_ID["OBSERVATION"]
            and math.isfinite(value)
        ]
    else:
        candidates = list(range(1, example.node_count))
    if not candidates or ratio <= 0:
        return []
    by_type: dict[int, list[int]] = {}
    for index in candidates:
        by_type.setdefault(example.node_types[index], []).append(index)
    selected: list[int] = []
    for node_type, indices in sorted(by_type.items()):
        count = max(1, min(len(indices), round(len(indices) * ratio)))
        # Valid views retain at least one observable concept for each core type
        # that is present in the original graph.
        if not numeric_only and node_type in CORE_TYPE_IDS:
            count = min(count, len(indices) - 1)
        if count > 0:
            selected.extend(rng.sample(indices, count))
    return selected


def choose_mnp_index(example: GraphExample, idf: dict[str, float], rng: random.Random) -> int | None:
    """Choose one aggregated node with uniform type sampling then IDF sampling."""
    by_type: dict[int, list[int]] = {}
    for index in range(1, example.node_count):
        by_type.setdefault(example.node_types[index], []).append(index)
    candidate_types: list[int] = []
    for node_type, indices in by_type.items():
        # Removing the only Diagnosis/Medicine/Procedure node would create an
        # invalid MNP graph under the structured-view validator.
        if node_type in CORE_TYPE_IDS and len(indices) <= 1:
            continue
        candidate_types.append(node_type)
    if not candidate_types:
        return None
    node_type = rng.choice(sorted(candidate_types))
    candidates = by_type[node_type]
    weights = [idf.get(example.tokens[index], 1.0) for index in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def typed_nam_loss(logits: Tensor, target_ids: Tensor) -> Tensor:
    return F.cross_entropy(logits, target_ids)


def numeric_mask_loss(predictions: Tensor, targets: Tensor) -> Tensor:
    return F.smooth_l1_loss(predictions, targets)


def _off_diagonal(matrix: Tensor) -> Tensor:
    n, m = matrix.shape
    if n != m:
        raise ValueError("covariance matrix must be square")
    return matrix.flatten()[:-1].view(n - 1, n + 1)[:, 1:].flatten()


def _variance_loss(vectors: Tensor, eps: float = 1e-4) -> Tensor:
    if vectors.shape[0] < 2:
        return vectors.new_zeros(())
    std = torch.sqrt(vectors.var(dim=0, unbiased=False) + eps)
    return F.relu(1.0 - std).mean()


def _covariance_loss(vectors: Tensor) -> Tensor:
    if vectors.shape[0] < 2:
        return vectors.new_zeros(())
    centered = vectors - vectors.mean(dim=0, keepdim=True)
    covariance = centered.T @ centered / max(1, vectors.shape[0] - 1)
    return _off_diagonal(covariance).pow(2).sum() / vectors.shape[1]


def corrupt_graph_for_mi(graph: dict[str, Tensor]) -> dict[str, Tensor] | None:
    """Create an InfEHR-style negative by corrupting categorical input pre-encoder.

    The negative is deliberately not a valid augmentation. It retains the
    graph topology, node type, observed numeric value, and time, while
    permuting categorical identities only inside same-type, exact-24h buckets.
    Nodes without a timestamp are not corrupted because they do not belong to
    a defensible time window.
    This avoids the degenerate post-encoder permutation where positive and
    negative local/global scores are the same multiset.
    """
    concept_ids = graph["concept_ids"].clone()
    type_ids = graph["type_ids"]
    time_buckets = graph["time_buckets"]
    if concept_ids.shape[0] <= 2:
        return None
    groups: dict[tuple[int, int], list[int]] = {}
    for index, (node_type, bucket) in enumerate(zip(type_ids.tolist(), time_buckets.tolist())):
        if index == 0 or bucket == MISSING_TIME_BUCKET:
            continue
        groups.setdefault((int(node_type), int(bucket)), []).append(index)
    changed = False
    for indices in groups.values():
        if len(indices) < 2:
            continue
        selected = torch.tensor(indices, device=concept_ids.device, dtype=torch.long)
        shuffled = selected[torch.randperm(len(indices), device=concept_ids.device)]
        if torch.equal(selected, shuffled):
            shuffled = torch.roll(selected, shifts=1)
        candidate_values = concept_ids[shuffled]
        if not torch.equal(concept_ids[selected], candidate_values):
            concept_ids[selected] = candidate_values
            changed = True
    if not changed:
        return None
    corrupted = dict(graph)
    corrupted["concept_ids"] = concept_ids
    return corrupted


def local_global_mi_loss(
    model: StructuredGraphSSL,
    hidden: Tensor,
    positive_raw_embedding: Tensor,
    corrupted_raw_embedding: Tensor,
) -> Tensor:
    """Discriminate a real graph summary from a pre-encoder corrupted summary."""
    if hidden.shape[0] <= 2:
        return hidden.new_zeros(())
    local = model.local_projector(hidden[1:])
    positive_global = model.global_projector(positive_raw_embedding).unsqueeze(0)
    negative_global = model.global_projector(corrupted_raw_embedding).unsqueeze(0)
    positive_logits = model.mi_score(local, positive_global)
    negative_logits = model.mi_score(local, negative_global)
    return 0.5 * (
        F.binary_cross_entropy_with_logits(positive_logits, torch.ones_like(positive_logits))
        + F.binary_cross_entropy_with_logits(negative_logits, torch.zeros_like(negative_logits))
    )


def vicreg_mi_loss(
    current_one: Tensor,
    current_two: Tensor,
    mi_losses: Iterable[Tensor],
    *,
    statistics_one: Tensor | None = None,
    statistics_two: Tensor | None = None,
    similarity_weight: float = 0.5,
    variance_weight: float = 0.5,
    covariance_weight: float = 0.05,
    mi_weight: float = 0.25,
) -> tuple[Tensor, dict[str, Tensor]]:
    """InfEHR-style graph-level SSL, with optional detached moment history."""
    if (statistics_one is None) != (statistics_two is None):
        raise ValueError("both VICReg statistic tensors must be supplied together")
    statistic_one = current_one if statistics_one is None else statistics_one
    statistic_two = current_two if statistics_two is None else statistics_two
    similarity = F.mse_loss(current_one, current_two)
    variance = _variance_loss(statistic_one) + _variance_loss(statistic_two)
    covariance = _covariance_loss(statistic_one) + _covariance_loss(statistic_two)
    mi_values = list(mi_losses)
    mutual_information = torch.stack(mi_values).float().mean() if mi_values else similarity.new_zeros(())
    total = (
        similarity_weight * similarity
        + variance_weight * variance
        + covariance_weight * covariance
        + mi_weight * mutual_information
    )
    return total, {
        "similarity": similarity,
        "variance": variance,
        "covariance": covariance,
        "mi": mutual_information,
    }


def structured_core_type_counts(example: GraphExample) -> dict[str, int]:
    return {
        name: sum(type_id == TYPE_TO_ID[name] for type_id in example.node_types)
        for name in ("DIAGNOSIS", "MEDICINE", "PROCEDURE")
    }
