# Context Clues visit embeddings

Pipeline này đọc trực tiếp workbook EHR raw, tự dựng năm bảng structured trong
thư mục data riêng, rồi chuyển chúng sang input của model
`StanfordShahLab/gpt-base-4096-clmbr`. Output có đúng một embedding cho mỗi
`visit_id`. Pipeline không dùng artifact từ `data/ehr/ehr_preprocessed/`, không
dựng clinical note/graph và không đọc ảnh.

Data-only preprocessing không cần checkpoint:

```bash
./run_data_only_server.sh
```

Nó đọc `/mnt/disk4/similar_cases_retrieval/data/ehr/raw/thông tin bệnh án.xlsx` và
ghi output vào `data/ehr/context_clues/raw_pipeline_v1/`:

- `structured/`: năm bảng được dựng trực tiếp từ các sheet raw;
- `source_prepared/`: toàn bộ structured event, audit, concept-map template và
  `ENCODER_HANDOFF.md`.

Manifest giữ path/SHA-256 của workbook và xác nhận không tiêu thụ snapshot
`ehr_preprocessed`. Đây là stage nên chạy trước khi tải encoder.

`source_prepared/concept_mapping_worklist.csv` loại riêng 16.223 diagnosis
phrase chỉ có text,
nhưng vẫn giữ toàn bộ code-bearing diagnoses và mọi concept thuốc/xét nghiệm/
procedure. Full inventory không bị xóa và vẫn nằm trong `concept_map.csv`.

Tải checkpoint riêng mà không dùng GPU:

```bash
./download_weights_server.sh
```

Weights được ghi tại
`data/ehr/context_clues/weights/gpt-base-4096-clmbr/`, cache tại
`data/ehr/context_clues/hf_cache/`. Script đặt `CUDA_VISIBLE_DEVICES=""`, không
import PyTorch và tạo `weights_manifest.json` kèm revision/SHA-256. Repo là
manual-gated nên tài khoản Hugging Face trên server phải được Stanford duyệt
trước; không dùng checkpoint `*-random` thay thế.

## Thư mục tách biệt

- Code: `code/ehr/context_clues/`
- Input raw trên Vaipe:
  `/mnt/disk4/similar_cases_retrieval/data/ehr/raw/thông tin bệnh án.xlsx`
- Tất cả data/output mới:
  `/mnt/disk4/similar_cases_retrieval/data/ehr/context_clues/`

Output cuối:

```text
data/ehr/context_clues/
├── raw_pipeline_v1/
│   ├── manifest.json
│   ├── structured/
│   │   ├── visits.parquet
│   │   ├── diagnoses.parquet
│   │   ├── medicines.parquet
│   │   ├── procedures.parquet
│   │   └── observations.parquet
│   ├── source_prepared/
│   │   ├── source_events.parquet
│   │   ├── concept_map.csv
│   │   └── manifest.json
│   └── prepared/
│       ├── events.parquet
│       ├── visits.parquet
│       ├── concept_map_snapshot.parquet
│       ├── unmapped_concepts.parquet
│       ├── mapping_audit.parquet
│       └── manifest.json
└── embeddings/gpt-base-4096-clmbr/
    ├── visit_embeddings.parquet
    ├── visit_embeddings.npy
    ├── visit_embedding_index.parquet
    ├── tokenization_audit.parquet
    ├── tokenization_summary.json
    └── manifest.json
```

`visit_embeddings.parquet` chứa `patient_id`, `visit_id`, audit số token và
cột `embedding` dạng list. `visit_embeddings.npy` chứa cùng ma trận theo thứ tự
trong `visit_embedding_index.parquet`.

## Điều kiện bắt buộc trước khi chạy

Checkpoint là public-gated. Tài khoản Hugging Face phải được cấp quyền tại
[model card](https://huggingface.co/StanfordShahLab/gpt-base-4096-clmbr) và đã
đăng nhập trên Vaipe. Không ghi token vào script hay repository.

```bash
huggingface-cli login
```

Dùng Python 3.10 hoặc 3.11 và một environment riêng vì `hf-ehr==0.1.4` pin
NumPy/Pandas khác environment graph hiện tại.

```bash
conda create -y -p /mnt/disk1/khangdp/conda_envs/context_clues python=3.11
/mnt/disk1/khangdp/conda_envs/context_clues/bin/python -m pip install \
  -r /mnt/disk4/similar_cases_retrieval/code/code/ehr/context_clues/requirements.txt
```

## Vì sao cần concept map

Tokenizer không hiểu mã bệnh viện local hay tên thuốc/xét nghiệm tiếng Việt.
Nó chỉ giữ code thuộc vocabulary pretrained như `SNOMED/...`, `LOINC/...`,
`RxNorm/...` và `CPT4/...`; code ngoài vocabulary bị loại hoàn toàn. Không nên
gán mã bằng fuzzy matching rồi coi như ground truth.

Lần chạy đầu tạo template rồi dừng:

```bash
cd /mnt/disk4/similar_cases_retrieval/code/code/ehr/context_clues
./run_server.sh
```

Trong `raw_pipeline_v1/source_prepared/concept_map.csv`, điền:

- `target_code`: code OMOP chuẩn theo dạng `VOCABULARY/concept_code`;
- `mapping_status=approved`: chỉ sau khi mapping đã được review;
- `mapping_method`: ví dụ `athena_maps_to`, `exact_loinc`, `manual_review`;
- `use_value=true`: chỉ cho lab exact đã harmonize đúng scale;
- `value_multiplier`, `value_offset`: đổi giá trị sang scale đã xác nhận.

Mặc định observation chỉ đóng góp code-presence. Numeric chỉ được dùng khi
`result_type=numeric_exact`, mapping được approve và `use_value=true`. Censored,
interval, approximate và proxy không bị giả thành số exact.

## Sinh embedding

Sau khi review concept map, chạy lại:

```bash
./run_server.sh
```

Mỗi target visit dùng timeline của cùng bệnh nhân từ đầu lịch sử đến
`discharge_time` của visit đó, giữ 4.096 token gần nhất, left-pad như evaluation
code chính thức, rồi lấy last hidden state ở token cuối. Vector mặc định được
L2-normalize để dùng cosine retrieval.

Pipeline chặn inference khi:

- event mapping coverage dưới 50%;
- tokenization coverage dưới 90%;
- có visit không còn clinical token nào của chính visit đó.

Audit tokenizer mà chưa tải model weights:

```bash
python embed_visits.py \
  --prepared-root /mnt/disk4/similar_cases_retrieval/data/ehr/context_clues/raw_pipeline_v1/prepared \
  --output-root /mnt/disk4/similar_cases_retrieval/data/ehr/context_clues/audit \
  --audit-only
```

Nếu concept map thay đổi, materialize lại data mà không sửa dữ liệu gốc:

```bash
CONTEXT_CLUES_REBUILD_PREPARED=1 ./run_server.sh
```

Chỉ overwrite embedding khi chủ động yêu cầu:

```bash
CONTEXT_CLUES_OVERWRITE_EMBEDDINGS=1 ./run_server.sh
```

## Kiểm thử

```bash
python -m pytest -q tests
```

Implementation bám theo inference/tokenization trong repository chính thức
[som-shahlab/hf_ehr](https://github.com/som-shahlab/hf_ehr). Model được dùng
frozen; pipeline này không fine-tune trên cohort 3.500 visit.
