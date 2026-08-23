# Tiền xử lý structured EHR cho SMB-v1-1.7B

## Mục tiêu

Pipeline chuyển workbook EHR raw thành input MEDS-compatible cho
`standardmodelbio/SMB-v1_Qwen3-1.7b_multi-objective`, nhưng chưa tải model
weights hoặc chạy inference. Retrieval unit vẫn là `visit_id`: mỗi target visit
dùng toàn bộ lịch sử structured EHR của cùng bệnh nhân đến `discharge_time`.

Luồng xử lý:

```text
raw XLSX
  -> 5 bảng structured độc lập
  -> common/events.parquet (canonical + MEDS columns)
  -> common/targets.parquet (một target mỗi visit)
  -> SMB timeline selection theo discharge cutoff
  -> official smb_utils serialization audit
  -> tokenizer audit tối đa 3.300 token
  -> [bước sau] SMB-v1_Qwen3-1.7b_multi-objective embedding
```

## Lineage và phạm vi

Input bắt buộc trên lab server:

```text
/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx
```

Pipeline tự ghi năm bảng `visits`, `diagnoses`, `medicines`, `procedures` và
`observations` dưới data root riêng. Nó tái sử dụng code parser raw của EHR
pipeline nhưng không đọc `data/ehr_preprocessed/` hay artifact của Context
Clues. Raw path và SHA-256 được ghi vào root, structured và common manifest.

Clinical notes, image, graph, embeddings và model weights không thuộc stage
này. Toàn bộ xử lý là CPU-only và script đặt `CUDA_VISIBLE_DEVICES=""`.

## Vì sao chỉ lưu một bảng event

Hai lớp schema cùng nằm trong `common/events.parquet`:

- Metadata canonical: `patient_id`, `visit_id`, `event_id`, local code/name,
  result type, thời gian gốc, temporal audit và mapping provenance.
- MEDS-compatible: `subject_id`, `time`, `code`, `table`, `numeric_value`,
  `text_value`, `unit`.

SMB adapter lọc view từ bảng này trong bộ nhớ. Nó không materialize một bản
event table riêng cho từng encoder hoặc một bản history cho từng target visit.
Điều này tránh nhân bản hàng trăm nghìn event và vẫn giữ một common contract để
thêm encoder khác sau này.

## Quy tắc event

Category `table` dùng các giá trị mà `smb_utils` hỗ trợ:

| Source | MEDS `table` | MEDS `code` mặc định |
|---|---|---|
| Demographic | `person` | `Birth`, `Gender` |
| Diagnosis | `condition_occurrence` | `ICD10:<code>` nếu mã từ ICD field có shape hợp lệ; nếu không dùng local label |
| Medicine | `drug_exposure` | tên hoạt chất, fallback tên thuốc |
| Procedure | `procedure_occurrence` | tên procedure, fallback local service code |
| Observation | `measurement` | tên chỉ số, fallback local service code |

Pipeline không fuzzy-map local concept và không tự tuyên bố local lab/procedure
code là LOINC/CPT. `concept_inventory.parquet` giữ toàn bộ inventory;
`concept_mappings.csv` là template long-form để sau này review mapping sang
ICD-10, LOINC, RxNorm hoặc ATC mà không thay đổi raw event.

Giá trị observation được xử lý như sau:

- `numeric_exact` và `numeric_with_unit` hữu hạn đi vào `numeric_value`;
- categorical/semi-quantitative đi vào `text_value` dạng category chuẩn hóa;
- censored, interval và approximate giữ biểu diễn text thay vì giả thành số
  exact;
- free-text result không được đưa vào SMB structured input;
- giá trị numeric NaN/Inf không được biến thành clinical value.

Nếu event thiếu thời gian, dùng admission time của visit và đánh dấu
`time_imputed=true`. `temporal_status` giữ `before_admission`, `within_visit`
hoặc `after_discharge` để audit.

## Visit target và chống leakage

`common/targets.parquet` có đúng một row cho mỗi visit:

```text
patient_id, visit_id, admission_time, discharge_time,
target_order, visit_ordinal, cutoff_time
```

Khi dựng input cho target visit:

```text
subject_id == target.patient_id
time <= target.cutoff_time
target.cutoff_time == target.discharge_time
```

Không đổi `subject_id` thành `visit_id`, vì làm vậy sẽ mất lịch sử longitudinal.
Không lấy event của bệnh nhân khác hoặc event sau cutoff. Preflight audit kiểm
tra target còn event thuộc chính visit hiện tại.

## Serializer chính thức và storage policy

Pipeline pin `smb-utils` tại revision:

```text
4f963e124a940c2ddbc10f50a7448a6e20654555
```

Checkpoint SMB được pin tại revision:

```text
81a889a17c84160eaab4c975c70e451482bc9e56
```

`process_ehr_info` được gọi với `category_column="table"`, demographics bật và
`end_time=cutoff_time`. Serialized clinical text không được lưu lại vì vừa lặp
dữ liệu vừa tăng bề mặt dữ liệu nhạy cảm. Audit chỉ ghi số event, số ký tự, số
dòng, trạng thái non-empty và SHA-256 của serialization.

Tokenizer của gated checkpoint đã được tải trên server bằng tài khoản được cấp
quyền; model weights chưa được tải. Checkpoint khai báo `Qwen2Tokenizer`.
Cảnh báo Mistral regex của Transformers đã được kiểm tra bằng chuỗi giả lập và
xác nhận là false-positive khi load tokenizer Qwen từ local. Loader đặt rõ
`fix_mistral_regex=False`; không thay tokenizer SMB bằng tokenizer Qwen gốc vì
checkpoint có `added_tokens.json` riêng.

Audit đo riêng:

- token count của toàn bộ longitudinal history đến cutoff;
- token count của target visit cộng demographics;
- số token vượt 3.300 và số target vượt giới hạn ở mỗi view.

Audit không truncation và không lưu serialized text/token IDs. Kết quả quyết
định chính sách event-aware recency; không được âm thầm dùng right truncation
nếu nó cắt mất visit hiện tại.

Audit đủ 3.500 target trên `vaipe_aiotlab` đã hoàn tất:

- full history: median 2.618,5; p95 10.924,2; max 32.490 token;
- 1.389/3.500 full histories (39,69%) vượt 3.300 token;
- target visit cộng demographics: median 2.355,5; p95 9.259,2; max 32.490;
- 1.200/3.500 current views (34,29%) vượt 3.300 token.

Kết quả này loại trừ policy chỉ giữ toàn bộ current visit rồi thêm history gần
nhất, vì hơn một phần ba current visits tự thân đã quá dài. Bước inference phải
dùng chunking hoặc selection ở event boundary và ghi rõ cách gom embedding.

Giới hạn 3.300 lấy từ `tokenizer_config.json` của checkpoint và max sequence
length tác giả công bố trong paper. Giới hạn 4.096 thuộc model
`smb-v1-1.7B` cũ, không phải checkpoint Qwen3 multi-objective hiện hành.

Nguồn contract chính thức:

- https://standardmodel.bio/your-data.html
- https://github.com/standardmodelbio/smb-utils
- https://huggingface.co/standardmodelbio/SMB-v1_Qwen3-1.7b_multi-objective
- https://arxiv.org/abs/2601.22128

## Cách chạy trên server

Chuẩn bị raw, common MEDS và target preflight:

```bash
cd /mnt/disk4/similar_cases_retrieval/code/code/ehr_foundation_encoders
./run_smb_data_server.sh
```

Script mặc định không overwrite. Muốn chủ động rebuild cùng data root:

```bash
SMB_OVERWRITE_DATA=1 ./run_smb_data_server.sh
```

Cài checkout `smb-utils` đã pin dưới server data/runtime, không đưa vào Git:

```bash
./install_smb_utils_server.sh
```

Chạy serialization audit cho toàn bộ target:

```bash
./run_smb_serialization_audit_server.sh
```

Để tái tạo tokenizer artifact, tải **chỉ tokenizer/config**, sau đó chạy
token-length audit:

```bash
./run_smb_tokenizer_download_server.sh
./run_smb_token_audit_server.sh
```

Downloader dùng allow-list, từ chối weight extensions và chỉ đổi staging
directory thành artifact chính thức sau khi download/validation hoàn tất.
Token audit manifest ghi path và SHA-256 của raw workbook, common manifest,
events, targets và toàn bộ tokenizer files để tái lập lineage.

Smoke audit một số target:

```bash
SMB_SERIALIZATION_MAX_TARGETS=20 \
  SMB_OVERWRITE_SERIALIZATION_AUDIT=1 \
  ./run_smb_serialization_audit_server.sh
```

## Artifact contract

```text
/mnt/disk4/similar_cases_retrieval/data/ehr_foundation_encoders/raw_pipeline_v1/
├── manifest.json
├── structured/
│   ├── visits.parquet
│   ├── diagnoses.parquet
│   ├── medicines.parquet
│   ├── procedures.parquet
│   ├── observations.parquet
│   └── manifest.json
├── common/
│   ├── events.parquet
│   ├── targets.parquet
│   ├── concept_inventory.parquet
│   ├── concept_mappings.csv
│   ├── table_audit.parquet
│   └── manifest.json
└── adapters/smb_v1_1_7b/
    ├── target_preflight.parquet
    ├── manifest.json
    ├── serialization/
        ├── serialization_audit.parquet
        └── manifest.json
    └── tokenization/
        ├── token_length_audit.parquet
        └── manifest.json
```

Không artifact nào trong stage này được gọi là embedding. Embedding chỉ được
tạo ở stage model riêng sau khi tokenizer coverage, truncation policy và GPU
được kiểm tra.
