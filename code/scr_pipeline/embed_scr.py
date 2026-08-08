#!/usr/bin/env python3
"""Create reusable BioClinicalBERT, lab-GRU and fused SCR embeddings."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from transformers import AutoModel, AutoTokenizer

from scr_models import LabGRUEncoder, batch_lab_sequences, checkpoint_config, l2_normalize


LOG = logging.getLogger("scr_embeddings")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True, help="Directory from preprocess_scr.py")
    p.add_argument("--output", type=Path, required=True, help="Embedding output directory")
    p.add_argument("--text-model", default="emilyalsentzer/Bio_ClinicalBERT")
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--device", default="auto", help="auto, cpu, cuda, or cuda:0")
    p.add_argument("--lab-checkpoint", type=Path, default=None)
    p.add_argument("--lab-item-dim", type=int, default=64)
    p.add_argument("--lab-hidden-dim", type=int, default=256)
    p.add_argument("--fusion-text-weight", type=float, default=1.0)
    p.add_argument("--fusion-lab-weight", type=float, default=1.0)
    p.add_argument("--overwrite-text", action="store_true")
    p.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING"))
    return p.parse_args()


def choose_device(value: str) -> torch.device:
    if value != "auto":
        return torch.device(value)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def rows_from(path: Path) -> List[dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    return pq.read_table(path).to_pylist()


def save_embedding_table(rows: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    schema = pa.schema([
        ("subject_id", pa.int64()),
        ("hadm_id", pa.int64()),
        ("split", pa.string()),
        ("embedding", pa.list_(pa.float32())),
        ("dimension", pa.int64()),
    ])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")


def encode_text(
    sample_rows: List[dict],
    output: Path,
    model_name: str,
    max_length: int,
    batch_size: int,
    device: torch.device,
    overwrite: bool,
) -> List[dict]:
    metadata_path = output.with_suffix(".json")
    if output.exists() and metadata_path.exists() and not overwrite:
        metadata = json.loads(metadata_path.read_text())
        if (
            metadata.get("model") == model_name
            and metadata.get("max_length") == max_length
            and metadata.get("count") == len(sample_rows)
        ):
            LOG.info("Reusing cached text embeddings: %s", output)
            return rows_from(output)
        LOG.warning("Text cache configuration differs; recomputing")

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(device)
    model.eval()
    output_rows: List[dict] = []
    for start in range(0, len(sample_rows), batch_size):
        batch = sample_rows[start : start + batch_size]
        texts = [str(row.get("text") or "") for row in batch]
        encoded = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode():
            hidden = model(**encoded).last_hidden_state
            # CLS pooling matches the usual BioClinicalBERT classification use.
            vectors = hidden[:, 0, :].detach().cpu().to(torch.float32).numpy()
        for row, vector in zip(batch, vectors):
            output_rows.append({
                "subject_id": int(row["subject_id"]),
                "hadm_id": int(row["hadm_id"]),
                "split": str(row["split"]),
                "embedding": vector.tolist(),
                "dimension": int(vector.shape[0]),
            })
        LOG.info("Text embeddings: %d/%d", min(start + len(batch), len(sample_rows)), len(sample_rows))
    save_embedding_table(output_rows, output)
    metadata_path.write_text(json.dumps({
        "model": model_name,
        "pooling": "cls",
        "max_length": max_length,
        "count": len(output_rows),
    }, indent=2) + "\n")
    return output_rows


def load_lab_model(
    vocab_size: int,
    checkpoint_path: Optional[Path],
    item_dim: int,
    hidden_dim: int,
    device: torch.device,
) -> Tuple[LabGRUEncoder, Optional[torch.nn.Module], bool]:
    trained = checkpoint_path is not None
    if checkpoint_path is not None:
        checkpoint = torch.load(checkpoint_path, map_location="cpu")
        config = checkpoint_config(checkpoint)
        if config["vocab_size"] != vocab_size:
            raise ValueError(f"Checkpoint vocab_size={config['vocab_size']} but current vocab_size={vocab_size}")
        model = LabGRUEncoder(**config)
        model.load_state_dict(checkpoint["model_state"])
        projection = None
        if checkpoint.get("projection_state") and checkpoint.get("text_dim"):
            projection = torch.nn.Linear(config["hidden_dim"], int(checkpoint["text_dim"]))
            projection.load_state_dict(checkpoint["projection_state"])
    else:
        torch.manual_seed(42)
        model = LabGRUEncoder(vocab_size, item_dim=item_dim, hidden_dim=hidden_dim)
        LOG.warning("No lab checkpoint supplied; lab embeddings are an untrained architecture smoke test")
        projection = None
    if projection is not None:
        projection = projection.to(device).eval()
    return model.to(device).eval(), projection, trained


def build_lab_and_fused(
    sample_rows: List[dict],
    text_rows: List[dict],
    sequence_rows: List[dict],
    vocab_path: Path,
    output: Path,
    checkpoint: Optional[Path],
    item_dim: int,
    hidden_dim: int,
    text_weight: float,
    lab_weight: float,
    device: torch.device,
    batch_size: int,
) -> None:
    vocab = json.loads(vocab_path.read_text())
    vocab_size = max([1] + [int(value) for value in vocab.get("itemid_to_index", {}).values()]) + 1
    lab_model, lab_projection, trained = load_lab_model(vocab_size, checkpoint, item_dim, hidden_dim, device)
    lab_output_dim = int(lab_projection.out_features) if lab_projection is not None else lab_model.output_dim
    text_by_hadm = {int(row["hadm_id"]): row for row in text_rows}
    sequence_by_hadm = {int(row["hadm_id"]): row for row in sequence_rows}
    result: List[dict] = []
    for start in range(0, len(sample_rows), batch_size):
        samples = sample_rows[start : start + batch_size]
        rows_with_labs = [sample for sample in samples if int(sample["hadm_id"]) in sequence_by_hadm]
        lab_vectors: Dict[int, np.ndarray] = {}
        if rows_with_labs:
            seqs = [sequence_by_hadm[int(sample["hadm_id"])] for sample in rows_with_labs]
            tensors = batch_lab_sequences(seqs, device)
            with torch.inference_mode():
                lab_tensor = lab_model(*tensors)
                if lab_projection is not None:
                    lab_tensor = lab_projection(lab_tensor)
                vectors = lab_tensor.detach().cpu().numpy().astype(np.float32)
            lab_vectors = {int(sample["hadm_id"]): vector for sample, vector in zip(rows_with_labs, vectors)}
        for sample in samples:
            hadm_id = int(sample["hadm_id"])
            text_vector = np.asarray(text_by_hadm[hadm_id]["embedding"], dtype=np.float32)
            text_vector = text_vector / max(float(np.linalg.norm(text_vector)), 1e-8)
            lab_vector = lab_vectors.get(hadm_id, np.zeros(lab_output_dim, dtype=np.float32))
            has_lab = hadm_id in lab_vectors
            if has_lab:
                lab_vector = lab_vector / max(float(np.linalg.norm(lab_vector)), 1e-8)
            fused = np.concatenate([text_weight * text_vector, lab_weight * lab_vector]).astype(np.float32)
            fused = fused / max(float(np.linalg.norm(fused)), 1e-8)
            result.append({
                "subject_id": int(sample["subject_id"]),
                "hadm_id": hadm_id,
                "split": str(sample["split"]),
                "has_lab_events": bool(has_lab),
                "text_embedding": text_vector.tolist(),
                "lab_embedding": lab_vector.tolist(),
                "fused_embedding": fused.tolist(),
            })
    output.unlink(missing_ok=True)
    schema = pa.schema([
        ("subject_id", pa.int64()), ("hadm_id", pa.int64()), ("split", pa.string()),
        ("has_lab_events", pa.bool_()), ("text_embedding", pa.list_(pa.float32())),
        ("lab_embedding", pa.list_(pa.float32())), ("fused_embedding", pa.list_(pa.float32())),
    ])
    pq.write_table(pa.Table.from_pylist(result, schema=schema), output, compression="zstd")
    (output.parent / "embedding_manifest.json").write_text(json.dumps({
        "text_model": "cached separately; see text_embeddings.json",
        "lab_encoder": "LabGRUEncoder",
        "lab_checkpoint": str(checkpoint) if checkpoint else None,
        "lab_checkpoint_trained": trained,
        "fusion": "L2-normalized weighted concatenation",
        "text_weight": text_weight,
        "lab_weight": lab_weight,
        "rows": len(result),
    }, indent=2) + "\n")


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    device = choose_device(args.device)
    args.output.mkdir(parents=True, exist_ok=True)
    samples = rows_from(args.input / "samples.parquet")
    text_rows = encode_text(
        samples,
        args.output / "text_embeddings.parquet",
        args.text_model,
        args.max_length,
        args.batch_size,
        device,
        args.overwrite_text,
    )
    sequence_rows = rows_from(args.input / "lab_sequences.parquet")
    build_lab_and_fused(
        samples, text_rows, sequence_rows, args.input / "lab_vocab.json",
        args.output / "scr_embeddings.parquet", args.lab_checkpoint,
        args.lab_item_dim, args.lab_hidden_dim, args.fusion_text_weight,
        args.fusion_lab_weight, device, args.batch_size,
    )
    LOG.info("Finished embeddings in %s", args.output)


if __name__ == "__main__":
    main()
