# Data contract

## Snapshot EHR hiện tại

- Root:
  `/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/ehr_preprocessed_full/`.
- 3.500 `visit_id` duy nhất thuộc 3.095 `patient_id`.
- `patient_id = SoVaoVien`; `visit_id = SoBenhAn`.
- Bảng chính: `visits`, `diagnoses`, `medicines`, `procedures`,
  `observations`, `clinical_notes`, `graph_nodes`, `graph_edges`.
- Clinical free text chưa được xác nhận khử định danh hoàn toàn; chỉ xử lý
  trên Vaipe.

## EHR graph

- Input đã chuẩn hóa: `visits`, `diagnoses`, `medicines`, `procedures`,
  `observations`.
- Đơn vị biểu diễn: một `visit_id` tương ứng một graph và một embedding.
- Snapshot hiện tại: `full_visit`, chỉ dùng retrospective.
- Split pretraining hiện tại hash theo `visit_id`, tỉ lệ 70/15/15. Khi đánh
  giá retrieval phải tạo split mới theo `patient_id` để tránh leakage giữa
  nhiều visit của cùng bệnh nhân.

## Image

- Đơn vị output mặc định: một embedding cho mỗi source image/volume.
- Encoder và preprocessing phải được ghi riêng theo modality.
- Không trộn vector từ encoder khác model/version trong cùng artifact.

### Linkage image–EHR hiện tại

- Manifest: 1.000 bệnh nhân; 999 bệnh nhân có ít nhất một image embedding.
- Image embeddings: 8.519 series (CT/MRI/XQ).
- Nối duy nhất được 8.315 series vào 1.005 visit thuộc 944 bệnh nhân.
- Candidate pool retrieval v2 chỉ gồm 1.005 visit này.
- Output:
  `/mnt/disk4/similar_cases_retrieval/data/retrieval_v2_image_1000/`.
- `image_embedding_links.parquet` giữ cả matched và unmatched row cùng
  `join_status`; không tự gán 204 row không đủ bằng chứng.

## Clinical note

- Input: `clinical_notes.parquet` với `note_id`, `visit_id` và `note_text`,
  kèm `visits.parquet` để bảo toàn đủ 3.500 visit.
- Đơn vị output hiện tại: một embedding cho mỗi `visit_id`, sau khi gom toàn
  bộ section/note của visit.
- Output không chứa lại `note_text`.
- Artifact hiện tại có bản 4096-D và 256-D tại `data/note_emb/`.
