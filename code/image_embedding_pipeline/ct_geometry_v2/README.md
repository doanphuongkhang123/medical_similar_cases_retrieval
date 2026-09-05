# CT DICOM geometry and full CT-CLIP embedding v2

This replacement run covers the 7,241 CT entries in the current patient-fusion
input manifest. The old manifest supplies cohort identity and pointers only:
pixels and geometry come directly from each original DICOM ZIP. Existing
embeddings and raw.npy files are never used as model inputs or overwritten.

The reader sorts by physical position along the slice normal, validates all
slice orientations/spacing/positions, applies slope/intercept per slice and
constructs a full RAS affine. Constant gantry tilt is preserved. It rejects RGB
renderings, localizers, missing geometry, nonuniform stacks, duplicate slice
positions and unsupported enhanced/multiframe CT with explicit reasons.
Rejection is audited; it is not silently repaired or filled with a vector.

The volume is sampled directly onto a centered RAS grid, XYZ spacing
0.75/0.75/1.5 mm and XYZ shape 480/480/240. Model layout is ZXY. HU is clamped
to [-1000,1000] before linear interpolation, divided by 1000, with air padding.
The physical sampling grid differs intentionally from legacy index-only resize.
Padding and physical coverage are recorded; no anatomy/padding threshold is
invented to discard grayscale CT. Full CT-CLIP remains a transfer model for
non-chest regions, so engineering verification is not clinical validation.

The existing CT-CLIP_v2.pt checkpoint loads all visual weights and the trained
294912-to-512 projection. Only the new VQ library's training-only embed_avg
buffer may be absent. Frozen inference calls the VQ module in bounded chunks,
means depth tokens, retains and flattens the 24x24 spatial grid and applies the
learned projection. Smoke compares chunked VQ against unchunked reference on
512 actual tokens. Stored embeddings are raw, unnormalized float32 512-D.

Every source entry has an atomic record with original ZIP SHA-256, member
hash, pixel/HU geometry hashes, tensor hash and checkpoint/code provenance.
Identical model tensors may share a physical embedding file; output records
retain every source entry. The final deduplicated fusion-candidate table keeps
one HU/geometry identity per patient/visit and excludes ambiguous visit joins.
It is not installed into the live fusion inputs automatically.

Run tests on Vaipe with GPUs hidden:

```bash
CUDA_VISIBLE_DEVICES='' /mnt/disk1/khangdp/conda_envs/scr_env/bin/python -m unittest discover -s tests -v
```

After inspecting nvidia-smi, run a production-shape CUDA smoke into a new root:

```bash
CUDA_VISIBLE_DEVICES=0 /mnt/disk1/khangdp/conda_envs/scr_env/bin/python -u run.py \
  --smoke --smoke-items 6 --output-root /mnt/disk4/similar_cases_retrieval/data/experiments/ct_geometry_v2_smoke_NEW
```

Then nohup launch.sh with a fresh full-output root and that verified smoke root.
The launcher has no utilization/free-VRAM gate, owns a flock, saves PID,
timestamped log, exact command, final verification and nonzero failure status.
Actual CUDA OOM exits immediately without automatic relaunch. Other per-series
exceptions are preserved; the run finishes nonzero if any failed records remain.
Resume requires identical source inventory/code/checkpoint configuration and
rechecks ZIP/output hashes; failed items are not automatically retried.

Outputs: source_inventory.parquet, config.json, model_manifest.json, per-item
records/, embeddings/, ct_embedding_manifest.parquet,
ct_embedding_manifest_deduplicated.parquet, verification.json, progress.json.
The CPU finalizer also writes quality_comparison.json against the old vectors
on the same successful source rows, raw_archive_manifest.json and run_manifest.json.
