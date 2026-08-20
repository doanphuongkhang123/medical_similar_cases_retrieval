#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/context_clues
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
ROOT=/mnt/disk4/similar_cases_retrieval/data/context_clues
WEIGHTS=$ROOT/weights/gpt-base-4096-clmbr

# Keep all Hugging Face cache and model bytes off disk1, which is full.
export HF_HOME=$ROOT/hf_cache
export CUDA_VISIBLE_DEVICES=""

"$PYTHON" "$PIPE/download_weights.py" \
  --model StanfordShahLab/gpt-base-4096-clmbr \
  --output-root "$WEIGHTS"
