# Architecture — GT-BEHRT-Visit baseline

```text
Excel workbook
  → canonical visits/events/relations (train-only vocab and robust lab stats)
  → independent sparse graph per SoBenhAn
  → 2-layer relation-aware Graph Transformer
  → VISIT node + event attention pooling
  → 256-dimensional L2-normalized visit embedding
```

The graph contains one `VISIT` node and sparse `TEXT_SECTION`, `VITAL`,
`ORDER`, `LAB_RESULT`, `PRESCRIPTION`, `MEDICATION`, and `PROCEDURE` nodes.
Each business edge is emitted with its reverse edge; `VISIT` also connects
directly to all event nodes. Consecutive results of the same lab test receive a
single temporal `next_same_test` edge.

The initial training stage masks approximately 15% of non-UNK concept IDs in
train visit graphs and predicts them from graph representations. It produces a
self-supervised checkpoint. Relation prediction, VICReg, text encoding, and
supervised similarity training remain future work described in
`GT_BEHRT_VISIT_PIPELINE.md`.

`visit_embeddings.parquet` follows the contract: `visit_id`, `split`,
`snapshot_mode`, `embedding_version`, and `embedding` (float32[256]). A
checkpoint makes the artifact model-derived, but not clinically validated;
retrieval metrics need an approved relevance definition.
