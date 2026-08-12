"""Stage-1 GT-BEHRT masked concept pretraining on train visit graphs."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd
import torch
import torch.nn.functional as F
import yaml

from build_visit_graphs import NODE_TYPES
from embed_visits import tensorize
from gt_behrt_visit import GTBEHRTVisit
from ehr_common import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Train GT-BEHRT-Visit with leakage-safe masked node concept prediction.")
    parser.add_argument("--graphs", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--mask-probability", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config" / "feature_policy.yaml")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    if not 0 < args.mask_probability < 1:
        raise SystemExit("--mask-probability must be between 0 and 1")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    policy = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    index = pd.read_parquet(args.graphs / "graph_index.parquet")
    index = index[index.split == "train"]
    if index.empty:
        raise SystemExit("No train graphs available for pretraining")
    vocab = json.loads((args.canonical / "concept_vocab.json").read_text(encoding="utf-8"))
    graphs = [json.loads((args.graphs / path).read_text(encoding="utf-8")) for path in index.graph_path]
    relations = sorted({edge["relation"] for graph in graphs for edge in graph["edges"]} | {"self"})
    type_to_id, relation_to_id = {name: index for index, name in enumerate(NODE_TYPES)}, {name: index for index, name in enumerate(relations)}
    config = policy["model"]
    device = torch.device(args.device)
    model = GTBEHRTVisit(len(vocab), len(type_to_id), len(relation_to_id), config["hidden_dimension"], config["output_dimension"], config["layers"], config["attention_heads"], config["dropout"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        random.shuffle(graphs)
        total_loss, batches = 0.0, 0
        for graph in graphs:
            tensors = list(tensorize(graph, type_to_id, relation_to_id, device))
            targets = tensors[0].clone()
            eligible = torch.where(targets > 0)[0]
            if len(eligible) == 0:
                continue
            count = max(1, round(len(eligible) * args.mask_probability))
            masked = eligible[torch.randperm(len(eligible), device=device)[:count]]
            tensors[0][masked] = 0
            hidden = model.encode(*tensors)
            loss = F.cross_entropy(model.concept_head(hidden[masked]), targets[masked])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach())
            batches += 1
        history.append({"epoch": epoch, "masked_concept_loss": total_loss / max(batches, 1), "graphs": batches})
        print(history[-1], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model": model.state_dict(), "relations": relations, "node_types": NODE_TYPES, "vocab_size": len(vocab), "training": {"objective": "masked_node_concept", "mask_probability": args.mask_probability, "seed": args.seed, "history": history}}, args.output)
    write_json(args.output.with_suffix(".training_manifest.json"), {"objective": "masked_node_concept", "train_graphs": len(graphs), "epochs": args.epochs, "history": history, "snapshot_mode": policy["snapshot"]["mode"]})


if __name__ == "__main__":
    main()
