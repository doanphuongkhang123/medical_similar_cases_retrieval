#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/ehr/ehr_foundation_encoders
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
WORKBOOK="/mnt/disk4/similar_cases_retrieval/data/ehr/raw/thông tin bệnh án.xlsx"
EHR_PREPROCESSING=/mnt/disk4/similar_cases_retrieval/code/code/ehr/ehr_graph_embedding/preprocessing
OUTPUT=/mnt/disk4/similar_cases_retrieval/data/ehr/ehr_foundation_encoders/raw_pipeline_v1

args=(
  --workbook "$WORKBOOK"
  --output-root "$OUTPUT"
  --ehr-preprocessing-root "$EHR_PREPROCESSING"
)
if [[ "${SMB_OVERWRITE_DATA:-0}" == "1" ]]; then
  args+=(--overwrite)
fi

CUDA_VISIBLE_DEVICES="" "$PYTHON" "$PIPE/prepare_smb_data.py" "${args[@]}"
