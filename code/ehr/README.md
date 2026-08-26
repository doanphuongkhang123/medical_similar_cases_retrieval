# Structured EHR workspace

Mọi pipeline đọc hoặc materialize EHR dạng bảng nằm dưới thư mục này:

- `ehr_graph_embedding/`: raw workbook -> normalized tables -> visit graph ->
  graph embedding.
- `ehr_foundation_encoders/`: structured events/MEDS -> SMB visit embedding.
- `context_clues/`: structured timeline cho Context Clues.
- `HyperGraph/`: dataset và hypergraph tương thích cấu trúc HypeMed.

Trên Vaipe, namespace dữ liệu tương ứng là
`/mnt/disk4/similar_cases_retrieval/data/ehr/`. Workbook canonical nằm tại
`data/ehr/raw/thông tin bệnh án.xlsx`; mọi output phải ở thư mục con riêng của
pipeline và manifest phải giữ path cùng SHA-256 của workbook.

Clinical-note embedding, image embedding và retrieval đa phương thức không
thuộc namespace code này dù chúng có thể đọc `visit_id` hoặc một projection từ
bảng EHR.

Sau khi đổi hoặc đồng bộ bố cục trên server, chạy:

```bash
CUDA_VISIBLE_DEVICES="" python code/ehr/audit_layout.py \
  --code-root /mnt/disk4/similar_cases_retrieval/code/code \
  --data-root /mnt/disk4/similar_cases_retrieval/data \
  --manifest /mnt/disk4/similar_cases_retrieval/data/ehr/layout_manifest.json
```
