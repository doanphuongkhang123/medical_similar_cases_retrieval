"""Small reusable models for the SCR embedding pipeline."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import torch
from torch import Tensor, nn


def l2_normalize(x: Tensor) -> Tensor:
    return x / x.norm(dim=-1, keepdim=True).clamp_min(1e-8)


def batch_lab_sequences(
    rows: Sequence[dict],
    device: torch.device,
) -> Tuple[Tensor, Tensor, Tensor, Tensor, Tensor]:
    """Pad variable-length lab sequences and return model-ready tensors."""
    if not rows:
        raise ValueError("Cannot batch an empty lab sequence batch")
    lengths = [max(1, len(row.get("item_indices") or [])) for row in rows]
    max_len = max(lengths)
    items = torch.zeros((len(rows), max_len), dtype=torch.long, device=device)
    values = torch.zeros((len(rows), max_len), dtype=torch.float32, device=device)
    times = torch.zeros((len(rows), max_len), dtype=torch.float32, device=device)
    abnormal = torch.zeros((len(rows), max_len), dtype=torch.float32, device=device)
    mask = torch.zeros((len(rows), max_len), dtype=torch.bool, device=device)
    for i, row in enumerate(rows):
        item_list = list(row.get("item_indices") or [])
        value_list = list(row.get("values_norm") or [])
        time_list = list(row.get("times_hours") or [])
        abnormal_list = list(row.get("is_abnormal") or [])
        n = min(len(item_list), max_len)
        if n == 0:
            continue
        items[i, :n] = torch.as_tensor(item_list[:n], dtype=torch.long, device=device)
        values[i, :n] = torch.as_tensor(value_list[:n], dtype=torch.float32, device=device)
        # Log time is more stable than raw hours for long admission windows.
        times[i, :n] = torch.log1p(torch.as_tensor(time_list[:n], dtype=torch.float32, device=device).clamp_min(0))
        abnormal[i, :n] = torch.as_tensor(abnormal_list[:n], dtype=torch.float32, device=device)
        mask[i, :n] = True
    return items, values, times, abnormal, mask


class LabGRUEncoder(nn.Module):
    """Encode irregular lab events using an item embedding and a GRU."""

    def __init__(
        self,
        vocab_size: int,
        item_dim: int = 64,
        hidden_dim: int = 256,
        num_layers: int = 1,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.vocab_size = int(vocab_size)
        self.item_dim = int(item_dim)
        self.hidden_dim = int(hidden_dim)
        self.num_layers = int(num_layers)
        self.item_embedding = nn.Embedding(self.vocab_size, self.item_dim, padding_idx=0)
        self.gru = nn.GRU(
            input_size=self.item_dim + 3,
            hidden_size=self.hidden_dim,
            num_layers=self.num_layers,
            batch_first=True,
            dropout=dropout if self.num_layers > 1 else 0.0,
        )

    @property
    def output_dim(self) -> int:
        return self.hidden_dim

    def forward(
        self,
        items: Tensor,
        values: Tensor,
        times: Tensor,
        abnormal: Tensor,
        mask: Tensor,
    ) -> Tensor:
        item_x = self.item_embedding(items)
        x = torch.cat([item_x, values.unsqueeze(-1), times.unsqueeze(-1), abnormal.unsqueeze(-1)], dim=-1)
        lengths = mask.sum(dim=1).clamp_min(1).to(torch.int64).cpu()
        packed = nn.utils.rnn.pack_padded_sequence(x, lengths, batch_first=True, enforce_sorted=False)
        _, hidden = self.gru(packed)
        return hidden[-1]


def checkpoint_config(checkpoint: Dict) -> Dict:
    return {
        "vocab_size": int(checkpoint["vocab_size"]),
        "item_dim": int(checkpoint["item_dim"]),
        "hidden_dim": int(checkpoint["hidden_dim"]),
        "num_layers": int(checkpoint.get("num_layers", 1)),
    }
