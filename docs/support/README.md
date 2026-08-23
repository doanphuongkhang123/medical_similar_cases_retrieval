# Tài liệu hỗ trợ pipeline và model

Thư mục này chứa các tài liệu giải thích trực tiếp cho pipeline chính, được
theo dõi trên GitHub. Không lưu dữ liệu bệnh nhân, embedding, checkpoint, log,
slide build, ảnh render hoặc chat archive tại đây.

## Context Clues structured-EHR encoder

- [Data preprocessing cho Context Clues GPT-base-4096-CLMBR](data_preprocess_context_clues_gpt_base_4096_clmbr.md):
  mô tả đầy đủ raw input, mapping từng sheet/cột, chuẩn hóa string/ID/time/lab,
  structured output, source-event inventory, concept mapping, timeline,
  tokenization và contract visit embedding.
- [Context Clues pipeline README](../../code/context_clues/README.md): cách chạy
  data-only, tải checkpoint, materialize mapped events và chạy frozen encoder.

## SMB-v1-1.7B structured-EHR encoder

- [Data preprocessing cho SMB-v1-1.7B](data_preprocess_smb_v1_1_7b.md): mô tả
  raw lineage, common MEDS schema, terminology policy, visit cutoff,
  `smb_utils` serialization audit và artifact contract.
- [SMB pipeline README](../../code/ehr_foundation_encoders/README.md): entry
  points chạy data-only và official serialization audit trên lab server.

## Contract chung của project

- [Data contract](../DATA.md)
- [Pipeline overview](../PIPELINES.md)
- [Code pipeline handoff](../CODE_PIPELINE_HANDOFF.md)
- [Project status](../STATUS.md)
- [Experiment contract](../EXPERIMENTS.md)

Chỉ tài liệu phản ánh code và artifact hiện hành mới được đặt trong thư mục
này. Tài liệu lịch sử hoặc giải thích tạm tiếp tục nằm ngoài Git.
