# Code pipeline handoff

**Cập nhật:** 2026-08-18

**Đơn vị xuyên suốt:** `visit_id`

**Phạm vi code hiện hành:** semantic EHR preprocessing v2, structured-EHR graph
SSL ba stage, xuất visit embedding, retrieval EHR + note và expert review.

Context Clues frozen inference nằm độc lập tại `code/context_clues/`. Pipeline
đọc trực tiếp workbook `data/raw/thông tin bệnh án.xlsx`, tự dựng năm bảng
structured trong `data/context_clues/raw_pipeline_v1/`, bắt buộc local-code →
OMOP mapping có review rồi dựng timeline đến discharge. Checkpoint
`StanfordShahLab/gpt-base-4096-clmbr` là gated; data-only raw đã hoàn thành
nhưng artifact embedding 3.500 visit chưa được tạo.

Tài liệu này mô tả contract đúng theo code đang có. Dữ liệu thật, checkpoint,
embedding và SQLite review là runtime artifact trên Vaipe, không đưa vào Git.

## 1. Luồng end-to-end

```text
Workbook EHR gốc
  -> preprocessing/preprocess_ehr_tables_v2.py
  -> semantic Parquet tables + manifest/audit tables
  -> ehr_graph_ssl.data.load_structured_dataset
  -> một sparse typed graph cho mỗi visit_id
  -> Stage 1: typed NAM + exact-numeric masking
  -> Stage 2: Stage 1 + missing-node prediction
  -> Stage 3: Stage 2 + VICReg + local/global MI
  -> best.pt + visit_embeddings.parquet + quality report

visit_embeddings.parquet + clinical-note embeddings
  -> web/expert_review/retrieval.py
  -> exact cosine Top 20 trên fused EHR+note vector
  -> Streamlit expert review
  -> append-only ground_truth.sqlite3
```

Clinical note và image không đi vào EHR graph encoder. Image cũng chưa tham gia
expert-review baseline vì image linkage chỉ phủ một phần cohort.

## 2. Semantic preprocessing v2

### Entry point

- Code: `code/ehr_graph_embedding/preprocessing/preprocess_ehr_tables_v2.py`
- V2 tái sử dụng relational builders của `preprocess_ehr_tables.py`, nhưng thay
  clean/time helpers và tự xây bảng `observations` để không làm mất semantics.

Chạy trên Vaipe:

```bash
PROJECT=/mnt/disk4/similar_cases_retrieval/code
WORKSPACE="$PROJECT/code/ehr_graph_embedding"
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
WORKBOOK=/path/to/source.xlsx
OUTPUT=/mnt/disk4/similar_cases_retrieval/data/preprocessed_v2

cd "$WORKSPACE"
"$PYTHON" preprocessing/preprocess_ehr_tables_v2.py \
  --workbook "$WORKBOOK" \
  --output "$OUTPUT"
```

### Result parser

`parse_result` giữ riêng raw value và semantic representation:

| Input class | `result_type` | Stored representation |
|---|---|---|
| missing literal | `missing` | không có numeric/proxy |
| exact number | `numeric_exact` | `result_numeric`, `value_proxy` |
| `<`, `<=`, `>`, `>=` | `numeric_censored` | operator, lower/upper bound, proxy |
| numeric range | `numeric_interval` | lower, upper, midpoint proxy |
| approximate marker | `numeric_approx` | numeric value, approximate subtype |
| scientific notation | `numeric_with_unit` | expanded numeric value và unit suffix |
| polarity/normality/status | `categorical` | canonical category và category group |
| ordinal/plus scale | `semi_quantitative` | canonical category và ordinal level |
| còn lại | `free_text` | raw text chỉ ở preprocessing table |

Proxy là model input hỗ trợ biểu diễn, không phải ground-truth regression target:

- interval: midpoint;
- left-censored non-negative: half upper bound;
- right-censored: lower bound cộng median tail của cùng test/unit nếu có, nếu
  không thì fallback lower bound;
- exact/approx/scientific: parsed numeric value.

### Output contract

Các bảng chính:

- `visits.parquet`
- `diagnoses.parquet`
- `medicines.parquet`
- `procedures.parquet`
- `clinical_notes.parquet`
- `observations.parquet`
- `visit_ehr.parquet`
- `graph_nodes.parquet`, `graph_edges.parquet`

Audit/metadata:

- `column_profile.parquet`
- `value_dictionary.parquet`
- `normalization_review_candidates.parquet`
- `manifest.json`

`observations.parquet` giữ cả `result_text`, exact numeric, proxy method,
semantic type, censoring bounds, category, ordinal level và normalized test/unit.
EHR graph loader chỉ đọc projection cần thiết; raw result text không được đưa
vào graph model hoặc embedding artifact.

## 3. Structured graph construction

### Input và split

`load_structured_dataset` chỉ đọc năm bảng: `visits`, `diagnoses`, `medicines`,
`procedures`, `observations`. Nó loại `clinical_notes`, `visit_ehr` và các graph
table đã materialize để graph SSL có một nguồn contract duy nhất.

Split pretraining là hash deterministic theo `visit_id`, seed mặc định
`20260812`, tỷ lệ 70/15/15. Vocabulary, numeric median/IQR và IDF chỉ fit trên
train. Split này chưa patient-disjoint và không được coi là retrieval evaluation
protocol cuối cùng.

### Node và token

Node types:

- `VISIT`
- `DIAGNOSIS`
- `MEDICINE`
- `PROCEDURE`
- `OBSERVATION`

Categorical concept được SHA-256 thành opaque token 24 hex characters. Diagnosis
chỉ dùng controlled code; không fallback sang mô tả tự do. Observation token gồm
test code/name, unit, result type, operator và category khi là categorical hoặc
semi-quantitative. Vì vậy raw clinical text không nằm trong vocabulary.

Aggregation:

- diagnosis: `visit_id + diagnosis token`;
- medicine: `visit_id + concept token + relative 24-hour bucket`;
- procedure: `visit_id + order_id + procedure token`;
- observation: `visit_id + order_id + observation token`.

### Edges

Graph có các cặp relation hai chiều:

- visit–diagnosis, visit–medicine, visit–procedure, visit–observation;
- procedure–result qua cùng `order_id`;
- next/previous cho cùng test theo thời gian;
- next/previous cho cùng medication concept theo thời gian.

### Numeric feature vector

Mỗi node có vector 16 chiều, đúng thứ tự sau:

1. proxy value robust-normalized;
2. `log1p(count)`;
3. relative time / 168 giờ, clip `[-4, 4]`;
4. has proxy;
5. has time;
6. missing proxy;
7. augmented numeric-mask flag;
8. censored flag;
9. interval flag;
10. categorical/status flag;
11. normalized lower bound;
12. normalized upper bound;
13. has lower bound;
14. has upper bound;
15. ordinal level / 4, clip `[0, 1]`;
16. has ordinal flag.

Value và bounds được robust-normalize theo train median/IQR của token rồi clip
`[-5, 5]`. Numeric reconstruction target chỉ tồn tại cho
`numeric_exact`; censored/interval/approximate/category không bị biến thành exact
label. Thay đổi 7 -> 16 chiều làm checkpoint từ encoder contract cũ không tương
thích với numeric encoder mới.

## 4. Graph model và ba stage SSL

Model ở `src/ehr_graph_ssl/model.py` là sparse relation-aware Graph Transformer.
Input node representation ghép concept embedding, type embedding và numeric
encoder. Output được readout ở graph level và L2-normalize thành visit embedding.

### Stage 1

- Typed node attribute masking (NAM): mask concept theo node type và predict
  concept ID bằng cross entropy.
- Numeric masking: chỉ chọn exact-numeric observation, zero input proxy, bật
  augmented-mask flag và reconstruct robust-normalized target bằng Smooth L1.
- Masking không được xóa observable concept cuối cùng của diagnosis/medicine/
  procedure core type.

### Stage 2

Giữ toàn bộ Stage 1 và thêm Missing Node Prediction:

- chọn node type gần uniform;
- chọn node trong type bằng IDF weighting;
- remove một node nhưng không làm mất core type cuối cùng;
- predict concept đã remove từ raw graph readout.

Stage 2 bắt buộc load `best.pt` của Stage 1. Model config, vocabulary, train
statistics, IDF, dataset manifest và data fingerprint phải khớp chính xác.

### Stage 3

Giữ base objectives của Stage 2 và thêm hai masked graph views:

- VICReg similarity trên paired current views;
- variance/covariance trên current vectors và optional detached FP32 history;
- local/global MI với negative graph tạo bằng cách hoán vị categorical concept
  trong cùng node type và exact 24-hour bucket.

Similarity và MI luôn chỉ dùng current group. History queue không giữ autograd,
reset mỗi epoch và chỉ hỗ trợ moment estimates của variance/covariance. Stage 3
bắt buộc load Stage 2 checkpoint với cùng fingerprint.

### Training orchestration

`scripts/run_semantic_v2_full.sh` chạy Stage 1 -> 2 -> 3 tuần tự trên GPU 0,
20 epoch tối đa, early stopping patience 5, AMP, gradient accumulation 8 và
export embedding ở mỗi stage. Script từ chối overwrite output stage đã tồn tại.

```bash
cd /mnt/disk4/similar_cases_retrieval/code/code/ehr_graph_embedding
./scripts/run_semantic_v2_full.sh
```

Các path `workspace`, `data_root`, `experiment_root` và `python` ở đầu script là
server-specific; chỉnh đúng host trước khi chạy ở môi trường khác.

Mỗi stage ghi:

- `run_manifest.json`
- `history.json`, `validation_metrics.json`, `training_summary.json`
- `last.pt`, `best.pt`
- `visit_embeddings.parquet` khi có `--export-embeddings`
- `embedding_quality_report.json`

Early stopping theo validation reconstruction loss. Quality report kiểm tra
finite vector, L2 norm, effective rank, top-1 hub fraction, graph-size
correlation và cross-view retrieval so với shuffled null. Đây là engineering
proxy, không phải clinical validation.

## 5. Expert-review retrieval

Code nằm ở `web/expert_review/`.

`FusedRetrievalIndex.from_files`:

1. đọc EHR `visit_embeddings.parquet` (`visit_id`, `embedding`);
2. đọc note embedding dạng Parquet hoặc CSV wide/list;
3. mean-pool duplicate note rows theo visit nếu cần;
4. L2-normalize riêng từng modality;
5. lấy giao `visit_id` của hai modality;
6. nhân positive weights, concatenate và L2-normalize lần cuối;
7. exact cosine với toàn candidate matrix, loại chính query và trả Top 20.

Mặc định `ehr_weight = text_weight = 1.0`. Vì concatenate hai block đã
L2-normalize, contribution thực tế tỷ lệ theo bình phương weight. Retrieval này
là baseline phục vụ thu ground truth; chưa phải protocol đánh giá patient-split.

Streamlit chỉ hiển thị EHR cho query/candidate. Một submission hợp lệ phải chọn
1–19 candidate hoặc đánh dấu không có candidate phù hợp. SQLite lưu append-only:

- `review_submissions`: reviewer/query/time/config/query snapshot/note;
- `review_selections`: selected visit, retrieval rank và score.

Chạy:

```bash
cd /mnt/disk4/similar_cases_retrieval/code/web/expert_review
./run.sh
```

Các environment override được liệt kê trong `web/expert_review/README.md`.

## 6. Verification

Preprocessing v1/v2 và expert review cần `numpy`, `pandas`, `pyarrow`; graph SSL
cần thêm `torch`. Các lệnh test chuẩn:

```bash
cd code/ehr_graph_embedding
python -m unittest discover -s preprocessing/tests -v
PYTHONPATH=src python -m unittest discover -s tests -v

cd ../../web/expert_review
python -m unittest discover -s tests -v
```

Smoke run GNN nên dùng `--limit-visits` và output directory mới. Không reuse
checkpoint pre-semantic-v2 vì input feature dimension đã đổi.

## 7. Khi agent khác sửa pipeline

1. Giữ `visit_id` là retrieval unit và không đưa raw text vào graph encoder.
2. Nếu đổi observation schema/feature order, cập nhật đồng thời preprocessor,
   `data.py`, model/checkpoint contract, tests và tài liệu này.
3. Nếu đổi split/vocab/statistics, checkpoint fingerprint cũ phải bị từ chối.
4. Stage 2/3 luôn bắt đầu từ predecessor `best.pt`, không skip stage.
5. Không ghi data thật, embedding, checkpoint, SQLite, slide/render hoặc log
   runtime vào Git.
6. Clinical relevance phải đến từ expert review/evaluation protocol; engineering
   quality gates không thay thế ground truth.
