# Data preprocessing cho Context Clues GPT-base-4096-CLMBR

## 1. Mục tiêu và phạm vi

Tài liệu này mô tả cách dữ liệu EHR dạng bảng được xử lý để làm input cho
encoder `StanfordShahLab/gpt-base-4096-clmbr` (Context Clues), với đơn vị output
cuối cùng là **một embedding cho mỗi `visit_id`**.

Luồng tổng quát:

```text
raw XLSX
  -> 5 bảng structured riêng của Context Clues
  -> event schema chung + temporal audit
  -> inventory local concept
  -> mapping local concept sang OMOP-standard code
  -> timeline theo bệnh nhân đến discharge của target visit
  -> tối đa 4.096 token gần nhất
  -> frozen Context Clues GPT-base-4096
  -> một vector 768-D cho mỗi visit
```

Phạm vi hiện tại:

- Đã chạy xong phần **raw data-only preprocessing** trên server.
- Chưa review xong local concept -> OMOP mapping.
- Chưa chạy tokenizer/model inference.
- Không sử dụng clinical note, ảnh, graph hoặc artifact từ pipeline EHR graph.
- Không sử dụng GPU trong data-only preprocessing.

## 2. Input gốc

### 2.1. Workbook

Input bắt buộc là workbook raw trên server:

```text
/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx
```

SHA-256 đã ghi trong manifest:

```text
4d621a576164aef695f7349fa770b916216401632d93078d62639842da1ec899
```

Pipeline **không** lấy dữ liệu từ:

```text
/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/
```

Code có tái sử dụng các hàm parser raw XLSX của pipeline EHR graph để giữ cùng
quy tắc parsing, nhưng không đọc Parquet hoặc manifest do pipeline đó sinh ra.

### 2.2. Các sheet được đọc

| Tên sheet raw | Tên logic trong code | Số dòng dữ liệu |
|---|---|---:|
| `thông tin bệnh án` | `visits` | 3.500 |
| `chỉ định DVKT` | `orders` | 151.248 |
| `Thuốc` | `medicines` | 219.167 |
| `KQCLS` | `labs` | 312.251 |
| `Phẫu thuật thủ thuật` | `procedures` | 11.342 |

Nếu thiếu một trong năm sheet bắt buộc, pipeline dừng thay vì tạo dataset thiếu.

## 3. Đường dẫn code preprocessing

### 3.1. Entry point

Local:

```text
/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/run_data_only_server.sh
/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/prepare_raw_source_data.py
```

Server:

```text
/mnt/disk4/similar_cases_retrieval/code/code/context_clues/run_data_only_server.sh
/mnt/disk4/similar_cases_retrieval/code/code/context_clues/prepare_raw_source_data.py
```

### 3.2. Code xử lý chính

| Chức năng | Path local |
|---|---|
| Điều phối raw workbook -> structured -> source events | `/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/src/context_clues_pipeline/raw_workbook.py` |
| Chuẩn hóa structured table thành event schema chung, concept map và audit | `/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/src/context_clues_pipeline/data.py` |
| Tạo mapped encoder-ready events sau khi mapping được duyệt | `/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/prepare_events.py` |
| Dựng timeline cho từng target visit | `/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/src/context_clues_pipeline/timeline.py` |
| Tokenization audit và lấy embedding | `/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/src/context_clues_pipeline/embedding.py` |
| CLI chạy tokenizer/model | `/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/embed_visits.py` |

### 3.3. Parser raw XLSX được tái sử dụng

Pipeline Context Clues gọi code parser, không gọi output data của pipeline EHR:

```text
/Users/k/Documents/work/SimilarCasesRetrieval/code/ehr_graph_embedding/preprocessing/preprocess_ehr_tables.py
/Users/k/Documents/work/SimilarCasesRetrieval/code/ehr_graph_embedding/preprocessing/preprocess_ehr_tables_v2.py
```

Path tương ứng trên server:

```text
/mnt/disk4/similar_cases_retrieval/code/code/ehr_graph_embedding/preprocessing/preprocess_ehr_tables.py
/mnt/disk4/similar_cases_retrieval/code/code/ehr_graph_embedding/preprocessing/preprocess_ehr_tables_v2.py
```

Chỉ các builder sau được gọi:

- `read_workbook`
- `build_visits`
- `build_diagnoses`
- `build_medicines`
- `build_procedures`
- `build_observations_v2`

Không gọi builder clinical note, visit summary, graph node hoặc graph edge.

## 4. Chuẩn hóa chung từ raw

### 4.1. Chuẩn hóa chuỗi

Mọi giá trị chuỗi đi qua các bước:

1. Unicode normalize theo `NFKC`.
2. Chuyển giá trị thành string.
3. Gộp khoảng trắng liên tiếp thành một khoảng trắng.
4. Xóa khoảng trắng đầu/cuối.
5. Các literal `""`, `null`, `none`, `nan`, `nat`, `not available` được xem là
   thiếu và chuyển thành chuỗi rỗng.

Khi tạo khóa concept, chuỗi còn được:

1. `casefold()` để không phân biệt hoa/thường;
2. thay chuỗi ký tự không phải chữ/số bằng khoảng trắng;
3. gộp khoảng trắng lần nữa.

Pipeline không fuzzy-merge hai tên gần giống nhau và không tự coi tên tiếng Việt
là một OMOP concept.

### 4.2. Chuẩn hóa ID

- `patient_id = SoVaoVien`.
- `visit_id = SoBenhAn`.
- Nếu ID Excel có dạng `123.0`, phần `.0` được bỏ để thành `123`.
- `patient_id` hoặc `visit_id` rỗng làm pipeline dừng.
- `visit_id` trùng làm pipeline dừng.

Các ID event con được tạo ổn định bằng SHA-256 của các trường định danh đã
clean, lấy 24 ký tự hex đầu và thêm prefix theo loại, ví dụ `diag_...`, `med_...`,
`proc_...`, `obs_...`. Cùng input và cùng code parsing sẽ sinh cùng ID.

### 4.3. Chuẩn hóa thời gian

Parser hỗ trợ:

- giá trị datetime đã được Excel/Pandas nhận diện;
- chuỗi 12 chữ số `YYYYMMDDHHMM`;
- chuỗi 8 chữ số `YYYYMMDD`;
- Excel serial date trong khoảng hợp lệ;
- các chuỗi thời gian khác mà `pandas.to_datetime` parse được.

Giá trị không parse được trở thành `NaT`; pipeline không tự suy diễn ngày từ
text tự do.

## 5. Tạo năm bảng structured riêng cho Context Clues

Output của stage này:

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/raw_pipeline_v1/structured/
```

### 5.1. `visits.parquet`

Nguồn chính: sheet `thông tin bệnh án`.

Mapping:

| Cột output | Cột/nguồn raw | Xử lý |
|---|---|---|
| `patient_id` | `SoVaoVien` | clean key, bỏ `.0` |
| `visit_id` | `SoBenhAn` | clean key, bắt buộc duy nhất |
| `admission_time` | `NgayVaoVien` | parse datetime |
| `discharge_time` | `NgayRaVien` | parse datetime |
| `department` | `TenPhongBan` | clean string |
| `birth_year` | `NamSinh` từ `chỉ định DVKT` | first non-empty theo visit, ép numeric |
| `gender_code` | `GioiTinh` từ `chỉ định DVKT` | first non-empty theo visit |
| `age_at_visit` | admission year - birth year | chỉ giữ tuổi trong `[0, 120]` |

Validation:

- Không có ID rỗng.
- `visit_id` duy nhất.
- Admission và discharge đều tồn tại.
- `discharge_time >= admission_time`.

Kết quả: 3.500 visit thuộc 3.095 bệnh nhân.

### 5.2. `diagnoses.parquet`

Diagnosis được lấy từ nhiều nguồn raw:

- `MaICD`: primary ICD ở sheet bệnh án;
- `ICD_phu`: tách theo dấu `;`, `,` hoặc `|`;
- các field diagnosis lúc khám, trước mổ, sau mổ, ra viện, bệnh kèm theo và
  chẩn đoán phân biệt;
- `ChanDoan` trong sheet chỉ định;
- `ChanDoanKhoaKham` trong sheet thuốc;
- `ChanDoan` trong sheet kết quả cận lâm sàng;
- diagnosis trước/sau mổ trong sheet thủ thuật, nối về visit qua
  `YeuCauChiTiet_Id`.

Mỗi row có:

```text
diagnosis_id, patient_id, visit_id, diagnosis_code, diagnosis_text,
diagnosis_type, event_time, source_sheet, source_field, source_row_count
```

Quy tắc thời gian:

- Primary/secondary ICD và phần lớn diagnosis lúc khám: admission time.
- Diagnosis ra viện: discharge time.
- Diagnosis từ order/lab/medicine/procedure: dùng timestamp của nguồn đó.

Deduplication theo:

```text
patient_id + visit_id + normalized diagnosis_code + normalized diagnosis_text
```

Nếu nhiều raw row trùng cùng concept trong visit, giữ event time sớm nhất và
gộp provenance. Structured output có 34.332 row; sau khi loại concept key rỗng
ở stage event còn 34.317 diagnosis event.

### 5.3. `medicines.parquet`

Nguồn: sheet `Thuốc`.

Mapping chính:

- `visit_id <- sobenhan`.
- `patient_id` được tra từ bảng visit, không lấy một patient key khác làm chuẩn.
- `drug_name <- TenDuoc`.
- `active_ingredient <- TenHoatChat`.
- `route <- DuongDung`.
- Liều sáng/trưa/chiều/tối được giữ ở các cột riêng.
- `days`, `total_quantity` được parse numeric khi có thể.
- `prescribed_time <- NgayKham`.
- Có `LyDoTraThuoc` thì status là `returned`, còn lại là `prescribed`.

Concept dùng cho Context Clues:

```text
active_ingredient nếu có, nếu không thì drug_name
```

Các raw row giống hệt nhau theo toàn bộ thông tin thuốc được gộp; số dòng nguồn
được ghi trong `source_row_count`. Structured output có 219.105 row; 219.103
row tạo được source concept event.

### 5.4. `procedures.parquet`

Base table là sheet `chỉ định DVKT`:

- `order_id <- YeuCauChiTiet_Id`;
- `procedure_name <- TenDichVu`;
- `ordered_time <- NgayYeuCau`;
- giữ khoa chỉ định, khoa thực hiện, loại/vị trí mẫu và indication.

Enrichment:

- Service code được gom từ `MA_DICH_VU` trong `KQCLS` theo `order_id`.
- Thông tin đã thực hiện được nối từ `Phẫu thuật thủ thuật` theo `order_id`.
- Nếu có biên bản thực hiện thì status `performed`; nếu không thì `ordered`.
- Chỉ loại raw row trùng hoàn toàn; không gộp hai chỉ định khác thời gian.

Thời gian event dùng theo thứ tự ưu tiên:

```text
start_time -> ordered_time -> received_time
```

Concept dùng `service_code` nếu có; nếu không dùng `performed_name`, sau đó
fallback `procedure_name`.

Kết quả: 151.248 procedure event.

### 5.5. `observations.parquet`

Nguồn:

- Các chỉ số trong sheet `KQCLS`.
- Sáu vital sign ở sheet bệnh án: pulse, respiratory rate, temperature, weight,
  systolic blood pressure và diastolic blood pressure.

Các cột chính:

```text
observation_id, patient_id, visit_id, order_id, service_code,
observation_name, result_text, result_numeric, result_type, value_proxy,
result_operator, lower/upper bound, category, ordinal_level, unit,
reference_range, specimen_type, observed_time
```

#### Phân loại kết quả xét nghiệm

| Input | `result_type` | Biểu diễn |
|---|---|---|
| rỗng/missing literal | `missing` | không có numeric |
| số chính xác | `numeric_exact` | `result_numeric`, `value_proxy` |
| `<`, `<=`, `>`, `>=` | `numeric_censored` | operator và bound riêng |
| khoảng số | `numeric_interval` | lower, upper, midpoint proxy |
| `~`, `≈`, `about`, `khoảng` | `numeric_approx` | số và subtype approximate |
| dạng `x 10^n` | `numeric_with_unit` | mở rộng số, giữ unit suffix |
| positive/negative/normal/... | `categorical` | canonical category |
| trace/low/moderate/high hoặc thang `+` | `semi_quantitative` | category và ordinal level |
| còn lại | `free_text` | giữ trong structured audit table |

`value_proxy` chỉ là biểu diễn hỗ trợ cho pipeline graph; không được coi là giá
trị xét nghiệm exact. Khi chuyển sang Context Clues source event, chỉ
`result_type=numeric_exact` mới được đưa vào `raw_numeric_value`. Các loại
censored, interval, approximate, categorical và free text chỉ có thể đóng góp
code-presence sau mapping.

#### Khóa concept observation

Một `service_code` có thể đại diện một panel gồm nhiều analyte. Vì vậy key là:

```text
code_name:<normalized service_code>|<normalized observation_name>
```

Nếu thiếu tên thì dùng code; nếu thiếu code thì dùng tên. Không map toàn bộ
component trong panel vào cùng một LOINC chỉ dựa trên panel code.

Kết quả: 329.702 observation event.

## 6. Structured output và lineage manifest

```text
raw_pipeline_v1/structured/
├── visits.parquet
├── diagnoses.parquet
├── medicines.parquet
├── procedures.parquet
├── observations.parquet
└── manifest.json
```

`manifest.json` ghi:

- raw workbook path và SHA-256;
- số dòng từng raw sheet;
- số row/visit từng output table;
- orphan count;
- Python/Pandas version;
- `clinical_notes_included=false`;
- `graph_tables_included=false`.

## 7. Chuyển structured table thành source event schema chung

Code:

```text
code/context_clues/src/context_clues_pipeline/data.py
```

### 7.1. Projection từng bảng

| Source table | Concept source | Event time | `omop_table` tạm |
|---|---|---|---|
| diagnoses | code, fallback diagnosis text | `event_time` | `condition_occurrence` |
| medicines | active ingredient, fallback drug name | `prescribed_time` | `drug_exposure` |
| procedures | service code, fallback procedure name | start/order/receive | `procedure_occurrence` |
| observations | service code + analyte name | `observed_time` | `measurement` |

Các row thiếu `patient_id`, `visit_id` hoặc concept key sau normalization bị
loại khỏi source event inventory.

### 7.2. Schema `source_events.parquet`

```text
patient_id
visit_id
source_table
source_event_id
source_code
source_name
event_time
raw_numeric_value
raw_unit
omop_table
source_key
admission_time
discharge_time
time_imputed
effective_time
time_source
temporal_status
available_by_discharge
event_priority
event_id
event_order_within_patient
event_order_within_visit
```

### 7.3. Temporal normalization

Sau khi nối với visit:

```text
effective_time = event_time nếu có
effective_time = admission_time nếu event_time thiếu
```

`time_source` nhận một trong hai giá trị:

- `source_event_time`
- `admission_fallback`

`temporal_status`:

- `before_admission` nếu `effective_time < admission_time`;
- `within_visit` nếu nằm trong khoảng admission-discharge;
- `after_discharge` nếu `effective_time > discharge_time`.

`available_by_discharge=true` khi:

```text
effective_time <= discharge_time
```

Stage source preparation chưa xóa event sau discharge. Nó giữ các event này để
audit. Khi dựng timeline cho target visit, cutoff mới thực sự được áp dụng.

Event priority khi cùng timestamp:

| Event | Priority |
|---|---:|
| diagnosis | 20 |
| medicine | 30 |
| procedure | 40 |
| observation | 50 |

Thứ tự cuối:

```text
patient_id -> effective_time -> event_priority -> event_id
```

Kết quả raw run hiện tại:

- 734.370 source event.
- 691.208 event available by discharge của visit nguồn.
- 43.162 event after discharge.
- 0 event phải impute thời gian.
- `event_id` duy nhất.
- Không có `effective_time` rỗng.

## 8. Tạo concept inventory và mapping worklist

### 8.1. Full concept map

Output:

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/raw_pipeline_v1/source_prepared/concept_map.csv
```

Mỗi row là một cặp duy nhất:

```text
source_table + source_key
```

Các cột:

```text
source_table, source_key, source_code, source_name,
event_count, visit_count, patient_count,
target_code, mapping_status, mapping_method,
use_value, value_multiplier, value_offset, target_unit, mapping_notes
```

Kết quả: 18.861 local concept.

### 8.2. Practical worklist

Output:

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/raw_pipeline_v1/source_prepared/concept_mapping_worklist.csv
```

Worklist gồm:

- diagnosis có code;
- toàn bộ medicine concept;
- toàn bộ procedure concept;
- toàn bộ observation concept.

Diagnosis chỉ có text vẫn được giữ trong full `concept_map.csv`, nhưng không nằm
trong worklist ưu tiên.

Kết quả:

- 2.638 concept trong worklist;
- bao phủ 97,006% source event.

## 9. Mapping sang code model hiểu được — chưa hoàn thành

Context Clues tokenizer không học mã nội bộ bệnh viện. Mỗi concept muốn đi vào
model phải được review và map sang dạng vocabulary/model code, ví dụ:

```text
SNOMED/...
LOINC/...
RxNorm/...
CPT4/...
```

Một row chỉ được dùng khi:

```text
mapping_status = approved hoặc auto_approved
target_code có dạng VOCABULARY/concept_code
```

Không dùng fuzzy matching rồi tự gán `approved`.

### Numeric observation sau mapping

Mặc định observation chỉ được encode bằng code-presence. Numeric chỉ được dùng
khi đồng thời thỏa mãn:

1. raw parser xác định `result_type=numeric_exact`;
2. mapping đã được approve;
3. unit và scale đã được review;
4. `use_value=true`.

Nếu dùng numeric:

```text
model_value = raw_numeric_value * value_multiplier + value_offset
unit = target_unit
```

Nếu không đủ điều kiện, `value` là missing nhưng code event vẫn được giữ.

## 10. Materialize encoder-ready events — chưa chạy

Command/code:

```text
/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/prepare_events.py
```

Input:

```text
raw_pipeline_v1/structured/*.parquet
raw_pipeline_v1/source_prepared/concept_map.csv
```

Chỉ approved mapped clinical events được materialize. Pipeline đồng thời thêm:

- một `Visit/IP` event cho mỗi visit;
- birth event `SNOMED/3950001` nếu birth year hợp lệ;
- `Gender/M` hoặc `Gender/F` nếu map được giới tính.

Output dự kiến:

```text
raw_pipeline_v1/prepared/
├── events.parquet
├── visits.parquet
├── concept_map_snapshot.parquet
├── unmapped_concepts.parquet
├── mapping_audit.parquet
└── manifest.json
```

Inference bị chặn mặc định nếu event mapping coverage dưới 50%.

## 11. Dựng timeline cho từng target visit — chưa chạy

Code:

```text
code/context_clues/src/context_clues_pipeline/timeline.py
```

Với target visit `v`, pipeline lấy:

```text
tất cả event của cùng patient có start/effective_time <= discharge_time(v)
```

Ví dụ patient có ba visit theo thời gian `V1 -> V2 -> V3`:

- embedding V1 chỉ thấy dữ liệu đến discharge V1;
- embedding V2 thấy lịch sử V1 và dữ liệu V2 đến discharge V2;
- embedding V3 thấy lịch sử V1, V2 và dữ liệu V3 đến discharge V3.

Như vậy vector biểu diễn trạng thái bệnh nhân tại cuối target visit, không chỉ
là bag-of-events riêng của visit.

## 12. Tokenization trước encoder — chưa chạy

Code:

```text
code/context_clues/src/context_clues_pipeline/embedding.py
code/context_clues/embed_visits.py
```

Quy tắc:

1. Chuyển từng mapped event thành `hf_ehr.config.Event`.
2. Gọi `CLMBRTokenizer.convert_event_to_token`.
3. Nếu numeric token không hợp lệ nhưng code token hợp lệ, fallback về
   code-presence.
4. Event có code ngoài tokenizer vocabulary bị bỏ và được phản ánh trong audit.
5. Không thêm BOS/EOS.
6. Chỉ giữ 4.096 token gần nhất:

   ```text
   token_ids[-4096:]
   ```

7. Khi batch, sequence được left-pad.

Audit ghi cho từng visit:

- số prepared event;
- số event tokenized;
- tokenization coverage;
- số numeric fallback;
- số token trước/sau truncation;
- visit có bị truncate không;
- số token của chính target visit;
- số clinical token của chính target visit;
- số historical visit.

Inference bị chặn nếu:

- tokenization coverage dưới 90%; hoặc
- có target visit không còn clinical token của chính nó.

## 13. Cách lấy embedding — chưa chạy

Encoder:

```text
StanfordShahLab/gpt-base-4096-clmbr
```

Model được dùng frozen:

1. Chạy `model.base_model` với `input_ids` và `attention_mask`.
2. Lấy `last_hidden_state` tại vị trí token không-padding cuối cùng.
3. Chuyển float32 trước khi xuất.
4. L2-normalize vector mặc định để dùng cosine retrieval.
5. Kiểm tra toàn bộ vector finite; gặp NaN/Inf thì dừng.

Expected output shape:

```text
[3500, 768]
```

Output cuối dự kiến:

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/embeddings/gpt-base-4096-clmbr/
├── visit_embeddings.parquet
├── visit_embeddings.npy
├── visit_embedding_index.parquet
├── tokenization_audit.parquet
├── tokenization_summary.json
└── manifest.json
```

`visit_embedding_index.parquet` là contract ánh xạ:

```text
row_index -> patient_id -> visit_id
```

## 14. Output data-only hiện có

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/raw_pipeline_v1/
├── manifest.json
├── structured/
│   ├── visits.parquet
│   ├── diagnoses.parquet
│   ├── medicines.parquet
│   ├── procedures.parquet
│   ├── observations.parquet
│   └── manifest.json
└── source_prepared/
    ├── source_events.parquet
    ├── visits.parquet
    ├── visit_event_audit.parquet
    ├── source_table_audit.parquet
    ├── concept_map.csv
    ├── concept_mapping_worklist.csv
    ├── ENCODER_HANDOFF.md
    └── manifest.json
```

Các kiểm tra đã pass trên `vaipe-Z790-UD-AX`:

- 3.500 `visit_id` duy nhất;
- 0 patient/visit ID rỗng;
- 0 orphan key ở bốn event table;
- 734.370 `source_events`;
- `event_id` duy nhất;
- 0 missing `effective_time`;
- raw SHA-256 khớp manifest;
- không có clinical-note hoặc graph artifact;
- `encoder_run=false`;
- `model_weights_used=false`;
- `gpu_used=false`;
- 5/5 unit test pass bằng CPU.

## 15. Cách chạy lại data-only trên server

```bash
ssh vaipe_aiotlab
cd /mnt/disk4/similar_cases_retrieval/code/code/context_clues
./run_data_only_server.sh
```

Script đặt:

```text
CUDA_VISIBLE_DEVICES=""
```

Nó không sử dụng GPU. Mặc định script từ chối overwrite thư mục output không
rỗng. Chỉ dùng `CONTEXT_CLUES_OVERWRITE_SOURCE=1` khi đã chủ động xác nhận cần
ghi đè và đã kiểm tra đúng target.

## 16. Artifact cũ không được dùng tiếp

Artifact cũ:

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/source_prepared/
```

được tạo từ `ehr_preprocessed_full`, không phải trực tiếp từ raw workbook. Nó
được giữ lại để audit nhưng không phải input chuẩn của pipeline hiện tại.

Artifact chuẩn phải bắt đầu từ:

```text
/mnt/disk4/similar_cases_retrieval/data/context_clues/raw_pipeline_v1/
```

Sự khác biệt đã quan sát: snapshot cũ có 5.386 diagnosis thiếu `event_time`,
trong khi raw pipeline hiện tại có 0 diagnosis thiếu thời gian. Vì temporal
cutoff phụ thuộc event time, không được trộn hai lineage này.
