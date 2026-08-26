# Structured EHR foundation encoders

Pipeline data-only dùng chung cho structured EHR foundation models. Phiên bản
hiện tại triển khai adapter cho
`standardmodelbio/SMB-v1_Qwen3-1.7b_multi-objective`. Data-only, tokenizer,
token audit và recent-event window selection đã hoàn tất. Checkpoint pin đã
được tải sau khi review custom model source. Audit dữ liệu thật chạy bằng
tokenizer Qwen với `fix_mistral_regex=False`.

Audit đủ 3.500 target đã hoàn tất: 1.389 full histories (39,69%) và 1.200
target visits cộng demographics (34,29%) vượt 3.300 token. Pipeline không dùng
tokenizer truncation; nó dựng lại một recent-event window tối đa 3.300 token
cho mỗi visit.

Chạy trên lab server:

```bash
./run_smb_data_server.sh
./install_smb_utils_server.sh
./run_smb_serialization_audit_server.sh
./run_smb_tokenizer_download_server.sh
./run_smb_token_audit_server.sh
./run_smb_window_selection_server.sh
./run_smb_checkpoint_download_server.sh
./wait_run_smb_smoke_server.sh
```

Output:

```text
/mnt/disk4/similar_cases_retrieval/data/ehr/ehr_foundation_encoders/raw_pipeline_v1/
├── structured/
├── common/
│   ├── events.parquet
│   ├── targets.parquet
│   ├── concept_inventory.parquet
│   ├── concept_mappings.csv
│   └── manifest.json
└── adapters/smb_v1_1_7b/
    ├── target_preflight.parquet
    ├── manifest.json
    ├── serialization/
        ├── serialization_audit.parquet
        └── manifest.json
    ├── tokenization/
        ├── token_length_audit.parquet
        └── manifest.json
    └── window_selection/
        ├── window_selection.parquet
        └── manifest.json
```

`common/events.parquet` chứa trực tiếp MEDS columns, nên adapter không ghi lại
một bản events thứ hai. Mỗi target visit lấy history cùng bệnh nhân đến thời
điểm xuất viện. Serialized clinical text không được lưu; audit chỉ giữ counts
và SHA-256. Xem tài liệu chi tiết tại
`docs/support/data_preprocess_smb_v1_1_7b.md`.

Tokenizer-only downloader không tải `model.safetensors`. Checkpoint downloader
riêng dùng staging directory, allow-list đúng chín file, revision pin và
SHA-256 pin cho cả custom source lẫn weights. Weights và cache chỉ nằm dưới
server data root, không vào Git.

`window_selection.parquet` không sao chép events. Mỗi row lưu điểm bắt đầu của
suffix event gần nhất để dựng lại input từ `common/events.parquet`. Tất cả 3.500
window đều không quá 3.300 token; 2.111 giữ nguyên full history và 1.389 cần
selection. Không current visit nào bị loại hết clinical events.

Smoke inference chạy bằng interpreter của conda env `scr_env`. Waiter dùng
`flock`, poll GPU mỗi 60 giây và chỉ chạy khi có ít nhất 18.000 MiB trống. Nó
lấy last non-padding token từ final decoder hidden state; manifest không lưu
serialized text, token IDs, embedding, patient ID hoặc visit ID.

Kiểm thử:

```bash
python -m pytest -q tests
```
