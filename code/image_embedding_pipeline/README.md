# Image embeddings

## Bộ 1.000 case đang dùng cho retrieval v2

Manifest nguồn:
`/mnt/disk4/namtn/similar_case_retrieval/building_verify_app/code/sample_manifest.json`.

Các vector hiện có của bộ này được tạo bởi pipeline ngoài repository hiện
tại và đã audit như sau:

| Modality | Số vector | Dimension |
|---|---:|---:|
| CT | 3.322 | 512 |
| MRI | 3.904 | 768 |
| XQ | 1.293 | 512 |

Toàn bộ 8.519 vector là `float32`, một chiều, finite và non-zero. Script
`merge_image_cases_with_ehr.py` nối từng series vào visit bằng `patient_id` và
`study_date` nằm trong duy nhất một khoảng admission–discharge:

```bash
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
"$PYTHON" code/image_embedding_pipeline/merge_image_cases_with_ehr.py
```

Output hiện tại:
`/mnt/disk4/similar_cases_retrieval/data/retrieval_v2_image_1000/`.
`retrieval_v2_visits.parquet` có 1.005 visit thuộc 944 bệnh nhân; 8.315
embedding nối được và 204 embedding không nối được vẫn nằm trong bảng audit.

## Pipeline encoder trong repository

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

Không được giả định các vector của bộ 1.000 case phía trên do
`embed_image_feats.py` tạo ra. Model revision và preprocessing phải lấy từ
manifest của từng run; không trộn vector khác encoder trong cùng modality.

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

## Environment

Dùng environment hiện có
`/mnt/disk1/khangdp/conda_envs/scr_env`; không tạo environment khác. Các source
và checkpoint bên thứ ba phải được chuẩn bị riêng trên Vaipe. MedSigLIP và
CT-CLIP yêu cầu tài khoản Hugging Face đã được cấp quyền.

## Run

```bash
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
"$PYTHON" code/image_embedding_pipeline/embed_image_feats.py \
  --source-root /mnt/disk4/similar_cases_retrieval/data/images \
  --output-root /mnt/disk4/similar_cases_retrieval/data/experiments/image_emb_001 \
  --checkpoint-root /mnt/disk1/khangdp/ckpt/encoders \
  --hf-cache /mnt/disk1/khangdp/hf_cache \
  --mammo-source /mnt/disk1/khangdp/third_party/Mammo-FM/src/codebase \
  --device cuda --amp --disable-cudnn --ct-patch-batch-size 16
```

The separate RAD-DINO set uses, for example:

```bash
"$PYTHON" code/image_embedding_pipeline/embed_image_feats.py \
  --encoder-set rad_dino \
  --source-root /mnt/disk4/similar_cases_retrieval/data/images \
  --output-root /mnt/disk4/similar_cases_retrieval/data/experiments/image_emb_rad_dino_001 \
  --checkpoint-root /mnt/disk1/khangdp/ckpt/encoders \
  --hf-cache /mnt/disk1/khangdp/hf_cache \
  --device cuda --amp --disable-cudnn
```

The separate CT-CLIP set uses:

```bash
"$PYTHON" code/image_embedding_pipeline/embed_image_feats.py \
  --encoder-set ct_clip --modalities CT \
  --source-root /mnt/disk4/similar_cases_retrieval/data/images \
  --output-root /mnt/disk4/similar_cases_retrieval/data/experiments/image_emb_ct_clip_001 \
  --checkpoint-root /mnt/disk1/khangdp/ckpt/encoders \
  --ct-clip-repo /mnt/disk1/khangdp/third_party/CT-CLIP \
  --device cuda --amp --disable-cudnn
```

To leave the complete run on the server while the local machine is off, use
the background wrapper. It waits for MARS and at least 2.5 GiB free VRAM, then
runs the default set, RAD-DINO, and CT-CLIP in separate output roots:

```bash
SCR_SOURCE_ROOT=/mnt/disk4/similar_cases_retrieval/data/images \
SCR_OUTPUT_ROOT=/mnt/disk4/similar_cases_retrieval/data/experiments/image_emb_full_001 \
nohup bash code/image_embedding_pipeline/run_image_embeddings_background.sh \
  >/mnt/disk4/similar_cases_retrieval/data/experiments/image_emb_launcher.out 2>&1 </dev/null &
```
