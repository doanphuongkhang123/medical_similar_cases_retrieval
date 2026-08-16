# EHR graph embedding — three-stage SSL

Pipeline tạo một graph cho mỗi visit và xuất một embedding 256 chiều đã
L2-normalize. Clinical note và image không đi vào encoder này.

Split hiện tại được hash theo `visit_id` với tỉ lệ train/validation/test
70/15/15. Đây là split phục vụ pretraining hiện hành, chưa phải protocol
patient-disjoint cuối cùng cho đánh giá retrieval.

## Graph

- Node: `VISIT`, `DIAGNOSIS`, `MEDICINE`, `PROCEDURE`, `OBSERVATION`.
- Edge: visit–event, procedure–result, chuỗi observation cùng test và chuỗi
  medication cùng concept theo bucket 24 giờ.
- Vocabulary, IDF và numeric statistics chỉ fit trên train.

## Pretraining

1. Stage 1: typed node masking + numeric observation reconstruction.
2. Stage 2: Stage 1 + missing-node prediction.
3. Stage 3: Stage 2 + similarity/variance/covariance + local/global MI.

Stage 2 phải nhận checkpoint Stage 1; Stage 3 phải nhận checkpoint Stage 2 có
cùng data fingerprint.

## Run trên Vaipe

```bash
PROJECT=/mnt/disk4/similar_cases_retrieval/code
WORKSPACE="$PROJECT/code/ehr_graph_embedding"
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
DATA=/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/ehr_preprocessed_full
RUN=/mnt/disk4/similar_cases_retrieval/data/experiments/ehr_graph_stage1_001

PYTHONPATH="$WORKSPACE/src" "$PYTHON" -m ehr_graph_ssl.train \
  --data-root "$DATA" --output "$RUN" --stage 1 --epochs 20 \
  --hidden-dim 256 --output-dim 256 --layers 4 --heads 8 \
  --early-stopping-patience 5 --export-embeddings --amp
```

Output chính là `visit_embeddings.parquet` và
`embedding_quality_report.json`. Pipeline dừng tại embedding, không tạo index
hoặc candidate pool.

Workbook preprocessing dùng
`preprocessing/preprocess_ehr_tables.py`; dữ liệu thật chỉ chạy trên Vaipe.
