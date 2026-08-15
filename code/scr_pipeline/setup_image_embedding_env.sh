#!/usr/bin/env bash
set -euo pipefail

# Run this script on vaipe_aiotlab.  It intentionally keeps the named conda
# environment and model cache on disk1; the MIMIC/subset source remains read-only.

ENV_ROOT="${SCR_CONDA_ENVS_ROOT:-/mnt/disk1/khangdp/conda_envs}"
HF_CACHE="${SCR_HF_CACHE:-/mnt/disk1/khangdp/hf_cache}"
CKPT_ROOT="${SCR_CHECKPOINT_ROOT:-/mnt/disk1/khangdp/ckpt/encoders}"
THIRD_PARTY="${SCR_THIRD_PARTY_ROOT:-/mnt/disk1/khangdp/third_party}"
REPO_ROOT="${SCR_REPO_ROOT:-/mnt/disk1/khangdp/similar_cases_retrieval}"

source /home/vaipe/miniconda3/etc/profile.d/conda.sh
mkdir -p "$ENV_ROOT" "$HF_CACHE" "$CKPT_ROOT" "$THIRD_PARTY"
export CONDA_ENVS_PATH="$ENV_ROOT"

if ! conda env list | awk '{print $1}' | grep -qx scr_env; then
  conda create -y --override-channels -c conda-forge -n scr_env python=3.11 pip
fi

conda run -n scr_env python -m pip install --upgrade pip
conda run -n scr_env python -m pip install \
  'torch==2.4.1' --index-url https://download.pytorch.org/whl/cu121
conda run -n scr_env python -m pip install \
  'torchvision==0.19.1' --index-url https://download.pytorch.org/whl/cu121
CONSTRAINTS_FILE="$(mktemp)"
trap 'rm -f "$CONSTRAINTS_FILE"' EXIT
printf '%s\n' 'torch==2.4.1' 'torchvision==0.19.1' > "$CONSTRAINTS_FILE"
conda run -n scr_env python -m pip install \
  'transformers>=4.46,<5' 'huggingface_hub[cli]>=0.26' safetensors \
  'monai>=1.4,<1.6' nibabel pillow numpy scipy pandas tqdm timm gdown pyyaml omegaconf \
  'sentencepiece>=0.2,<1' 'protobuf>=4.25,<7' 'einops>=0.8,<1' \
  'beartype>=0.16' 'ftfy>=6' 'vector-quantize-pytorch>=1.14' 'einx>=0.3' \
  frozendict 'torch-einops-utils' 'ema-pytorch' \
  --constraint "$CONSTRAINTS_FILE"

if conda run -n scr_env hf --help >/dev/null 2>&1; then
  HF_CLI="hf"
elif conda run -n scr_env huggingface-cli --help >/dev/null 2>&1; then
  HF_CLI="huggingface-cli"
else
  echo "Hugging Face CLI was not installed" >&2
  exit 1
fi

if [ ! -d "$THIRD_PARTY/Mammo-FM/.git" ]; then
  git clone https://github.com/batmanlab/Mammo-FM.git "$THIRD_PARTY/Mammo-FM"
else
  git -C "$THIRD_PARTY/Mammo-FM" fetch --depth=1 origin main
  git -C "$THIRD_PARTY/Mammo-FM" reset --hard origin/main
fi

if [ ! -d "$THIRD_PARTY/MARS/.git" ]; then
  git clone https://github.com/zqiuak/MARS.git "$THIRD_PARTY/MARS"
else
  git -C "$THIRD_PARTY/MARS" fetch --depth=1 origin main
  git -C "$THIRD_PARTY/MARS" reset --hard origin/main
fi

if [ ! -d "$THIRD_PARTY/CT-CLIP/.git" ]; then
  git clone https://github.com/ibrahimethemhamamci/CT-CLIP.git "$THIRD_PARTY/CT-CLIP"
else
  git -C "$THIRD_PARTY/CT-CLIP" fetch --depth=1 origin main
  git -C "$THIRD_PARTY/CT-CLIP" reset --hard origin/main
fi

# Public checkpoints.  The MedSigLIP repository is gated by Hugging Face; if
# the account has not accepted its terms, this one command fails with 401 and
# the remaining public checkpoints are still already available.
mkdir -p "$CKPT_ROOT/ct_fm_feature_extractor" "$CKPT_ROOT/rad_dino" "$CKPT_ROOT/medsiglip-448" "$CKPT_ROOT/Mammo-FM" "$CKPT_ROOT/MARS" "$CKPT_ROOT/ct_clip"
conda run -n scr_env "$HF_CLI" download project-lighter/ct_fm_feature_extractor \
  model.safetensors --local-dir "$CKPT_ROOT/ct_fm_feature_extractor"
conda run -n scr_env "$HF_CLI" download microsoft/rad-dino \
  --local-dir "$CKPT_ROOT/rad_dino"
conda run -n scr_env "$HF_CLI" download batmanLab/Mammo-FM \
  Mammo-FM_BatmanlabTrained_CLIP.tar --local-dir "$CKPT_ROOT/Mammo-FM"

if [ ! -s "$CKPT_ROOT/MARS/mars_pretrained.pt" ]; then
  conda run -n scr_env gdown 'https://drive.google.com/uc?id=1__lWJfBaCSQqkyPvxpQqK-MWH_d__bWz' \
    -O "$CKPT_ROOT/MARS/mars_pretrained.pt"
fi

# MedSigLIP is a gated Hugging Face model.  A missing account permission must
# not erase the usable public checkpoints above or prevent MARS from finishing.
if ! conda run -n scr_env "$HF_CLI" download google/medsiglip-448 \
  --local-dir "$CKPT_ROOT/medsiglip-448"; then
  echo "WARNING: MedSigLIP was not downloaded; accept its HF terms and set HF_TOKEN, then rerun this script." >&2
fi

# CT-CLIP is stored inside the gated CT-RATE dataset.  If the repository
# access has been accepted, source the project .env without printing the token
# and resume/download the official checkpoint.  Otherwise leave the other
# encoders usable and report the missing artifact.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
fi
if [ -n "${HF_TOKEN:-}" ]; then
  if ! conda run -n scr_env "$HF_CLI" download ibrahimhamamci/CT-RATE \
    models/CT-CLIP-Related/CT-CLIP_v2.pt --repo-type dataset \
    --local-dir "$CKPT_ROOT/ct_clip"; then
    echo "WARNING: CT-CLIP was not downloaded; accept CT-RATE access and rerun this script." >&2
  fi
else
  echo "WARNING: HF_TOKEN not found; skipping gated CT-CLIP download." >&2
fi

echo "scr_env ready"
echo "envs: $ENV_ROOT"
echo "checkpoints: $CKPT_ROOT"
echo "repo: $REPO_ROOT"
