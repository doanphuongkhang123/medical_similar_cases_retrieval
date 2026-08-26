# Similar Cases Retrieval

Code và dữ liệu EHR dạng bảng được gom dưới hai namespace riêng:

- Code: `code/ehr/`.
- Data trên Vaipe: `/mnt/disk4/similar_cases_retrieval/data/ehr/`.

Repository giữ các pipeline tạo embedding độc lập:

1. `code/ehr/ehr_graph_embedding/`: biểu diễn một visit EHR thành graph, pretrain
   GNN qua ba stage và xuất một embedding cho mỗi visit.
2. `code/image_embedding_pipeline/`: đưa ảnh y khoa qua encoder phù hợp với
   modality và xuất embedding ảnh.
3. `code/text_embedding_pipeline/`: gom toàn bộ clinical note theo visit, đưa
   qua Qwen3-Embedding-8B và xuất embedding văn bản.
4. `code/ehr/ehr_foundation_encoders/`: đọc workbook EHR raw, dựng một common
   MEDS-compatible event store, serialize bằng `smb_utils`, rồi chạy
   `SMB-v1_Qwen3-1.7b_multi-objective` để xuất một frozen embedding cho mỗi
   visit. Code Context Clues cũ vẫn được giữ để truy vết nhưng checkpoint còn
   gated và không phải pipeline foundation encoder đang triển khai.

Các công cụ Context Clues và HyperGraph cũng nằm lần lượt tại
`code/ehr/context_clues/` và `code/ehr/HyperGraph/`. Workbook EHR gốc nằm tại
`data/ehr/raw/thông tin bệnh án.xlsx`; `data/raw/` chỉ còn dữ liệu ảnh/PDF.

`code/image_embedding_pipeline/merge_image_cases_with_ehr.py` nối image
embedding vào đúng `visit_id` để chuẩn bị candidate pool cho retrieval v2.
`web/expert_review/` triển khai baseline retrieval v1 EHR + clinical note để
chuyên gia duyệt Top 20 và tạo ground truth append-only. Retrieval v2 có image
vẫn chưa được triển khai.

## Đọc trước khi tiếp tục ở chat khác

1. [docs/STATUS.md](docs/STATUS.md): trạng thái và việc chưa chốt.
2. [docs/PIPELINES.md](docs/PIPELINES.md): luồng ba encoder và hai bản retrieval.
3. [docs/DATA.md](docs/DATA.md): data contract, ID và artifact hiện có.
4. [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md): các run đã hoàn tất.
5. [docs/CODE_PIPELINE_HANDOFF.md](docs/CODE_PIPELINE_HANDOFF.md): contract
   semantic-v2, graph SSL ba stage, embedding và expert-review đúng theo code.

Code server: `/mnt/disk4/similar_cases_retrieval/code/`. Dữ liệu và model
artifact chỉ tồn tại trên Vaipe, không đưa vào Git.
