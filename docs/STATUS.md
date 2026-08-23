# Project Status

**Cập nhật:** 2026-08-23

**Retrieval unit:** `visit_id`

## Pipeline hiện tại

1. EHR structured → visit graph → 3-stage pretrained GNN → EHR embedding.
2. Clinical note → Qwen3-Embedding-8B → note embedding 4096-D và 256-D.
3. CT/MRI/XQ → image encoder tương ứng → series-level image embedding.
4. Structured EHR → common MEDS-compatible events →
   `SMB-v1_Qwen3-1.7b_multi-objective` → frozen visit embedding. Data-only và
   official `smb_utils` serialization audit đã chạy trực tiếp từ workbook raw;
   tokenizer/model inference chưa chạy.

## Dữ liệu và embedding

- EHR: 3.500 visit thuộc 3.095 bệnh nhân.
- SMB raw data-only: 734.370 clinical event, 3.095 demographic event, 18.861
  local concept và 3.500 target visit; output tại
  `data/ehr_foundation_encoders/raw_pipeline_v1/`. Cả 3.500 target serialize
  non-empty bằng `smb_utils` revision
  `4f963e124a940c2ddbc10f50a7448a6e20654555`; serialized clinical text không
  được lưu.
- Context Clues data-only cũ vẫn ở `data/context_clues/raw_pipeline_v1/`, nhưng
  model path tạm dừng vì checkpoint gated và không phải input của SMB pipeline.
- SMB tokenizer của checkpoint pin đã tải thành công trên server mà không tải
  model weights. Tokenizer và paper cùng khai báo max sequence length 3.300;
  token audit chưa chạy vì Transformers cảnh báo regex tokenizer cần được xác
  minh trước khi dùng trên dữ liệu thật.
- Clinical note: đã embed đủ 3.500 visit.
- Image manifest: 1.000 bệnh nhân; 999 bệnh nhân có image embedding.
- Image embeddings hợp lệ: CT 3.322 × 512-D, MRI 3.904 × 768-D,
  XQ 1.293 × 512-D; không có NaN/Inf hoặc zero-vector.

## Merge image–EHR cho retrieval v2

- Quy tắc nối: `patient_id` khớp chính xác và `study_date` phải nằm trong duy
  nhất một khoảng `admission_time–discharge_time`.
- Kết quả: 8.315/8.519 image embedding nối được vào 1.005 visit thuộc 944 bệnh
  nhân; 204 embedding không đủ điều kiện nối được giữ trong bảng audit.
- Không ép một bệnh nhân vào một visit: 60 bệnh nhân có ảnh thuộc nhiều visit.
- Artifact:
  `/mnt/disk4/similar_cases_retrieval/data/retrieval_v2_image_1000/`.
- Bảng retrieval chính: `retrieval_v2_visits.parquet`.
- Bảng linkage/audit: `image_embedding_links.parquet`,
  `case_join_audit.parquet`, `manifest.json`.

## Hai bản retrieval

### V1 — EHR + clinical note

- Candidate ở cấp visit.
- Baseline đã triển khai tại `web/expert_review/`.
- Mỗi modality được L2-normalize, weighted-concatenate và L2-normalize lại.
- Exact cosine Top 20, loại query; kết quả được expert chọn và lưu append-only
  vào SQLite để tạo ground truth.

### V2 — EHR + clinical note + image

- Candidate pool chỉ gồm 1.005 visit có ít nhất một image embedding.
- Nhiều series trong cùng visit được gom riêng theo CT/MRI/XQ.
- Baseline đề xuất: L2-normalize từng series → mean-pooling trong cùng modality
  → L2-normalize visit-modality vector.
- Retrieval hai bước: EHR + note lấy shortlist, sau đó image similarity rerank.
- Không tính cosine trực tiếp giữa các modality dùng encoder/dimension khác nhau.

## Chưa triển khai/chưa chốt

- Xác minh cách xử lý cảnh báo regex của tokenizer checkpoint, sau đó chạy
  tokenizer audit đủ 3.500 visit, đo tỷ lệ vượt 3.300 token và chốt
  recency/truncation policy trước model inference.
- Review mapping local medicine/lab/procedure sang standard terminology để
  giảm domain shift; không chặn SMB data-only vì model nhận MEDS text code.
- Context Clues tạm dừng đến khi checkpoint được cấp quyền.
- Code retrieval v2.
- Trọng số V1 cuối cùng; expert-review hiện dùng default equal weights và Top 20.
- Trọng số late fusion/rerank và kích thước shortlist cho V2.
- Cách xử lý cặp visit không có modality ảnh chung.
- Split train/validation/test theo `patient_id` và protocol đánh giá retrieval.
