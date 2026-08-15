# Image embeddings

`embed_image_feats.py` creates one raw `float32` tensor per source file and
mirrors the source relative path. For example, `MG/case/view.jpg` becomes
`MG/case/view.jpg.pt` below the selected output root. It writes a CSV manifest
and saves each tensor atomically, so a stopped run can be resumed.

The current mapping is:

| Modality | Encoder | Vector |
|---|---|---|
| CR/DX | MedSigLIP-448 | projected image features |
| MG | Mammo-FM Batmanlab checkpoint | projected image features |
| CT | CT-FM | mean of official 3D patch features |
| MR | MARS | mean of pooled MARS features over T volumes |
| CT (separate set) | CT-CLIP | raw projected image features |

Run the separate chest comparison set with `--encoder-set rad_dino`; it writes
to a different output root and never mixes vectors with MedSigLIP.
Run the separate CT-CLIP set with `--encoder-set ct_clip`; it writes to a
different output root and never mixes vectors with CT-FM.

The source data is never modified. The `normalized` manifest field is
`false`: vectors are saved raw, as requested. For CT, preprocessing follows
CT-FM's official feature-extractor transform (SPL orientation, spacing
`3,1,1`, foreground crop, HU scaling `[-1024,2048]` and `24x128x128` patches).
For MR, 3D volumes are canonicalized to RAS, nonzero z-normalized, padded and
center-cropped to `96^3`; a 4D file is encoded volume-by-volume and mean-pooled
to exactly one vector. CT-CLIP uses its released 3D target `(240,480,480)`,
the NIfTI header spacing to resample toward `(1.5,0.75,0.75)`, center crop/pad,
and HU scaling to `[-1,1]` before the CTViT image encoder.

On the shared GPU, the tested low-VRAM settings are `--disable-cudnn
--amp`, 2D encoder batch 1, CT-FM patch-batch 16, and CT-CLIP batch 1.
CT-FM patch-batch 32 OOMed with only about 3 GiB free VRAM. The pipeline saves
all output vectors as raw `float32`, even when model inference uses FP16.

## Server setup

On `vaipe_aiotlab`, run `setup_image_embedding_env.sh` once. It creates the
named `scr_env` environment under `/mnt/disk1`, checks out the official
Mammo-FM/MARS/CT-CLIP sources under `/mnt/disk1`, and downloads checkpoints to
`/mnt/disk1/khangdp/ckpt/encoders`. MedSigLIP and CT-CLIP require authenticated
Hugging Face access that has accepted their respective terms.

## Run

```bash
conda run -n scr_env python code/scr_pipeline/embed_image_feats.py \
  --source-root /mnt/disk4/trangtth/data_subset \
  --output-root /mnt/disk1/khangdp/similar_cases_retrieval/image_feats \
  --checkpoint-root /mnt/disk1/khangdp/ckpt/encoders \
  --hf-cache /mnt/disk1/khangdp/hf_cache \
  --mammo-source /mnt/disk1/khangdp/third_party/Mammo-FM/src/codebase \
  --device cuda --amp --disable-cudnn --ct-patch-batch-size 16
```

The separate RAD-DINO set uses, for example:

```bash
conda run -n scr_env python code/scr_pipeline/embed_image_feats.py \
  --encoder-set rad_dino \
  --source-root /mnt/disk4/trangtth/data_subset \
  --output-root /mnt/disk1/khangdp/similar_cases_retrieval/image_feats/rad_dino \
  --checkpoint-root /mnt/disk1/khangdp/ckpt/encoders \
  --hf-cache /mnt/disk1/khangdp/hf_cache \
  --device cuda --amp --disable-cudnn

The separate CT-CLIP set uses:

```bash
conda run -n scr_env python code/scr_pipeline/embed_image_feats.py \
  --encoder-set ct_clip --modalities CT \
  --source-root /mnt/disk4/trangtth/data_subset \
  --output-root /mnt/disk1/khangdp/similar_cases_retrieval/image_feats/ct_clip \
  --checkpoint-root /mnt/disk1/khangdp/ckpt/encoders \
  --ct-clip-repo /mnt/disk1/khangdp/third_party/CT-CLIP \
  --device cuda --amp --disable-cudnn
```
```

To leave the complete run on the server while the local machine is off, use
the background wrapper. It waits for MARS and at least 2.5 GiB free VRAM, then
runs the default set, RAD-DINO, and CT-CLIP in separate output roots:

```bash
nohup bash code/scr_pipeline/run_image_embeddings_background.sh \
  >/mnt/disk1/khangdp/image_embedding_launcher.out 2>&1 </dev/null &
```
