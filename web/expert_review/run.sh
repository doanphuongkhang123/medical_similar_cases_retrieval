#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${EXPERT_REVIEW_PYTHON:-/mnt/disk4/namtn/conda_envs/retrieval/bin/python}"
PORT="${EXPERT_REVIEW_PORT:-8501}"

cd "$APP_DIR"
exec "$PYTHON" -m streamlit run app.py \
  --server.address 127.0.0.1 \
  --server.port "$PORT" \
  --server.headless true
