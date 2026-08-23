# Experiments

## Đã hoàn tất

### EHR graph embedding

- Đã chạy ba stage trên 3.500 visit và xuất 256-D L2-normalized embedding.
- Các run nằm dưới
  `/mnt/disk4/similar_cases_retrieval/data/experiments/`.
- Artifact stage 3 hiện có `visit_embeddings.parquet` và quality report;
  chưa chốt run nào làm baseline retrieval cuối cùng.

### Clinical-note embedding

- Model: `Qwen/Qwen3-Embedding-8B`.
- Coverage: 3.500/3.500 visit; không note nào vượt context 32.768 token.
- Cấu hình thành công: FP16, 8-bit quantization, batch size 2.
- Output: 4096-D và 256-D, đều L2-normalized, tại `data/note_emb/`.

### Image–EHR linkage

- Input: 1.000 case bệnh nhân, 8.519 image embedding.
- Matched: 8.315 embedding → 1.005 visit / 944 bệnh nhân.
- Unmatched audit: 204 embedding.
- Output: `data/retrieval_v2_image_1000/`.
- Integrity check và ba unit test merge đều pass.

## Quy tắc cho run tiếp theo

Chỉ ghi các run thuộc một trong bốn pipeline embedding hoặc hai bản retrieval:

- EHR graph 3-stage pretraining;
- image encoder inference;
- clinical-note text encoder inference.
- SMB structured-EHR frozen inference.

Mỗi run cần ghi host/environment, Git commit, dataset path/version, model
revision, preprocessing, split, seed, command, exit status và artifact output.

Kết quả lịch sử trước đợt tinh gọn ngày 2026-08-16 đã được chuyển ra archive
sibling của project và không còn là contract hiện hành.
