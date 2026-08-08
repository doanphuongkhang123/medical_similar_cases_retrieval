#!/usr/bin/env python3
"""Train the lab GRU to align each admission's labs with its cached text embedding."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pyarrow.parquet as pq
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader

from scr_models import LabGRUEncoder, batch_lab_sequences, l2_normalize

LOG = logging.getLogger("train_lab_encoder")


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--text-embeddings", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--item-dim", type=int, default=64)
    p.add_argument("--hidden-dim", type=int, default=256)
    p.add_argument("--learning-rate", type=float, default=1e-3)
    p.add_argument("--temperature", type=float, default=0.07)
    p.add_argument("--device", default="auto")
    return p.parse_args()


def device(value: str) -> torch.device:
    return torch.device("cuda" if value == "auto" and torch.cuda.is_available() else ("cpu" if value == "auto" else value))


def main() -> None:
    cfg = args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dev = device(cfg.device)
    samples = pq.read_table(cfg.input / "samples.parquet").to_pylist()
    seqs = {int(row["hadm_id"]): row for row in pq.read_table(cfg.input / "lab_sequences.parquet").to_pylist()}
    texts = {int(row["hadm_id"]): row for row in pq.read_table(cfg.text_embeddings).to_pylist()}
    rows = [
        (seqs[int(sample["hadm_id"])], texts[int(sample["hadm_id"])])
        for sample in samples
        if str(sample["split"]) == "train" and int(sample["hadm_id"]) in seqs and int(sample["hadm_id"]) in texts
    ]
    if len(rows) < 2:
        raise RuntimeError("Need at least two training admissions with both labs and text embeddings")
    vocab = json.loads((cfg.input / "lab_vocab.json").read_text())
    vocab_size = max([1] + [int(value) for value in vocab.get("itemid_to_index", {}).values()]) + 1
    model = LabGRUEncoder(vocab_size, item_dim=cfg.item_dim, hidden_dim=cfg.hidden_dim).to(dev)
    text_dim = len(rows[0][1]["embedding"])
    projection = nn.Linear(cfg.hidden_dim, text_dim).to(dev)
    optimizer = torch.optim.AdamW(list(model.parameters()) + list(projection.parameters()), lr=cfg.learning_rate)
    generator = torch.Generator().manual_seed(42)
    loader = DataLoader(rows, batch_size=cfg.batch_size, shuffle=True, generator=generator, collate_fn=lambda x: x)
    model.train(); projection.train()
    for epoch in range(cfg.epochs):
        losses = []
        for batch in loader:
            lab_rows = [pair[0] for pair in batch]
            text = torch.tensor([pair[1]["embedding"] for pair in batch], dtype=torch.float32, device=dev)
            tensors = batch_lab_sequences(lab_rows, dev)
            lab = l2_normalize(projection(model(*tensors)))
            text = l2_normalize(text)
            logits = lab @ text.T / cfg.temperature
            target = torch.arange(len(batch), device=dev)
            loss = (F.cross_entropy(logits, target) + F.cross_entropy(logits.T, target)) / 2
            optimizer.zero_grad(); loss.backward(); optimizer.step()
            losses.append(float(loss.detach().cpu()))
        LOG.info("epoch=%d loss=%.4f", epoch + 1, sum(losses) / max(len(losses), 1))
    cfg.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state": model.state_dict(),
        "vocab_size": vocab_size,
        "item_dim": cfg.item_dim,
        "hidden_dim": cfg.hidden_dim,
        "num_layers": 1,
        "text_dim": text_dim,
        "projection_state": projection.state_dict(),
        "objective": "symmetric in-batch text-lab InfoNCE",
    }, cfg.output)
    LOG.info("Saved lab checkpoint to %s", cfg.output)


if __name__ == "__main__":
    main()
