#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${1:?usage: launch.sh OUTPUT_ROOT SMOKE_ROOT}"
SMOKE="${2:?smoke output root required}"
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
case "$OUTPUT" in /mnt/disk4/similar_cases_retrieval/data/experiments/ct_geometry_v2_*) ;; *) echo 'Unexpected output root'; exit 2;; esac
mkdir -p "$OUTPUT"
exec 9>"$OUTPUT/launcher.lock"
flock -n 9 || { echo 'Another launcher owns this run'; exit 3; }
LOG="$OUTPUT/run_$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
printf '%s\n' "$$" >"$OUTPUT/launcher.pid"
printf '%s\n' "$LOG" >"$OUTPUT/log_path.txt"
finish() {
  local rc=$?
  trap - EXIT
  printf '%s\n' "$rc" >"$OUTPUT/exit_code.txt"
  date -u +%FT%TZ >"$OUTPUT/finished_at.txt"
  echo "FINISHED rc=$rc $(date -u +%FT%TZ)"
  exit "$rc"
}
trap finish EXIT
date -u +%FT%TZ >"$OUTPUT/started_at.txt"
echo "START pid=$$ host=$(hostname)"
CUDA_VISIBLE_DEVICES='' "$PYTHON" - "$SMOKE" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]);r=json.loads((p/'verification.json').read_text())
assert r['verification_passed'] and r['success_rows'] >= 3, r
config=json.loads((p/'config.json').read_text())
for name in ['geometry.py','encoder.py','run.py']:
    code=Path('/mnt/disk4/similar_cases_retrieval/code/code/image_embedding_pipeline/ct_geometry_v2')/name
    assert hashlib.sha256(code.read_bytes()).hexdigest()==config['script_sha256'][name], name
for f in (p/'records').glob('*.json'):
    row=json.loads(f.read_text())
    if row['status']=='success' and not row.get('reuse_from_item'):
        assert row['vq_chunk_reference_max_error'] <= 1e-6
print('Representative production-shape CUDA smoke verified')
PY
nvidia-smi --query-gpu=index,name,memory.total,memory.free,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
export CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export HF_HOME=/mnt/disk4/similar_cases_retrieval/data/model_cache
COMMAND=("$PYTHON" -u "$ROOT/run.py" --output-root "$OUTPUT")
printf '%q ' "${COMMAND[@]}" >"$OUTPUT/command.sh"
printf '\n' >>"$OUTPUT/command.sh"
"${COMMAND[@]}"
CUDA_VISIBLE_DEVICES='' "$PYTHON" "$ROOT/audit_run.py" "$OUTPUT"
