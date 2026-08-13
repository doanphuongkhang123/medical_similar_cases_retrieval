#!/usr/bin/env bash
# Run only on vaipe_aiotlab. One run owns one self-contained output directory.
set -euo pipefail

if [[ $# -eq 1 ]]; then
  run_dir="$1"
  workbook="/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx"
elif [[ $# -eq 2 ]]; then
  run_dir="$1"
  workbook="$2"
else
  echo "Usage: $0 RUN_DIRECTORY [WORKBOOK]" >&2
  exit 2
fi
case "$run_dir" in
  /mnt/disk4/similar_cases_retrieval/data/experiments/*) ;;
  *) echo "RUN_DIRECTORY must be below data/experiments/" >&2; exit 2 ;;
esac
if [[ -e "$run_dir/preprocessed" || -e "$run_dir/graphs" ]]; then
  echo "Refusing to overwrite an existing preprocessing or graph stage: $run_dir" >&2
  exit 2
fi
mkdir -p "$run_dir/logs"
exec > "$run_dir/logs/preprocess_and_graphs.log" 2>&1
conda_base="$(/home/vaipe/miniconda3/bin/conda info --base)"
source "$conda_base/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env

python code/ehr_graph_pipeline/preprocess_ehr.py \
  --workbook "$workbook" \
  --output "$run_dir/preprocessed" \
  --snapshot-mode full_visit
python code/ehr_graph_pipeline/build_visit_graphs.py \
  --input "$run_dir/preprocessed" \
  --output "$run_dir/graphs"
