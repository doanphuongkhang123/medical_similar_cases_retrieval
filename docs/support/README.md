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

## Contract chung của project

- [Data contract](../DATA.md)
- [Pipeline overview](../PIPELINES.md)
- [Code pipeline handoff](../CODE_PIPELINE_HANDOFF.md)
- [Project status](../STATUS.md)
- [Experiment contract](../EXPERIMENTS.md)

Chỉ tài liệu phản ánh code và artifact hiện hành mới được đặt trong thư mục
này. Tài liệu lịch sử hoặc giải thích tạm tiếp tục nằm ngoài Git.
