# Retrieval-first structured SSL implementation

**Updated:** 2026-08-15  
**Implementation:** code/retrieval_first_ssl_20260814/  
**Scope:** structured EHR only; no clinical-note, PDF, image, or label input.

## Data and safety contract

The loader column-projects only these input tables: visits, diagnoses,
medicines, procedures, and observations. It never reads clinical_notes,
visit_ehr, graph_nodes, or graph_edges.

Diagnosis nodes require a controlled diagnosis code. A diagnosis description is
not hashed or used as a fallback, because a hash would still turn free clinical
text into a model feature. Medicine, procedure, and observation tokens are
opaque categorical identifiers derived from their structured fields. No raw
text is written into embeddings, logs, checkpoints, or candidate output.

The representation is full_visit and therefore retrospective only. Splits are
deterministic visit-disjoint 70/15/15 with seed 20260812; this is explicitly
not a patient-disjoint result. Vocabulary, IDF, and numeric statistics are fit
from train visits only.

## Graph and staged objectives

Each visit is a sparse graph with VISIT, DIAGNOSIS, MEDICINE, PROCEDURE, and
OBSERVATION nodes. Edges are bidirectional visit-event relations, verified
procedure-observation order links, same-test temporal links, and same-medicine
temporal links. Medicine events are aggregated only within a relative 24-hour
bucket; repeated buckets of the same medicine remain distinct nodes.

1. Stage 1: per-type GT-BEHRT-style NAM plus Huber reconstruction of only
   intentionally masked Observation values.
2. Stage 2: Stage 1 plus MNP. MNP samples type uniformly, then samples by
   IDF within type, and does not remove the only core Diagnosis, Medicine, or
   Procedure node.
3. Stage 3: Stage 2 plus InfEHR-style similarity, variance, covariance, and
   local-global MI. VICReg operates directly on the unnormalized encoder
   readout; retrieval exports its L2-normalized form and never a projector.
   The MI negative corrupts categorical identities before the encoder only
   within same-type, exact 24-hour known-time groups; it preserves topology,
   numeric values, and timestamps. It is not a valid retrieval augmentation.

Stage 2 and Stage 3 require the immediately prior stage checkpoint and verify
model configuration, vocabulary, data fingerprint, IDF, numeric statistics,
and manifest before loading.

For groups smaller than a useful VICReg sample, Stage 3 optionally maintains a
bounded FP32 FIFO of **detached** raw encoder readouts, reset at every epoch.
Only variance/covariance sees current vectors plus this history; similarity and
MI remain current-group objectives. This is documented as a stale moment
estimator, not a claim of a fully differentiable larger batch, and no history
is persisted in checkpoints or exported artifacts.

## Selection and retrieval gate

Every epoch records validation reconstruction and cross-view Recall@1/5/10
against a shuffled visit null. The runner selects best.pt by validation
reconstruction and reloads that checkpoint before export. Each stage allows at
most 20 epochs; `ReduceLROnPlateau` halves the learning rate after two
validation plateaus (floor `1e-6`) and early stopping ends a run after five
consecutive validation epochs without a reconstruction-loss reduction of at
least `1e-4`. Checkpoints include optimizer/scheduler state and each run writes
the actual learning-rate history and stopping summary.

The quality report gates on validation embeddings only and writes all-split
statistics as descriptive diagnostics. It checks finite/unit vectors,
effective rank at least 25% of embedding dimension, top-1 hub fraction at most
5%, graph-size correlation below 0.20, and cross-view retrieval above
shuffled-null by more than 0.05. The note-length gate is recorded as not
applicable for this structured-only version. A pass is an engineering sanity
check, not clinical validation.

Only a passing quality report can enter the FAISS inner-product index builder.
The resulting candidate pool excludes self retrieval and carries only visit
IDs, rank, cosine score, version/snapshot, shared typed node counts, and graph
sizes. It never creates pseudo-labels or clinical-relevance conclusions.

## Provenance

GT-BEHRT and GCVR are reference-only because their public repositories do not
supply an upstream license. The implementation adapts the Apache-2.0 InfEHR
objective and the MIT AID-MAE numeric dual-mask idea. MUSE remains deferred
until a dedicated clinical-note encoder and modality contract are ready.
