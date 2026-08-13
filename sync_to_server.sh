#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="${SCRIPT_DIR}/"
REMOTE_HOST="vaipe_aiotlab"
REMOTE_DIR="/mnt/disk4/similar_cases_retrieval/code/"

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
  --exclude='preprocessed/' \
  "$LOCAL_DIR" \
  "${REMOTE_HOST}:${REMOTE_DIR}"

echo "Sync completed."
