#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/context_clues
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
WORKBOOK="/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx"
EHR_PREPROCESSING=/mnt/disk4/similar_cases_retrieval/code/code/ehr_graph_embedding/preprocessing
OUTPUT=/mnt/disk4/similar_cases_retrieval/data/context_clues/raw_pipeline_v1

args=(
  --workbook "$WORKBOOK"
  --output-root "$OUTPUT"
  --ehr-preprocessing-root "$EHR_PREPROCESSING"
)
if [[ "${CONTEXT_CLUES_OVERWRITE_SOURCE:-0}" == "1" ]]; then
  args+=(--overwrite)
fi

CUDA_VISIBLE_DEVICES="" "$PYTHON" "$PIPE/prepare_raw_source_data.py" "${args[@]}"
