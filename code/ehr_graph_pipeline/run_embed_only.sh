#!/usr/bin/env bash
set -euo pipefail

cd /mnt/disk4/similar_cases_retrieval/code
mkdir -p logs
exec > logs/gt_behrt_reembed_20260812.log 2>&1
conda_base="$(/home/vaipe/miniconda3/bin/conda info --base)"
source "$conda_base/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env

python code/ehr_graph_pipeline/embed_visits.py \
  --graphs /mnt/disk4/similar_cases_retrieval/data/ehr_graph_dataset \
  --canonical /mnt/disk4/similar_cases_retrieval/data/ehr_graph_preprocessed \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr_graph_embeddings \
  --checkpoint /mnt/disk4/similar_cases_retrieval/data/ehr_graph_model/gt_behrt_visit.pt
