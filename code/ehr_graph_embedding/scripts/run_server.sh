#!/usr/bin/env bash
# Run one EHR graph embedding stage on Vaipe.
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "Usage: $0 WORKSPACE DATA_ROOT OUTPUT_DIR --stage {1,2,3} [train options]" >&2
  exit 2
fi

workspace=$1
data_root=$2
output_dir=$3
shift 3
python=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python

case "$workspace" in
  /mnt/disk4/similar_cases_retrieval/code/code/ehr_graph_embedding) ;;
  *) echo "WORKSPACE must be the EHR graph embedding workspace" >&2; exit 2 ;;
esac
case "$data_root" in
  /mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/*) ;;
  *) echo "DATA_ROOT must be the approved read-only preprocessed EHR root" >&2; exit 2 ;;
esac
case "$output_dir" in
  /mnt/disk4/similar_cases_retrieval/data/experiments/*) ;;
  *) echo "OUTPUT_DIR must be under data/experiments" >&2; exit 2 ;;
esac

if [[ -e "$output_dir" ]]; then
  echo "Refusing to overwrite existing output directory: $output_dir" >&2
  exit 2
fi
mkdir -p "$output_dir/logs"
nvidia-smi > "$output_dir/logs/nvidia_smi_before.txt" || true
set +e
PYTHONPATH="$workspace/src" "$python" -m ehr_graph_ssl.train \
  --data-root "$data_root" --output "$output_dir" "$@" \
  > "$output_dir/logs/train.log" 2>&1
status=$?
set -e
nvidia-smi > "$output_dir/logs/nvidia_smi_after.txt" || true
printf '%s\n' "$status" > "$output_dir/logs/exit_status.txt"
exit "$status"
