# Bốn pipeline embedding

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

## 4. SMB structured-EHR foundation embedding

```text
raw/thông tin bệnh án.xlsx
    -> pipeline-owned visits + diagnoses + medicines + procedures + observations
    -> one canonical MEDS-compatible event store
    -> chronological patient timeline through target discharge
    -> official smb_utils serialization
    -> 3,300-token audit + event-boundary recent window
    -> pinned SMB-v1 Qwen3 1.7B checkpoint
    -> [running] last-token smoke inference
    -> [next] one frozen embedding per visit
```

Source: `code/ehr_foundation_encoders/`. Data trung gian và artifact nằm riêng
dưới `data/ehr_foundation_encoders/raw_pipeline_v1/`. Pipeline không tiêu thụ
`data/ehr_preprocessed/` hay output Context Clues, không dựng clinical
note/graph và không nhân bản event table cho mỗi encoder/target. Data-only,
serialization, token audit, window selection và checkpoint download đã hoàn
tất; smoke inference đang chờ GPU dùng chung đủ trống.

Context Clues code/artifact cũ vẫn được giữ để truy vết nhưng model path đang
tạm dừng do checkpoint gated.

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

## Expert-review retrieval v1 đã triển khai

```text
EHR visit embedding + clinical-note visit embedding
    -> L2-normalize từng block
    -> positive weight + concatenate + L2-normalize
    -> exact cosine Top 20, loại query
    -> expert selection
    -> append-only SQLite ground truth
```

Source: `web/expert_review/`. Contract code end-to-end nằm trong
`docs/CODE_PIPELINE_HANDOFF.md`.

## Hai bản retrieval đã chốt về phạm vi

1. V1: EHR graph embedding + clinical-note embedding, đơn vị `visit_id`.
2. V2: giống V1 và thêm image embedding; candidate pool chỉ gồm visit có ít
   nhất một ảnh hợp lệ.

Một visit có thể có nhiều series ảnh. Baseline đang đề xuất là L2-normalize
từng series, mean-pooling riêng trong CT/MRI/XQ rồi L2-normalize lại. CT, MRI
và XQ không cosine trực tiếp với nhau vì encoder/dimension khác nhau.

V1 expert-review hiện cố định shortlist Top 20 và mặc định equal weights cho
EHR/note. Retrieval v2, trọng số image fusion và cách xử lý cặp không có modality
ảnh chung vẫn chưa chốt/triển khai; xem `STATUS.md`.
