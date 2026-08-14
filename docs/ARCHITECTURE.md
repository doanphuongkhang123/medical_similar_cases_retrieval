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

Each experiment must write all derived data, checkpoint, embeddings and logs to
one server-only run directory: `data/experiments/<experiment_id>/`. The source
workbook remains outside this directory and is read-only.

## Supervised retrieval-improvement stage

After self-supervised embedding export, the optional supervised retrieval path
is deliberately decoupled from the graph encoder:

```text
visit_embeddings.parquet
  -> top-k + random annotation candidates (no inferred labels)
  -> externally reviewed ordinal relevance pairs
  -> train-only linear projection + L2 normalization
  -> supervised_visit_embeddings.parquet
  -> Precision@k / mAP@k / nDCG@k on judged held-out candidates
```

The projection is trained only on pairs whose visits are in the train split.
It cannot certify patient-disjointness from the current `visit_id` contract;
that requires an approved pseudonymized patient identifier and split audit.
Unreviewed candidates are never silently treated as negative labels, so the
reported evaluation scope is explicitly the judged candidate set.

## Đầu vào GNN theo thiết kế một visit — một graph

Pipeline `preprocess_ehr_tables.py` tạo đồng thời hai cách nhìn của cùng dữ
liệu:

```text
Một dòng Visit_EHR
├── diagnosis: danh sách chẩn đoán
├── medicine: danh sách thuốc
├── procedure: danh sách dịch vụ/thủ thuật
└── clinical_note: ghi chú và báo cáo đã ghép theo phần
          │
          ▼
Một graph cho một visit
├── 1 nút VISIT
├── nhiều nút DIAGNOSIS
├── nhiều nút MEDICINE
├── nhiều nút PROCEDURE
├── nhiều nút NOTE
└── nhiều nút OBSERVATION
```

Mọi nút con nối hai chiều với `VISIT`. Khi có `order_id`, `PROCEDURE` còn nối
với `OBSERVATION` bằng `has_result/result_of` và với `NOTE` bằng
`has_report/report_of`. `graph_id = patient_id::visit_id`. Bước tiếp theo chỉ
cần mã hóa thuộc tính từng loại nút, đưa `graph_nodes` và `graph_edges` vào
GNN, rồi lấy đầu ra của nút `VISIT` hoặc phép gộp toàn graph làm embedding của
lượt khám.
