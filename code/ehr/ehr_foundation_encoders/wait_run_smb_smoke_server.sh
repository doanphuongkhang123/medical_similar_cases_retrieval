#!/usr/bin/env bash
set -euo pipefail

PIPE=/mnt/disk4/similar_cases_retrieval/code/code/ehr/ehr_foundation_encoders
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
DATA_ROOT=/mnt/disk4/similar_cases_retrieval/data/ehr/ehr_foundation_encoders
PIPELINE_ROOT="$DATA_ROOT/raw_pipeline_v1"
SMB_UTILS="$DATA_ROOT/runtime/smb-utils"
CHECKPOINT="$DATA_ROOT/models/SMB-v1_Qwen3-1.7b_multi-objective/checkpoint"
EXPERIMENT_ROOT="$DATA_ROOT/experiments/smb_v1_qwen3_1_7b"
OUTPUT="$EXPERIMENT_ROOT/smoke_inference"
LOG_ROOT="$EXPERIMENT_ROOT/logs"
MIN_FREE_MIB="${SMB_SMOKE_MIN_FREE_MIB:-18000}"
POLL_SECONDS="${SMB_SMOKE_POLL_SECONDS:-60}"

mkdir -p "$LOG_ROOT"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
log="$LOG_ROOT/smoke_waiter_${timestamp}.log"
pid_file="$LOG_ROOT/smoke_waiter.pid"
lock_file="$LOG_ROOT/smoke_waiter.lock"

exec 9>"$lock_file"
if ! flock -n 9; then
  echo "Another SMB smoke waiter holds $lock_file" >&2
  exit 1
fi
echo "$$" > "$pid_file"
trap 'rm -f "$pid_file"' EXIT
exec > >(tee -a "$log") 2>&1

echo "[$(date -u +%FT%TZ)] waiter_pid=$$"
echo "[$(date -u +%FT%TZ)] minimum_free_memory_mib=$MIN_FREE_MIB poll_seconds=$POLL_SECONDS"
echo "[$(date -u +%FT%TZ)] output=$OUTPUT"

if [[ -s "$OUTPUT/smoke_manifest.json" ]]; then
  echo "[$(date -u +%FT%TZ)] smoke output already exists; nothing to run"
  exit 0
fi
if [[ -e "$OUTPUT" ]]; then
  echo "[$(date -u +%FT%TZ)] refusing existing incomplete output: $OUTPUT" >&2
  exit 1
fi
for required in \
  "$PIPE/smoke_smb_inference.py" \
  "$PIPELINE_ROOT/common/manifest.json" \
  "$PIPELINE_ROOT/adapters/smb_v1_1_7b/window_selection/manifest.json" \
  "$CHECKPOINT/checkpoint_manifest.json"; do
  if [[ ! -f "$required" ]]; then
    echo "[$(date -u +%FT%TZ)] required input is missing: $required" >&2
    exit 1
  fi
done
if [[ ! -d "$SMB_UTILS/src/smb_utils" ]]; then
  echo "[$(date -u +%FT%TZ)] pinned smb-utils runtime is missing" >&2
  exit 1
fi

chosen_gpu=""
while [[ -z "$chosen_gpu" ]]; do
  gpu_snapshot="$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits)"
  while IFS=',' read -r index free_mib; do
    index="${index//[[:space:]]/}"
    free_mib="${free_mib//[[:space:]]/}"
    if [[ "$free_mib" =~ ^[0-9]+$ ]] && (( free_mib >= MIN_FREE_MIB )); then
      chosen_gpu="$index"
      break
    fi
  done <<< "$gpu_snapshot"
  if [[ -z "$chosen_gpu" ]]; then
    echo "[$(date -u +%FT%TZ)] waiting; gpu_free_mib=${gpu_snapshot//$'\n'/;}"
    sleep "$POLL_SECONDS"
  fi
done

export CUDA_VISIBLE_DEVICES="$chosen_gpu"
export HF_HOME="$DATA_ROOT/hf_cache"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$SMB_UTILS/src"
command=(
  "$PYTHON" "$PIPE/smoke_smb_inference.py"
  --common-root "$PIPELINE_ROOT/common"
  --window-root "$PIPELINE_ROOT/adapters/smb_v1_1_7b/window_selection"
  --checkpoint-root "$CHECKPOINT"
  --output-root "$OUTPUT"
)
echo "[$(date -u +%FT%TZ)] selected_physical_gpu=$chosen_gpu"
printf '[%s] command=' "$(date -u +%FT%TZ)"
printf ' %q' "${command[@]}"
printf '\n'

if "${command[@]}"; then
  echo "[$(date -u +%FT%TZ)] smoke inference completed"
else
  rc=$?
  echo "[$(date -u +%FT%TZ)] smoke inference failed rc=$rc" >&2
  exit "$rc"
fi
