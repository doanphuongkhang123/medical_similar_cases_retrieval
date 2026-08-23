#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/ehr_foundation_encoders
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
DATA_ROOT=/mnt/disk4/similar_cases_retrieval/data/ehr_foundation_encoders
CHECKPOINT="$DATA_ROOT/models/SMB-v1_Qwen3-1.7b_multi-objective/checkpoint"
CACHE="$DATA_ROOT/hf_cache"

args=(--output-root "$CHECKPOINT" --cache-root "$CACHE")
if [[ "${SMB_OVERWRITE_CHECKPOINT:-0}" == "1" ]]; then
  args+=(--overwrite)
fi

CUDA_VISIBLE_DEVICES="" HF_HOME="$CACHE" "$PYTHON" \
  "$PIPE/download_smb_checkpoint.py" "${args[@]}"
