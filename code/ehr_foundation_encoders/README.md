# Structured EHR foundation encoders

Pipeline data-only dùng chung cho structured EHR foundation models. Phiên bản
hiện tại triển khai adapter cho `standardmodelbio/SMB-v1-1.7B` và dừng trước
tokenizer/model inference.

Chạy trên lab server:

```bash
./run_smb_data_server.sh
./install_smb_utils_server.sh
./run_smb_serialization_audit_server.sh
```

Output:

```text
/mnt/disk4/similar_cases_retrieval/data/ehr_foundation_encoders/raw_pipeline_v1/
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
    └── serialization/
        ├── serialization_audit.parquet
        └── manifest.json
```

`common/events.parquet` chứa trực tiếp MEDS columns, nên adapter không ghi lại
một bản events thứ hai. Mỗi target visit lấy history cùng bệnh nhân đến thời
điểm xuất viện. Serialized clinical text không được lưu; audit chỉ giữ counts
và SHA-256. Xem tài liệu chi tiết tại
`docs/support/data_preprocess_smb_v1_1_7b.md`.

Kiểm thử:

```bash
python -m pytest -q tests
```
