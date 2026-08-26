# Project Status

**Cập nhật:** 2026-08-27

**Retrieval unit:** `visit_id`

## Bố cục lưu trữ

- Toàn bộ code xử lý EHR dạng bảng nằm dưới `code/ehr/`.
- Workbook gốc và mọi artifact EHR dạng bảng nằm dưới `data/ehr/` trên Vaipe.
- Workbook không còn nằm lẫn với ảnh/PDF trong `data/raw/`.

## Pipeline hiện tại

1. EHR structured → visit graph → 3-stage pretrained GNN → EHR embedding.
2. Clinical note → Qwen3-Embedding-8B → note embedding 4096-D và 256-D.
3. CT/MRI/XQ → image encoder tương ứng → series-level image embedding.
4. Structured EHR → common MEDS-compatible events →
   `SMB-v1_Qwen3-1.7b_multi-objective` → frozen visit embedding. Data-only và
   official `smb_utils` serialization/token-length audit đã chạy trực tiếp từ
   workbook raw; checkpoint đã tải và smoke inference đang chờ GPU đủ trống.

## Dữ liệu và embedding

- EHR: 3.500 visit thuộc 3.095 bệnh nhân.
- SMB raw data-only: 734.370 clinical event, 3.095 demographic event, 18.861
  local concept và 3.500 target visit; output tại
  `data/ehr/ehr_foundation_encoders/raw_pipeline_v1/`. Cả 3.500 target serialize
  non-empty bằng `smb_utils` revision
  `4f963e124a940c2ddbc10f50a7448a6e20654555`; serialized clinical text không
  được lưu.
- Context Clues data-only cũ vẫn ở `data/ehr/context_clues/raw_pipeline_v1/`, nhưng
  model path tạm dừng vì checkpoint gated và không phải input của SMB pipeline.
- SMB tokenizer và checkpoint pin đã tải thành công trên server. Tokenizer và
  paper cùng khai báo max sequence length 3.300.
  Cảnh báo regex được xác nhận là false-positive của Transformers cho tokenizer
  Qwen local; loader pin `fix_mistral_regex=False`.
- Token audit đủ 3.500 visit: full history median 2.618,5, p95 10.924,2, max
  32.490 token; 1.389/3.500 (39,69%) vượt giới hạn. Riêng target visit cộng
  demographics có 1.200/3.500 (34,29%) vượt giới hạn. Audit không truncation,
  không lưu serialized text/token IDs và không dùng GPU/model weights.
- Recent-event window selection đã hoàn tất: 2.111 visit giữ nguyên full
  history, 1.389 visit chọn suffix; mọi window ≤3.300 token (p95 3.298, max
  3.300). Có 2.300 visit giữ toàn bộ current-visit events; 1.200 visit giữ một
  phần recent events, nhưng không visit nào mất toàn bộ current clinical events.
  Selection plan không nhân bản common events.
- Checkpoint revision `81a889a17c84160eaab4c975c70e451482bc9e56` đã tải đủ
  vào server data root. `model.safetensors` SHA-256 là
  `f2c15be357477e8553d2953a075fb9527fdad6db0c2f6aee3ece9c43d862394c`;
  custom model source đã review và pin SHA-256. Không có lỗi quyền truy cập.
- Smoke inference đã xếp hàng trong tmux `khangdp` với ngưỡng 18.000 MiB GPU
  trống; output dự kiến tại
  `data/ehr/ehr_foundation_encoders/experiments/smb_v1_qwen3_1_7b/smoke_inference/`.
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

- Hoàn tất smoke inference đang chờ GPU, sau đó chạy full 3.500 visit embedding
  với last-token pooling và verify one-row-per-visit/finite/lineage.
- Review mapping local medicine/lab/procedure sang standard terminology để
  giảm domain shift; không chặn SMB data-only vì model nhận MEDS text code.
- Context Clues tạm dừng đến khi checkpoint được cấp quyền.
- Code retrieval v2.
- Trọng số V1 cuối cùng; expert-review hiện dùng default equal weights và Top 20.
- Trọng số late fusion/rerank và kích thước shortlist cho V2.
- Cách xử lý cặp visit không có modality ảnh chung.
- Split train/validation/test theo `patient_id` và protocol đánh giá retrieval.
