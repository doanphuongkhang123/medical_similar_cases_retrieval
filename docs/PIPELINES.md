# Ba pipeline embedding

## 1. EHR graph embedding

```text
EHR tables -> visit graph -> Stage 1 NAM/numeric masking
           -> Stage 2 missing-node prediction
           -> Stage 3 VICReg + local/global MI
           -> 256-D L2-normalized visit embedding
```

Source: `code/ehr_graph_embedding/`.

## 2. Image embedding

```text
medical image -> modality-specific preprocessing -> image encoder
              -> raw float32 image embedding
```

Source: `code/image_embedding_pipeline/`.

## 3. Clinical-note text embedding

```text
clinical_notes.parquet + visits.parquet -> group all sections by visit_id
                                        -> Qwen3-Embedding-8B
                                        -> 4096-D and 256-D visit embeddings
```

Source: `code/text_embedding_pipeline/`.

## Contract chung

- Mỗi output phải giữ stable source ID, model revision, dimension và cấu hình
  preprocessing cần để tái lập.
- Không ghi raw clinical text hoặc pixel vào log/manifest embedding.
- Dữ liệu thật chỉ được đọc trên `vaipe_aiotlab`.
- Artifact thật nằm ngoài Git, dưới vùng experiment được phê duyệt.
- Các pipeline chỉ tạo representation; không tự suy diễn clinical similarity,
  ground truth, diagnosis hay treatment recommendation.

## Chuẩn bị retrieval v2

```text
image manifest + DICOM study metadata + EHR visits
    -> patient_id exact match
    -> study_date inside one admission/discharge interval
    -> image_embedding_links.parquet
    -> retrieval_v2_visits.parquet
```

Source: `code/image_embedding_pipeline/merge_image_cases_with_ehr.py`.

## Hai bản retrieval đã chốt về phạm vi

1. V1: EHR graph embedding + clinical-note embedding, đơn vị `visit_id`.
2. V2: giống V1 và thêm image embedding; candidate pool chỉ gồm visit có ít
   nhất một ảnh hợp lệ.

Một visit có thể có nhiều series ảnh. Baseline đang đề xuất là L2-normalize
từng series, mean-pooling riêng trong CT/MRI/XQ rồi L2-normalize lại. CT, MRI
và XQ không cosine trực tiếp với nhau vì encoder/dimension khác nhau.

Code retrieval, trọng số fusion, shortlist size và cách xử lý cặp không có
modality ảnh chung vẫn chưa chốt/triển khai; xem `STATUS.md`.
