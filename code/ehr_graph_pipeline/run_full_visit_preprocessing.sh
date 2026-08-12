#!/usr/bin/env bash
# Run only on vaipe_aiotlab. Outputs remain under the protected server data root.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  workbook="/mnt/disk4/similar_cases_retrieval/data/thông tin bệnh án.xlsx"
  data_root="/mnt/disk4/similar_cases_retrieval/data"
elif [[ $# -eq 2 ]]; then
  workbook="$1"
  data_root="$2"
else
  echo "Usage: $0 [WORKBOOK OUTPUT_DATA_ROOT]" >&2
  exit 2
fi
mkdir -p logs
exec > logs/gt_behrt_visit_20260812.log 2>&1
conda_base="$(/home/vaipe/miniconda3/bin/conda info --base)"
source "$conda_base/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env

python code/ehr_graph_pipeline/preprocess_ehr.py \
  --workbook "$workbook" \
  --output "$data_root/ehr_graph_preprocessed" \
  --snapshot-mode full_visit
python code/ehr_graph_pipeline/build_visit_graphs.py \
  --input "$data_root/ehr_graph_preprocessed" \
  --output "$data_root/ehr_graph_dataset"
