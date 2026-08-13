# GT-BEHRT-Visit EHR pipeline

This module implements the first usable GT-BEHRT-Visit path for the project's
workbook: canonical EHR tables → one sparse heterogeneous graph per `SoBenhAn`
→ a 256-dimensional L2-normalized visit vector.

It deliberately excludes discharge/outcome fields and direct identifiers from
model features.  Raw clinical text is hashed during canonicalization and does
not enter graph tensors in this initial structured-data baseline; a locally
approved Vietnamese clinical text encoder can be added later.

## Server run

Run on the server after synchronizing code. `scr_env` must contain the packages
in `requirements.txt`.

```bash
cd /mnt/disk4/similar_cases_retrieval/code
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env

python code/ehr_graph_pipeline/preprocess_ehr.py \
  --workbook '/mnt/disk4/similar_cases_retrieval/data/thông tin bệnh án.xlsx' \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr_graph_preprocessed \
  --snapshot-mode full_visit
python code/ehr_graph_pipeline/build_visit_graphs.py \
  --input /mnt/disk4/similar_cases_retrieval/data/ehr_graph_preprocessed \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr_graph_dataset
```

Pretrain the checkpoint on the train split before embedding. This is a
self-supervised initialization, not a clinical-quality or retrieval-quality
claim; label-based evaluation remains required.

```bash
python code/ehr_graph_pipeline/pretrain_graph_encoder.py \
  --graphs /mnt/disk4/similar_cases_retrieval/data/ehr_graph_dataset \
  --canonical /mnt/disk4/similar_cases_retrieval/data/ehr_graph_preprocessed \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr_graph_model/gt_behrt_visit.pt \
  --epochs 5
python code/ehr_graph_pipeline/embed_visits.py \
  --graphs /mnt/disk4/similar_cases_retrieval/data/ehr_graph_dataset \
  --canonical /mnt/disk4/similar_cases_retrieval/data/ehr_graph_preprocessed \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr_graph_embeddings \
  --checkpoint /path/to/gt_behrt_visit.pt
```

Full pretraining is intentionally not launched until the pending snapshot,
patient split, text-policy, and similarity-label decisions in
`docs/GT_BEHRT_VISIT_PIPELINE.md` are approved.

## Create a relationally consistent CSV preview

The preview command samples visits first, then retains all related event rows,
graph nodes, and graph edges. This keeps each sampled visit graph complete.

```powershell
python code/preprocess_code/create_csv_preview.py `
  --input preprocessed/csv `
  --output preprocessed/preview_100_visits `
  --n-visits 100 `
  --seed 20260813
```

The command refuses to overwrite an existing output directory. Its metadata
records the seed, row counts, and graph-integrity validation results.
