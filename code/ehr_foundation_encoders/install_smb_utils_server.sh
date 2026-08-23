#!/usr/bin/env bash
set -euo pipefail

REVISION=4f963e124a940c2ddbc10f50a7448a6e20654555
RUNTIME=/mnt/disk4/similar_cases_retrieval/data/ehr_foundation_encoders/runtime/smb-utils

if [[ -d "$RUNTIME/.git" ]]; then
  actual=$(git -C "$RUNTIME" rev-parse HEAD)
  if [[ "$actual" != "$REVISION" ]]; then
    echo "Refusing to alter existing smb-utils checkout at revision $actual" >&2
    exit 1
  fi
else
  if [[ -e "$RUNTIME" ]]; then
    echo "Refusing to overwrite existing non-Git path: $RUNTIME" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$RUNTIME")"
  CUDA_VISIBLE_DEVICES="" git clone https://github.com/standardmodelbio/smb-utils.git "$RUNTIME"
  git -C "$RUNTIME" checkout --detach "$REVISION"
fi

echo "$RUNTIME/src"
