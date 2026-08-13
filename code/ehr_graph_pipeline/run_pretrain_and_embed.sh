#!/usr/bin/env bash
# Run only on vaipe_aiotlab in a detached tmux session.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 RUN_DIRECTORY" >&2
  exit 2
fi
run_dir="$1"
case "$run_dir" in
  /mnt/disk4/similar_cases_retrieval/data/experiments/*) ;;
  *) echo "RUN_DIRECTORY must be below data/experiments/" >&2; exit 2 ;;
esac
if [[ -e "$run_dir/model" || -e "$run_dir/embeddings" ]]; then
  echo "Refusing to overwrite an existing model or embedding stage: $run_dir" >&2
  exit 2
fi
cd /mnt/disk4/similar_cases_retrieval/code
mkdir -p "$run_dir/logs"
exec > "$run_dir/logs/pretrain_and_embed.log" 2>&1
conda_base="$(/home/vaipe/miniconda3/bin/conda info --base)"
source "$conda_base/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env

python code/ehr_graph_pipeline/pretrain_graph_encoder.py \
  --graphs "$run_dir/graphs" \
  --canonical "$run_dir/preprocessed" \
  --output "$run_dir/model/gt_behrt_visit.pt" \
  --epochs 5
python code/ehr_graph_pipeline/embed_visits.py \
  --graphs "$run_dir/graphs" \
  --canonical "$run_dir/preprocessed" \
  --output "$run_dir/embeddings" \
  --checkpoint "$run_dir/model/gt_behrt_visit.pt"
