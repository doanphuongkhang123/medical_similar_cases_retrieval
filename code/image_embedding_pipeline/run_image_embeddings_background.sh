#!/usr/bin/env bash
set -u

REPO_ROOT="${SCR_REPO_ROOT:-/mnt/disk4/similar_cases_retrieval/code}"
SOURCE_ROOT="${SCR_SOURCE_ROOT:?Set SCR_SOURCE_ROOT below /mnt/disk4/similar_cases_retrieval/data/}"
OUTPUT_ROOT="${SCR_OUTPUT_ROOT:?Set SCR_OUTPUT_ROOT below /mnt/disk4/similar_cases_retrieval/data/experiments/}"
CHECKPOINT_ROOT="${SCR_CHECKPOINT_ROOT:-/mnt/disk1/khangdp/ckpt/encoders}"
HF_CACHE="${SCR_HF_CACHE:-/mnt/disk1/khangdp/hf_cache}"
MAMMO_SOURCE="${SCR_MAMMO_SOURCE:-/mnt/disk1/khangdp/third_party/Mammo-FM/src/codebase}"
CT_CLIP_REPO="${SCR_CT_CLIP_REPO:-/mnt/disk1/khangdp/third_party/CT-CLIP}"
LOG_FILE="${SCR_EMBED_LOG:-$OUTPUT_ROOT/image_embedding_full.log}"
MIN_FREE_VRAM_MIB="${SCR_MIN_FREE_VRAM_MIB:-2500}"

case "$SOURCE_ROOT" in
  /mnt/disk4/similar_cases_retrieval/data/*) ;;
  *) echo "SCR_SOURCE_ROOT must be inside the approved dataset root" >&2; exit 2 ;;
esac
case "$OUTPUT_ROOT" in
  /mnt/disk4/similar_cases_retrieval/data/experiments/*) ;;
  *) echo "SCR_OUTPUT_ROOT must be inside data/experiments" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$LOG_FILE")" "$OUTPUT_ROOT"
exec >>"$LOG_FILE" 2>&1

echo "[$(date -Is)] background embedding job started"
echo "[$(date -Is)] repo=$REPO_ROOT source=$SOURCE_ROOT output=$OUTPUT_ROOT"

PYTHON="${SCR_PYTHON:-/mnt/disk1/khangdp/conda_envs/scr_env/bin/python}"
echo "[$(date -Is)] python=$PYTHON version=$($PYTHON --version 2>&1)"

MARS_CHECKPOINT="$CHECKPOINT_ROOT/MARS/mars_pretrained.pt"
DEADLINE=$(( $(date +%s) + 604800 ))
while [ ! -s "$MARS_CHECKPOINT" ]; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "[$(date -Is)] ERROR: MARS checkpoint was not ready within 7 days"
    exit 1
  fi
  echo "[$(date -Is)] waiting for MARS checkpoint"
  sleep 120
done

while true; do
  FREE_VRAM="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | awk 'NR==1{print $1}')"
  if [ -n "$FREE_VRAM" ] && [ "$FREE_VRAM" -ge "$MIN_FREE_VRAM_MIB" ]; then
    break
  fi
  echo "[$(date -Is)] waiting for GPU free VRAM >= ${MIN_FREE_VRAM_MIB} MiB (current=${FREE_VRAM:-unknown})"
  sleep 120
done

cd "$REPO_ROOT"

# MedSigLIP is gated. Include CR/DX in the default run only if its local
# checkpoint is available; RAD-DINO is always run separately below.
DEFAULT_MODALITIES="MG CT MR"
if [ -s "$CHECKPOINT_ROOT/medsiglip-448/model.safetensors" ]; then
  DEFAULT_MODALITIES="CR DX MG CT MR"
fi

echo "[$(date -Is)] starting default encoder set: $DEFAULT_MODALITIES"
"$PYTHON" code/image_embedding_pipeline/embed_image_feats.py \
  --modalities $DEFAULT_MODALITIES \
  --source-root "$SOURCE_ROOT" \
  --output-root "$OUTPUT_ROOT" \
  --checkpoint-root "$CHECKPOINT_ROOT" \
  --hf-cache "$HF_CACHE" \
  --mammo-source "$MAMMO_SOURCE" \
  --device cuda \
  --amp \
  --disable-cudnn \
  --ct-patch-batch-size 16

echo "[$(date -Is)] starting separate RAD-DINO CR/DX set"
"$PYTHON" code/image_embedding_pipeline/embed_image_feats.py \
  --encoder-set rad_dino \
  --source-root "$SOURCE_ROOT" \
  --output-root "$OUTPUT_ROOT/rad_dino" \
  --checkpoint-root "$CHECKPOINT_ROOT" \
  --hf-cache "$HF_CACHE" \
  --device cuda \
  --amp \
  --disable-cudnn

echo "[$(date -Is)] starting separate CT-CLIP CT set"
"$PYTHON" code/image_embedding_pipeline/embed_image_feats.py \
  --encoder-set ct_clip \
  --modalities CT \
  --source-root "$SOURCE_ROOT" \
  --output-root "$OUTPUT_ROOT/ct_clip" \
  --checkpoint-root "$CHECKPOINT_ROOT" \
  --hf-cache "$HF_CACHE" \
  --ct-clip-repo "$CT_CLIP_REPO" \
  --device cuda \
  --amp \
  --disable-cudnn

echo "[$(date -Is)] background embedding job finished"
