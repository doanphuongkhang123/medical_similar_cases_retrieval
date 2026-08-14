# Supervised clinical-retrieval pipeline

## Purpose and scope

This pipeline improves visit retrieval with **externally reviewed pairwise
clinical-relevance labels**.  It does not define relevance from `MaICD`,
outcome, medication, or any other EHR field.  Those fields may be shown to
reviewers only if the approved rubric and observation snapshot permit them.

The existing GT-BEHRT-Visit encoder first produces a self-supervised 256-D
vector.  `supervised_retrieval.py` learns a lightweight 128-D projection from
reviewed pairs; this is intentionally separate from the graph encoder so the
supervision step is auditable and reversible.

```text
visit embeddings (self-supervised)
  -> candidate generation (top-k + random controls; no labels)
  -> blinded clinical review and adjudication
  -> reviewed pair labels
  -> train-only pairwise projection
  -> projected, normalized embeddings
  -> ranking evaluation on held-out reviewed pairs
```

## Required decisions before using real data

1. Observation policy: `admission`, `first_24h`, or `full_visit`.
2. Retrieval unit and clinical question represented by “similar”.
3. A relevance rubric, reviewer roles, adjudication procedure, and handling of
   uncertainty/disagreement.
4. An approved pseudonymized patient ID and patient-disjoint split.  The
   current `visit_id` contract cannot prove this condition.

## Reviewed-pair contract

The reviewed Parquet must contain exactly one judgement per `(query_visit_id,
candidate_visit_id)` and at least these columns:

| Column | Meaning |
|---|---|
| `query_visit_id` | query visit identifier |
| `candidate_visit_id` | candidate visit identifier; never equal to query |
| `relevance` | approved non-negative ordinal score, for example `0`, `1`, `2` |
| `partition` | `train`, `validation`, or `test` |

Training pairs must have both visits in the embedding `train` split.  Held-out
test queries should be in the test split and candidates in the approved
reference/train cohort.  The evaluator reports metrics only on the explicitly
judged candidate set; it never treats an unreviewed pair as irrelevant.

## Server run

All output paths below must be inside one server experiment directory.  The
raw workbook remains read-only.

```bash
cd /mnt/disk4/similar_cases_retrieval/code
# The non-interactive vaipe shell currently does not expose `conda`; use the
# verified executable of the approved scr_env, never another environment.
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
"$PYTHON" --version

RUN_DIR=/mnt/disk4/similar_cases_retrieval/data/experiments/retrieval_001
BASE="$RUN_DIR/embeddings/visit_embeddings.parquet"

# Generates candidates only; expert review supplies relevance and partition.
"$PYTHON" code/ehr_graph_pipeline/supervised_retrieval.py candidates \
  --embeddings "$BASE" \
  --output "$RUN_DIR/review/candidates_validation.parquet" \
  --query-split validation --reference-split train --top-k 20 --random-k 10

# After review and adjudication; fit sees only partition=train labels.
"$PYTHON" code/ehr_graph_pipeline/supervised_retrieval.py fit \
  --embeddings "$BASE" --pairs "$RUN_DIR/review/reviewed_pairs.parquet" \
  --output "$RUN_DIR/model/retrieval_projection.pt"
"$PYTHON" code/ehr_graph_pipeline/supervised_retrieval.py project \
  --embeddings "$BASE" --checkpoint "$RUN_DIR/model/retrieval_projection.pt" \
  --output "$RUN_DIR/embeddings/supervised_visit_embeddings.parquet"
"$PYTHON" code/ehr_graph_pipeline/supervised_retrieval.py evaluate \
  --embeddings "$RUN_DIR/embeddings/supervised_visit_embeddings.parquet" \
  --pairs "$RUN_DIR/review/reviewed_pairs.parquet" \
  --partition test --output "$RUN_DIR/evaluation/retrieval_metrics.json"
```

The test report contains `Precision@k`, `mAP@k`, and `nDCG@k`, with the
explicit scope `judged_candidate_set_only`.  It is not valid to claim
whole-corpus retrieval performance unless the judging design covers the
candidate corpus or uses an approved pooling protocol.
