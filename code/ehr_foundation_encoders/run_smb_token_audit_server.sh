#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/ehr_foundation_encoders
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
DATA_ROOT=/mnt/disk4/similar_cases_retrieval/data/ehr_foundation_encoders
PIPELINE_ROOT="$DATA_ROOT/raw_pipeline_v1"
TOKENIZER="$DATA_ROOT/models/SMB-v1_Qwen3-1.7b_multi-objective/tokenizer"
SMB_UTILS="$DATA_ROOT/runtime/smb-utils"
OUTPUT="$PIPELINE_ROOT/adapters/smb_v1_1_7b/tokenization"

if [[ ! -f "$TOKENIZER/tokenizer_manifest.json" ]]; then
  echo "Tokenizer manifest is missing; run run_smb_tokenizer_download_server.sh first" >&2
  exit 1
fi
if [[ ! -d "$SMB_UTILS/src/smb_utils" ]]; then
  echo "Pinned smb-utils runtime is missing; run install_smb_utils_server.sh first" >&2
  exit 1
fi

args=(
  --common-root "$PIPELINE_ROOT/common"
  --tokenizer-root "$TOKENIZER"
  --output-root "$OUTPUT"
  --max-length 3300
  --batch-size "${SMB_TOKENIZER_BATCH_SIZE:-16}"
)
if [[ -n "${SMB_TOKEN_AUDIT_MAX_TARGETS:-}" ]]; then
  args+=(--max-targets "$SMB_TOKEN_AUDIT_MAX_TARGETS")
fi
if [[ "${SMB_OVERWRITE_TOKEN_AUDIT:-0}" == "1" ]]; then
  args+=(--overwrite)
fi

CUDA_VISIBLE_DEVICES="" HF_HOME="$DATA_ROOT/hf_cache" \
  PYTHONPATH="$SMB_UTILS/src" "$PYTHON" \
  "$PIPE/audit_smb_tokens.py" "${args[@]}"
