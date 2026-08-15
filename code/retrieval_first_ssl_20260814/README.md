# Retrieval-first structured EHR SSL

This is an isolated server workspace for the first structured-EHR-only version
of the retrieval-first design. It implements the following staged objectives:

1. GT-BEHRT-style typed node attribute masking (NAM) plus AID-MAE-style
   observed-value masking for numeric features.
2. GT-BEHRT-style missing node prediction (MNP).
3. InfEHR-style consistency, variance, covariance, and local-to-global mutual
   information for two valid feature-masked views of the same visit.

The loader reads only `visits`, `diagnoses`, `medicines`, `procedures`, and
`observations`. It never reads `clinical_notes`, `visit_ehr`, `graph_nodes`, or
`graph_edges`. Diagnosis descriptions have no fallback path: only controlled
diagnosis codes can become Diagnosis nodes. This keeps raw/free clinical text
out of the EHR-only encoder until the later text-encoder stage.

The v1 safety contract is:

- train-only vocabulary, IDF, and numeric statistics;
- visit-disjoint split only (not a patient-disjoint claim);
- concept masking separately by node type; an augmented view keeps at least one
  Diagnosis, Medicine, and Procedure concept whenever that type is present;
- numeric dual-mask loss only for observed Observation values;
- repeated medicines are grouped only within a 24-hour relative-time bucket;
  repeated buckets of the same medicine are connected in chronological order;
- MNP samples node type uniformly then uses IDF within that type, and never
  removes the sole core node;
- Stage 3 MI uses a same-type, exact-24-hour categorical corruption *before*
  the graph encoder. It preserves topology, numeric values, and timestamps;
  nodes without a timestamp are not corrupted. It is a negative, not a valid
  retrieval view.
- All stages export the L2-normalized encoder readout. Stage 3 applies VICReg
  directly to its unnormalized form; the compatibility-only projector is not
  used for training or retrieval.

The dataset remains `full_visit` and is therefore **retrospective only**. The
split is deterministic by `visit_id` (70/15/15); it is not a patient-disjoint
claim.

## Run on Vaipe

Use the verified interpreter directly because non-interactive SSH does not
currently expose `conda`:

```bash
WORKSPACE=/mnt/disk4/similar_cases_retrieval/code/retrieval_first_ssl_20260814
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
DATA=/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/ehr_preprocessed_full
RUN=/mnt/disk4/similar_cases_retrieval/data/experiments/retrieval_first_structured_stage1

PYTHONPATH="$WORKSPACE/src" "$PYTHON" -m rfssl.train \
  --data-root "$DATA" --output "$RUN" --stage 1 --epochs 20 \
  --early-stopping-patience 5 --scheduler-patience 2 --scheduler-factor 0.5 \
  --hidden-dim 256 --output-dim 256 --layers 4 --heads 8 --amp
```

Use a fresh run directory every time; the runner refuses to overwrite output.
Stage 2 requires a stage-1 checkpoint, and stage 3 requires a stage-2
checkpoint from the identical data fingerprint. The runner validates the
predecessor stage, vocabulary, IDF, numeric statistics, and manifest before
loading it.

Each epoch records validation masked reconstruction and cross-view retrieval
against a shuffled-null mapping, plus process-local CUDA peak memory. Export
reloads the validation-selected `best.pt`, rather than the final in-memory
epoch. The quality report applies its engineering gates on validation only and
stores all-split values as descriptive diagnostics: finite/unit vectors,
effective rank, top-1 hub concentration, graph-size correlation, and
cross-view performance over the shuffled null. A passing report is only an
engineering sanity check; it is not clinical retrieval validation.

The default maximum is 20 epochs for every stage. `ReduceLROnPlateau` monitors
validation reconstruction loss, halves the learning rate after two plateaus,
and never drops below `1e-6`. Training stops after five consecutive validation
epochs without a decrease of at least `1e-4`; the run records the chosen
checkpoint, learning rates, and stopping reason.

Candidate/index generation remains blocked until a checkpoint passes those
gates.

When a bounded graph group is too small for a stable variance/covariance
estimate, stage 3 can use a short, reset-per-epoch **detached** FP32 history
for those two VICReg terms only. It does not turn historical vectors into a
fully differentiable batch, and it never changes similarity or MI pairs. For
the 8-graph VRAM configuration, use at most 32 statistic vectors per view:

```bash
--vicreg-history-size 24 --vicreg-max-stat-vectors 32
```

The run manifest and epoch metrics record this setting and the effective
statistic-vector count.

## Candidate pool after a passing quality report

The builder makes a cosine/IP FAISS index and a top-k, self-excluded
`pre_review_candidates.parquet`. It refuses an embedding report that fails the
engineering gates and never assigns clinical relevance.

```bash
PYTHONPATH="$WORKSPACE/src" "$PYTHON" -m rfssl.build_candidate_pool \
  --embeddings "$RUN/visit_embeddings.parquet" \
  --quality-report "$RUN/embedding_quality_report.json" \
  --output-dir "$RUN/candidate_index" --top-k 20
```

FAISS is intentionally not installed automatically in `scr_env`. The
`--allow-exact-numpy` fallback is only for small fixture tests, not the
production index path.

See [THIRD_PARTY.md](THIRD_PARTY.md) for source commits and licenses.
