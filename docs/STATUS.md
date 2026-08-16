# Project Status

**Cập nhật:** 2026-08-16

**Retrieval unit:** `visit_id`

## Pipeline hiện tại

1. EHR structured → visit graph → 3-stage pretrained GNN → EHR embedding.
2. Clinical note → Qwen3-Embedding-8B → note embedding 4096-D và 256-D.
3. CT/MRI/XQ → image encoder tương ứng → series-level image embedding.

## Dữ liệu và embedding

- EHR: 3.500 visit thuộc 3.095 bệnh nhân.
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
- Score từ EHR graph embedding và clinical-note embedding.

### V2 — EHR + clinical note + image

- Candidate pool chỉ gồm 1.005 visit có ít nhất một image embedding.
- Nhiều series trong cùng visit được gom riêng theo CT/MRI/XQ.
- Baseline đề xuất: L2-normalize từng series → mean-pooling trong cùng modality
  → L2-normalize visit-modality vector.
- Retrieval hai bước: EHR + note lấy shortlist, sau đó image similarity rerank.
- Không tính cosine trực tiếp giữa các modality dùng encoder/dimension khác nhau.

## Chưa triển khai/chưa chốt

- Code retrieval v1 và v2.
- Trọng số late fusion và kích thước shortlist.
- Cách xử lý cặp visit không có modality ảnh chung.
- Split train/validation/test theo `patient_id` và protocol đánh giá retrieval.
