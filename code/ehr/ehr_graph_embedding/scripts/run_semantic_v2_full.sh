#!/usr/bin/env bash
# Sequential full semantic-v2 training: Stage 1 -> Stage 2 -> Stage 3.
set -euo pipefail

workspace=/mnt/disk4/similar_cases_retrieval/code/code/ehr/ehr_graph_embedding
data_root=/mnt/disk4/similar_cases_retrieval/data/ehr/preprocessed_v2
experiment_root=/mnt/disk4/similar_cases_retrieval/data/ehr/experiments
python=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python

stage1="$experiment_root/ehr_graph_semantic_v2_s1_e20_es5_20260816"
stage2="$experiment_root/ehr_graph_semantic_v2_s2_e20_es5_20260816"
stage3="$experiment_root/ehr_graph_semantic_v2_s3_e20_es5_20260816"
controller="$experiment_root/ehr_graph_semantic_v2_full_20260816"

mkdir -p "$controller"
exec > >(tee -a "$controller/controller.log") 2>&1

run_stage() {
  local output=$1
  shift
  if [[ -e "$output" ]]; then
    echo "Refusing to overwrite existing stage output: $output" >&2
    return 2
  fi
  mkdir -p "$output/logs"
  nvidia-smi > "$output/logs/nvidia_smi_before.txt" || true
  set +e
  PYTHONPATH="$workspace/src" CUDA_VISIBLE_DEVICES=0 "$python" -u -m ehr_graph_ssl.train \
    --data-root "$data_root" \
    --output "$output" \
    --epochs 20 \
    --early-stopping-patience 5 \
    --early-stopping-min-delta 1e-4 \
    --scheduler-patience 2 \
    --scheduler-factor 0.5 \
    --hidden-dim 256 \
    --output-dim 256 \
    --layers 4 \
    --heads 8 \
    --gradient-accumulation 8 \
    --ssl-max-graphs 1 \
    --ssl-max-nodes 800 \
    --device cuda \
    --amp \
    --export-embeddings \
    "$@" > "$output/logs/train.log" 2>&1
  local status=$?
  set -e
  printf '%s\n' "$status" > "$output/logs/exit_status.txt"
  nvidia-smi > "$output/logs/nvidia_smi_after.txt" || true
  if [[ "$status" -ne 0 ]]; then
    echo "Stage failed with status $status: $output" >&2
    return "$status"
  fi
}

echo "Starting semantic-v2 Stage 1"
run_stage "$stage1" --stage 1

echo "Starting semantic-v2 Stage 2"
run_stage "$stage2" --stage 2 --checkpoint "$stage1/best.pt"

echo "Starting semantic-v2 Stage 3"
run_stage "$stage3" --stage 3 --checkpoint "$stage2/best.pt"

echo "All semantic-v2 stages completed successfully"
