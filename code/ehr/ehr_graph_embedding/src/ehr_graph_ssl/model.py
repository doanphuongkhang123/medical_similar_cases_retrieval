"""Relation-aware sparse Graph Transformer used by the structured SSL stages.

The VISIT token and typed masked-concept objectives follow GT-BEHRT's visit
graph idea.  The model deliberately keeps typed business relations rather than
replacing them with the homogeneous graph used by the InfEHR reference code.
"""
from __future__ import annotations

import math

import torch
from torch import Tensor, nn
import torch.nn.functional as F

from .data import FEATURE_DIMENSION


def _segment_softmax(scores: Tensor, destinations: Tensor, node_count: int) -> Tensor:
    """Softmax over incoming sparse edges for each destination node/head."""
    expanded = destinations.unsqueeze(-1).expand_as(scores)
    maximum = torch.full((node_count, scores.shape[1]), -torch.inf, dtype=scores.dtype, device=scores.device)
    maximum.scatter_reduce_(0, expanded, scores, reduce="amax", include_self=True)
    exponent = torch.exp(scores - maximum[destinations])
    denominator = torch.zeros_like(maximum)
    denominator.scatter_add_(0, expanded, exponent)
    return exponent / denominator[destinations].clamp_min(torch.finfo(scores.dtype).tiny)


class RelationAttentionLayer(nn.Module):
    def __init__(self, hidden_dim: int, heads: int, relation_count: int, dropout: float) -> None:
        super().__init__()
        if hidden_dim % heads:
            raise ValueError("hidden_dim must be divisible by heads")
        self.heads = heads
        self.head_dim = hidden_dim // heads
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.relation_key = nn.Embedding(relation_count, hidden_dim)
        self.relation_value = nn.Embedding(relation_count, hidden_dim)
        self.output = nn.Linear(hidden_dim, hidden_dim)
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.feed_forward = nn.Sequential(
            nn.Linear(hidden_dim, 4 * hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * hidden_dim, hidden_dim),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        hidden: Tensor,
        sources: Tensor,
        destinations: Tensor,
        relation_ids: Tensor,
    ) -> Tensor:
        residual = hidden
        normalized = self.norm1(hidden)
        query = self.query(normalized).reshape(-1, self.heads, self.head_dim)
        key = self.key(normalized).reshape(-1, self.heads, self.head_dim)
        value = self.value(normalized).reshape(-1, self.heads, self.head_dim)
        # Embedding lookup weights remain fp32 under autocast, while projected
        # node activations may be fp16.  Align dtypes before sparse aggregation.
        relation_key = self.relation_key(relation_ids).reshape(-1, self.heads, self.head_dim).to(query.dtype)
        relation_value = self.relation_value(relation_ids).reshape(-1, self.heads, self.head_dim).to(value.dtype)
        scores = (query[destinations] * (key[sources] + relation_key)).sum(dim=-1) / math.sqrt(self.head_dim)
        attention = self.dropout(_segment_softmax(scores, destinations, hidden.shape[0]))
        messages = (value[sources] + relation_value) * attention.unsqueeze(-1)
        # PyTorch may promote sparse-attention messages under autocast even when
        # Q/K/V are fp16.  Allocate from the actual message dtype, then restore
        # the residual dtype before the skip connection.
        aggregated = torch.zeros(
            (hidden.shape[0], self.heads, self.head_dim),
            dtype=messages.dtype,
            device=messages.device,
        )
        aggregated.index_add_(0, destinations, messages)
        update = self.output(aggregated.reshape(hidden.shape[0], -1)).to(residual.dtype)
        hidden = residual + self.dropout(update)
        return hidden + self.dropout(self.feed_forward(self.norm2(hidden)))


class StructuredGraphSSL(nn.Module):
    """GT-BEHRT-style graph encoder plus heads for NAM, MNP and numeric MAE."""

    def __init__(
        self,
        *,
        vocab_size: int,
        node_type_count: int,
        relation_count: int,
        hidden_dim: int = 256,
        output_dim: int = 256,
        layers: int = 4,
        heads: int = 8,
        dropout: float = 0.15,
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.concept_embedding = nn.Embedding(vocab_size, 96)
        self.type_embedding = nn.Embedding(node_type_count, 32)
        self.numeric_encoder = nn.Sequential(
            nn.Linear(FEATURE_DIMENSION, 64), nn.GELU(), nn.LayerNorm(64), nn.Linear(64, 64), nn.GELU()
        )
        self.input_projection = nn.Sequential(
            nn.Linear(96 + 32 + 64, hidden_dim), nn.GELU(), nn.LayerNorm(hidden_dim)
        )
        self.layers = nn.ModuleList(
            RelationAttentionLayer(hidden_dim, heads, relation_count, dropout) for _ in range(layers)
        )
        self.type_query = nn.Parameter(torch.empty(node_type_count, hidden_dim))
        nn.init.normal_(self.type_query, std=0.02)
        self.readout = nn.Sequential(
            # [VISIT || pooled diagnosis || medicine || procedure || observation].
            # VISIT itself is intentionally not pooled a second time.
            nn.Linear(hidden_dim * node_type_count, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, output_dim),
        )
        self.concept_head = nn.Linear(hidden_dim, vocab_size)
        self.mnp_head = nn.Linear(output_dim, vocab_size)
        self.numeric_head = nn.Sequential(nn.LayerNorm(hidden_dim), nn.Linear(hidden_dim, 1))
        # Kept solely to load the stage-2 predecessor checkpoint strictly.
        # The embedding contract regularizes and exports the encoder
        # readout itself, so stage 3 deliberately does not call this projector.
        self.ssl_projector = nn.Sequential(
            nn.Linear(output_dim, output_dim), nn.GELU(), nn.Linear(output_dim, output_dim)
        )
        # InfEHR-style local/global discriminator; it is trained only in stage 3.
        self.local_projector = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.GELU(), nn.Linear(hidden_dim, hidden_dim))
        self.global_projector = nn.Sequential(nn.Linear(output_dim, hidden_dim), nn.GELU(), nn.Linear(hidden_dim, hidden_dim))
        self.mi_matrix = nn.Parameter(torch.empty(hidden_dim, hidden_dim))
        nn.init.xavier_uniform_(self.mi_matrix)

    def encode(
        self,
        concept_ids: Tensor,
        type_ids: Tensor,
        numeric: Tensor,
        sources: Tensor,
        destinations: Tensor,
        relation_ids: Tensor,
    ) -> tuple[Tensor, Tensor, Tensor]:
        hidden = self.input_projection(torch.cat([
            self.concept_embedding(concept_ids), self.type_embedding(type_ids), self.numeric_encoder(numeric)
        ], dim=-1))
        for layer in self.layers:
            hidden = layer(hidden, sources, destinations, relation_ids)
        pools: list[Tensor] = []
        # A separate type pool exists for event types only; type 0 is the
        # VISIT virtual node and is concatenated directly below.
        for type_id in range(1, self.type_embedding.num_embeddings):
            positions = torch.nonzero(type_ids == type_id, as_tuple=False).flatten()
            if not len(positions):
                pools.append(torch.zeros(self.hidden_dim, device=hidden.device, dtype=hidden.dtype))
                continue
            values = hidden[positions]
            scores = (values * self.type_query[type_id]).sum(dim=-1)
            pools.append((F.softmax(scores, dim=0).unsqueeze(-1) * values).sum(dim=0))
        visit = hidden[0]
        raw_embedding = self.readout(torch.cat([visit, *pools], dim=-1))
        embedding = F.normalize(raw_embedding, dim=-1)
        return hidden, embedding, raw_embedding

    def mi_score(self, local_features: Tensor, global_features: Tensor) -> Tensor:
        """Bilinear local/global score used by the InfEHR-style discriminator."""
        return ((local_features @ self.mi_matrix) * global_features).sum(dim=-1) / math.sqrt(self.hidden_dim)

    def forward(self, *, return_projector: bool = False, return_raw: bool = False, **graph: Tensor):
        hidden, embedding, raw_embedding = self.encode(
            graph["concept_ids"], graph["type_ids"], graph["numeric"],
            graph["sources"], graph["destinations"], graph["relation_ids"],
        )
        if return_projector:
            return hidden, embedding, self.ssl_projector(raw_embedding)
        if return_raw:
            return hidden, embedding, raw_embedding
        return hidden, embedding
