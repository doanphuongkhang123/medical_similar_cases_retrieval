#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/ehr/ehr_foundation_encoders
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
PIPELINE_ROOT=/mnt/disk4/similar_cases_retrieval/data/ehr/ehr_foundation_encoders/raw_pipeline_v1
SMB_UTILS=/mnt/disk4/similar_cases_retrieval/data/ehr/ehr_foundation_encoders/runtime/smb-utils
OUTPUT="$PIPELINE_ROOT/adapters/smb_v1_1_7b/serialization"

if [[ ! -d "$SMB_UTILS/src/smb_utils" ]]; then
  echo "Pinned smb-utils runtime is missing; run install_smb_utils_server.sh first" >&2
  exit 1
fi

args=(
  --common-root "$PIPELINE_ROOT/common"
  --output-root "$OUTPUT"
)
if [[ -n "${SMB_SERIALIZATION_MAX_TARGETS:-}" ]]; then
  args+=(--max-targets "$SMB_SERIALIZATION_MAX_TARGETS")
fi
if [[ "${SMB_OVERWRITE_SERIALIZATION_AUDIT:-0}" == "1" ]]; then
  args+=(--overwrite)
fi

CUDA_VISIBLE_DEVICES="" PYTHONPATH="$SMB_UTILS/src" "$PYTHON" \
  "$PIPE/audit_smb_serialization.py" "${args[@]}"
