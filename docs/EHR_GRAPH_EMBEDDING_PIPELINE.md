# EHR → Graph → Visit Embedding

**Status:** Baseline đã chạy trên dữ liệu thật với self-supervised learning.
**Updated:** 2026-08-14.
**Unit:** `1 SoBenhAn = 1 visit = 1 sparse graph = 1 embedding`.
**Scope:** EHR workbook; chưa gồm PDF, ảnh hoặc DICOM.

Tài liệu này là bản ghi tập trung cho implementation trong
`code/ehr_graph_pipeline/`. Embedding hiện tại là representation baseline,
không phải kết quả clinical retrieval đã được đánh giá.

## Mục tiêu và luồng

```text
EHR workbook (read-only)
  → canonical visits/events/relations
  → graph dị thể thưa cho mỗi visit
  → Graph Transformer 2 lớp
  → masked-node self-supervised training
  → L2-normalized embedding 256 chiều
```

Đây là phần visit-level của GT-BEHRT. Bài gốc còn đưa chuỗi visit theo bệnh
nhân vào BERT; baseline này dừng ở visit embedding.

## Data và experiment layout

Chỉ đọc dữ liệu thật trên `vaipe_aiotlab`.

```text
/mnt/disk4/similar_cases_retrieval/data/
├── raw/                              # nguồn gốc, read-only
│   ├── thông tin bệnh án.xlsx
│   ├── CT/  MRI/  XQ/
│   ├── 2025 PET CT/
│   └── PDF-grBA/
├── experiments/
│   └── <experiment_id>/
│       ├── preprocessed/
│       ├── graphs/
│       ├── model/
│       ├── embeddings/
│       └── logs/
├── ehr_preprocessed/                 # pipeline khác
└── processed/                         # pipeline khác
```

Không copy raw data về local hoặc Git. Derived artifact của mỗi run phải ở
`data/experiments/<experiment_id>/`; scripts từ chối ghi đè stage đã tồn tại.

## Workbook và joins đã dùng

Workbook nguồn:

```text
/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx
```

| Sheet | Dòng | Vai trò baseline |
|---|---:|---|
| `thông tin bệnh án` | 3.500 | `VISIT`, `TEXT_SECTION`, `VITAL` |
| `chỉ định DVKT` | 151.248 | `ORDER` |
| `Thuốc` | 219.167 | `PRESCRIPTION`, `MEDICATION` |
| `KQCLS` | 312.251 | `LAB_RESULT` |
| `Phẫu thuật thủ thuật` | 11.342 | `PROCEDURE` |

Khóa graph là `SoBenhAn`, unique 3.500/3.500. Joins:

```text
ORDER.SoBenhAn              → VISIT.SoBenhAn
MEDICATION.sobenhan         → VISIT.SoBenhAn
LAB_RESULT.SoBenhAn         → VISIT.SoBenhAn
LAB_RESULT.YeuCauChiTiet_Id → ORDER.YeuCauChiTiet_Id
PROCEDURE.YeuCauChiTiet_Id  → ORDER → VISIT
```

Run baseline có 0 lab-order link không ghép được. Các ID chỉ dùng để join và
trace lineage, không dùng trực tiếp làm feature.

## Feature policy hiện thực

Được dùng: allow-listed text-section (chỉ hash, chưa encode text), vital số,
tên/thời điểm order, thuốc, lab, và thủ thuật. Lab giữ số hoặc categorical
value, comparison operator và unit; giá trị không parse được không thành 0.

Không dùng: direct identifier/hành chính, raw clinical text, discharge/outcome
field, `MaICD`/`ICD_phu`, PDF, ảnh, DICOM, và diagnosis node. Không ghi raw
`text_value` vào `events.parquet`.

## Canonical tables

`preprocess_ehr.py` ghi vào `RUN_DIR/preprocessed/`:

| File | Nội dung |
|---|---|
| `visits.parquet` | một row/visit; time, department, split |
| `events.parquet` | một row/event, không raw text |
| `relations.parquet` | `has_drug`, `has_result`, `has_procedure` |
| `concept_vocab.json` | vocab fit từ train visits |
| `numeric_stats.json` | train-only median/IQR theo concept/unit |
| `preprocessing_manifest.json` | workbook hash, snapshot, split, count |

Numeric value được normalize khi build graph:

```text
value_norm = clip((value - train_median) / train_IQR, -5, 5)
```

Nếu IQR không hợp lệ, implementation dùng `1.0`. Đây là baseline, chưa có
fallback hierarchy theo test/global.

## Snapshot và split

Code hỗ trợ `admission`, `first_24h`, `full_visit`. Run hiện dùng:

```yaml
snapshot_mode: full_visit
split: deterministic hash of visit_id
seed: 20260812
fractions: train 0.70, validation 0.15, test 0.15
```

`full_visit` là retrospective representation, không phải admission-time model.
Split hiện visit-disjoint, chưa chứng minh patient-disjoint. Vocab và stats chỉ
fit từ train split.

## Graph schema

Node types:

```text
VISIT
TEXT_SECTION  VITAL  ORDER  LAB_RESULT
PRESCRIPTION  MEDICATION  PROCEDURE
```

Edges:

```text
VISIT ──has_event────> tất cả event node
PRESCRIPTION ─has_drug────> MEDICATION
ORDER ────────has_result──> LAB_RESULT
ORDER ────────has_procedure> PROCEDURE
LAB_RESULT ───next_same_test> kết quả liên tiếp, cùng visit/cùng test
```

Mọi edge có reverse edge. Temporal edge chỉ nối kết quả kế tiếp có timestamp
hợp lệ; không có all-pairs edge. Graph JSON lưu tại `RUN_DIR/graphs/graphs/`;
`graph_index.parquet` ghi path, split, node count và edge count.

## Graph Transformer và readout

```yaml
hidden_dimension: 256
output_dimension: 256
layers: 2
attention_heads: 4
dropout: 0.2
```

Node input kết hợp concept embedding (64), node-type embedding (16), và
numeric/time MLP (32), rồi project lên 256. Hai relation-aware attention layer
dùng relation embedding, residual connection và LayerNorm.

`VISIT` là virtual readout node (`<VST>` tương đương GT-BEHRT):

```text
h_visit = hidden state VISIT sau layer cuối
h_pool  = attention-pooling trên event nodes
z_visit = L2Normalize(MLP([h_visit || h_pool]))
```

Code chạy từng graph per forward pass, chưa graph minibatch. VRAM của lần train
baseline khoảng 656 MiB, nhưng throughput GPU chưa tối ưu.

## Training đã chạy: self-supervised NAM

Training không dùng diagnosis label hoặc pair “tương tự”. NAM là stage đầu của
GT-BEHRT:

1. Chọn khoảng 15% node train có concept khác `UNK`.
2. Thay concept ID bằng mask/`UNK`.
3. Chạy hai Graph Transformer layer.
4. `concept_head` dự đoán concept gốc bằng cross-entropy.
5. Backpropagate qua toàn bộ node encoder và model.

Run `gt_behrt_visit_20260812` train 5 epoch trên 2.464 train graph:

| Epoch | Masked-concept loss |
|---:|---:|
| 1 | 2.8682 |
| 2 | 2.2787 |
| 3 | 2.1282 |
| 4 | 2.0438 |
| 5 | 1.9894 |

Loss giảm xác nhận trọng số đã học; embedding không random. NAM đơn lẻ vẫn
không chứng minh chất lượng retrieval lâm sàng.

## Kết quả run đã xác minh

```text
/mnt/disk4/similar_cases_retrieval/data/experiments/gt_behrt_visit_20260812/
```

| Check | Kết quả |
|---|---:|
| Canonical visit | 3.500 |
| Canonical event | 760.276 |
| Business relation | 542.760 |
| Graph độc lập | 3.500 |
| Embedding | 3.500 |
| Embedding shape | `3500 × 256` |
| Missing/extra visit | 0 / 0 |
| L2 norm | 0.99999988 đến 1.00000012 |

Artifact chính là `embeddings/visit_embeddings.parquet`, có các cột
`visit_id`, `split`, `snapshot_mode`, `embedding_version`, `embedding`.
Manifest ghi `model_trained: true`, nhưng `retrieval_ready: false` và
`clinical_retrieval_validated: false`.

## Chạy một run mới

```bash
cd /mnt/disk4/similar_cases_retrieval/code
RUN_ID=gt_behrt_visit_002
RUN_DIR=/mnt/disk4/similar_cases_retrieval/data/experiments/$RUN_ID

tmux new-session -d -s "$RUN_ID-preprocess" \
  "bash code/ehr_graph_pipeline/run_full_visit_preprocessing.sh '$RUN_DIR'"

# Chạy sau khi preprocess/graph đã thành công.
tmux new-session -d -s "$RUN_ID-train" \
  "bash code/ehr_graph_pipeline/run_pretrain_and_embed.sh '$RUN_DIR'"
```

Scripts tự activate `/mnt/disk1/khangdp/conda_envs/scr_env` và log vào
`$RUN_DIR/logs/`. Không dùng `data/raw/` làm output.

## Kiểm thử

```bash
cd /mnt/disk4/similar_cases_retrieval/code
source "$(/home/vaipe/miniconda3/bin/conda info --base)/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env
PYTHONPATH=code python -m unittest ehr_graph_pipeline.tests.test_ehr_pipeline -v
```

Tests dùng fixture giả và kiểm tra lab parser, cutoff, không raw text trong
graph, cùng shape/L2 norm của encoder.

## Chưa có / việc tiếp theo

- Numeric/text masking, relation prediction, VICReg/Barlow Twins.
- Text encoder tiếng Việt/clinical được phê duyệt local-only.
- Diagnosis node, PDF/report, imaging/DICOM.
- Patient-sequence BERT theo GT-BEHRT gốc.
- Patient-disjoint split, relevance label, cosine index chính thức và các metric
  Precision/Recall/mAP/nDCG.

Vector hiện tại là self-supervised representation baseline, chưa là bằng chứng
rằng các visit truy hồi tương tự nhau về mặt lâm sàng.

## File code

| File | Vai trò |
|---|---|
| `preprocess_ehr.py` | workbook → canonical tables/split/vocab/stats |
| `build_visit_graphs.py` | canonical tables → sparse graph JSON |
| `gt_behrt_visit.py` | Graph Transformer/readout |
| `pretrain_graph_encoder.py` | NAM self-supervised pretraining |
| `embed_visits.py` | checkpoint → embedding parquet/manifest |
| `run_full_visit_preprocessing.sh` | preprocess + graph stage |
| `run_pretrain_and_embed.sh` | train + embedding stage |
| `tests/test_ehr_pipeline.py` | fixture/unit tests |
