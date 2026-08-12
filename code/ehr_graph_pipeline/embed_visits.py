"""Generate 256-dimensional L2-normalized embeddings from visit graphs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

from build_visit_graphs import NODE_TYPES
from ehr_common import write_json
from gt_behrt_visit import GTBEHRTVisit


def tensorize(graph: dict, type_to_id: dict[str, int], relation_to_id: dict[str, int], device: torch.device) -> tuple[torch.Tensor, ...]:
    nodes = graph["nodes"]
    edges = graph["edges"] or [{"source": 0, "target": 0, "relation": "self"}]
    return tuple(torch.tensor(values, dtype=dtype, device=device) for values, dtype in [
        ([node["concept_index"] for node in nodes], torch.long),
        ([type_to_id[node["node_type"]] for node in nodes], torch.long),
        ([node["numeric_value"] for node in nodes], torch.float32),
        ([node["time_hours"] for node in nodes], torch.float32),
        ([edge["source"] for edge in edges], torch.long),
        ([edge["target"] for edge in edges], torch.long),
        ([relation_to_id[edge["relation"]] for edge in edges], torch.long),
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed every visit graph. A checkpoint is required for retrieval-ready embeddings.")
    parser.add_argument("--graphs", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--allow-untrained", action="store_true", help="Only for contract/smoke tests; not retrieval-ready.")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config" / "feature_policy.yaml")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    if args.checkpoint is None and not args.allow_untrained:
        raise SystemExit("A trained --checkpoint is required. Use --allow-untrained only to verify the embedding contract.")
    policy = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    index = pd.read_parquet(args.graphs / "graph_index.parquet")
    vocab = json.loads((args.canonical / "concept_vocab.json").read_text(encoding="utf-8"))
    graph_rows = [json.loads((args.graphs / path).read_text(encoding="utf-8")) for path in index.graph_path]
    observed_relations = sorted({edge["relation"] for graph in graph_rows for edge in graph["edges"]} | {"self"})
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True) if args.checkpoint else None
    relations = checkpoint.get("relations", observed_relations) if checkpoint else observed_relations
    unknown_relations = set(observed_relations).difference(relations)
    if unknown_relations:
        raise SystemExit(f"Checkpoint has no parameters for graph relations: {sorted(unknown_relations)}")
    type_to_id, relation_to_id = {name: index for index, name in enumerate(NODE_TYPES)}, {name: index for index, name in enumerate(relations)}
    device = torch.device(args.device)
    config = policy["model"]
    model = GTBEHRTVisit(
        len(vocab), len(type_to_id), len(relation_to_id),
        hidden_dimension=config["hidden_dimension"],
        output_dimension=config["output_dimension"],
        layers=config["layers"],
        heads=config["attention_heads"],
        dropout=config["dropout"],
    ).to(device)
    if checkpoint:
        model.load_state_dict(checkpoint["model"] if "model" in checkpoint else checkpoint)
    model.eval()
    records = []
    with torch.inference_mode():
        for graph in graph_rows:
            vector = model(*tensorize(graph, type_to_id, relation_to_id, device)).cpu().numpy().astype(np.float32)
            records.append({"visit_id": graph["visit_id"], "split": graph["split"], "snapshot_mode": policy["snapshot"]["mode"], "embedding_version": "gt_behrt_visit_v0.1", "embedding": vector.tolist()})
    args.output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(args.output / "visit_embeddings.parquet", index=False)
    write_json(args.output / "embedding_manifest.json", {
        "embedding_dimension": policy["model"]["output_dimension"],
        "l2_normalized": True,
        "checkpoint": str(args.checkpoint) if args.checkpoint else None,
        "model_trained": bool(args.checkpoint),
        "retrieval_ready": False,
        "clinical_retrieval_validated": False,
        "snapshot_mode": policy["snapshot"]["mode"],
        "device": str(device),
        "graph_count": len(records),
    })
    print({"output": str(args.output), "embeddings": len(records), "model_trained": bool(args.checkpoint), "retrieval_ready": False})


if __name__ == "__main__":
    main()
