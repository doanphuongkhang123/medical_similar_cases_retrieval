#!/usr/bin/env bash

set -euo pipefail

LOCAL_DIR="/Users/k/Documents/work/SimilarCasesRetrieval/"
REMOTE_HOST="vaipe_aiotlab"
REMOTE_DIR="/mnt/disk4/khangdp/similar_cases_retrieval/"

ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"

rsync -avzh --progress \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='.DS_Store' \
  --exclude='*.pyc' \
  --exclude='data/' \
  --exclude='datasets/' \
  --exclude='checkpoints/' \
  --exclude='outputs/' \
  "$LOCAL_DIR" \
  "${REMOTE_HOST}:${REMOTE_DIR}"

echo "Sync completed."
