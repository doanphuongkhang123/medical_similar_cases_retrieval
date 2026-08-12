"""Compact relation-aware sparse Graph Transformer for a single visit graph."""
from __future__ import annotations

from typing import Iterable

import torch
from torch import Tensor, nn
import torch.nn.functional as F


def _segment_softmax(scores: Tensor, destinations: Tensor, node_count: int) -> Tensor:
    """Per-destination softmax without a Python loop over graph nodes."""
    expanded = destinations.unsqueeze(-1).expand_as(scores)
    maximum = torch.full((node_count, scores.shape[1]), -torch.inf, dtype=scores.dtype, device=scores.device)
    maximum.scatter_reduce_(0, expanded, scores, reduce="amax", include_self=True)
    exponent = torch.exp(scores - maximum[destinations])
    denominator = torch.zeros_like(maximum)
    denominator.scatter_add_(0, expanded, exponent)
    return exponent / denominator[destinations].clamp_min(torch.finfo(scores.dtype).tiny)


class RelationAttentionLayer(nn.Module):
    def __init__(self, dimension: int, heads: int, relation_count: int, dropout: float) -> None:
        super().__init__()
        if dimension % heads:
            raise ValueError("hidden dimension must be divisible by attention heads")
        self.heads, self.head_dim = heads, dimension // heads
        self.query, self.key, self.value = nn.Linear(dimension, dimension), nn.Linear(dimension, dimension), nn.Linear(dimension, dimension)
        self.relation = nn.Embedding(relation_count, heads)
        self.output = nn.Linear(dimension, dimension)
        self.norm = nn.LayerNorm(dimension)
        self.dropout = nn.Dropout(dropout)

    def forward(self, hidden: Tensor, sources: Tensor, destinations: Tensor, relation_ids: Tensor) -> Tensor:
        query = self.query(hidden).view(-1, self.heads, self.head_dim)
        key = self.key(hidden).view(-1, self.heads, self.head_dim)
        value = self.value(hidden).view(-1, self.heads, self.head_dim)
        score = (query[destinations] * key[sources]).sum(-1) / self.head_dim**0.5 + self.relation(relation_ids)
        weight = _segment_softmax(score, destinations, hidden.shape[0])
        messages = value[sources] * weight.unsqueeze(-1)
        aggregated = torch.zeros_like(value)
        aggregated.index_add_(0, destinations, messages)
        updated = self.output(aggregated.flatten(1))
        return self.norm(hidden + self.dropout(F.gelu(updated)))


class GTBEHRTVisit(nn.Module):
    def __init__(self, vocab_size: int, node_type_count: int, relation_count: int, hidden_dimension: int = 256, output_dimension: int = 256, layers: int = 2, heads: int = 4, dropout: float = 0.2) -> None:
        super().__init__()
        self.concepts = nn.Embedding(vocab_size, 64)
        self.node_types = nn.Embedding(node_type_count, 16)
        self.numeric = nn.Sequential(nn.Linear(2, 32), nn.GELU(), nn.Linear(32, 32))
        self.input = nn.Sequential(nn.Linear(112, hidden_dimension), nn.GELU(), nn.LayerNorm(hidden_dimension))
        self.layers = nn.ModuleList([RelationAttentionLayer(hidden_dimension, heads, relation_count, dropout) for _ in range(layers)])
        self.pool_query = nn.Linear(hidden_dimension, hidden_dimension, bias=False)
        self.concept_head = nn.Linear(hidden_dimension, vocab_size)
        self.readout = nn.Sequential(nn.Linear(hidden_dimension * 2, hidden_dimension), nn.GELU(), nn.Linear(hidden_dimension, output_dimension))

    def encode(self, concept_ids: Tensor, node_type_ids: Tensor, numeric_values: Tensor, time_hours: Tensor, sources: Tensor, destinations: Tensor, relation_ids: Tensor) -> Tensor:
        continuous = torch.stack((numeric_values, torch.tanh(time_hours / 24)), dim=-1)
        hidden = self.input(torch.cat((self.concepts(concept_ids), self.node_types(node_type_ids), self.numeric(continuous)), dim=-1))
        for layer in self.layers:
            hidden = layer(hidden, sources, destinations, relation_ids)
        return hidden

    def forward(self, concept_ids: Tensor, node_type_ids: Tensor, numeric_values: Tensor, time_hours: Tensor, sources: Tensor, destinations: Tensor, relation_ids: Tensor) -> Tensor:
        hidden = self.encode(concept_ids, node_type_ids, numeric_values, time_hours, sources, destinations, relation_ids)
        visit = hidden[0]
        if len(hidden) == 1:
            pooled = visit
        else:
            weights = torch.softmax((self.pool_query(hidden[1:]) * visit).sum(-1) / visit.shape[0]**0.5, dim=0)
            pooled = (weights.unsqueeze(-1) * hidden[1:]).sum(0)
        return F.normalize(self.readout(torch.cat((visit, pooled))), dim=0)
