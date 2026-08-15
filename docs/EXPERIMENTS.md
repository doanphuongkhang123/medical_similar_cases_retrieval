# Experiments

## 2026-08-12 — GT-BEHRT-Visit structured full-visit baseline

- **Host/environment:** `vaipe_aiotlab`, `/mnt/disk1/khangdp/conda_envs/scr_env`, Python 3.11.15.
- **Source dataset:** `/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx` (server-only; no raw data copied to local or Git).
- **Observation policy:** `full_visit`, retrospective only.
- **Graph unit:** `SoBenhAn`; 3,500 visits.
- **Canonical result:** 760,276 event nodes, 542,760 business relations, 0 unmatched lab-order links.
- **Graph result:** 3,500 sparse independent graphs.
- **Split:** deterministic visit-disjoint 70/15/15, seed `20260812`; not patient-disjoint because no approved pseudonymized patient ID is available.
- **Model:** 2-layer relation-aware GT-BEHRT-Visit, hidden/output dimension 256, 4 heads, dropout 0.2.
- **Pretraining:** masked node-concept prediction, mask rate 15%, 5 epochs, 2,464 train graphs. Loss by epoch: 2.8682, 2.2787, 2.1282, 2.0438, 1.9894.
- **Run directory (server only):**
  `/mnt/disk4/similar_cases_retrieval/data/experiments/gt_behrt_visit_20260812/`
  - `preprocessed/`: canonical tables, split and feature artifacts
  - `graphs/`: independent visit graphs and index
  - `model/gt_behrt_visit.pt`: masked-node pretrained checkpoint
  - `embeddings/visit_embeddings.parquet`: visit vectors
  - `logs/`: commands' stdout/stderr

This produces model-trained vectors only. It does not validate clinical
similarity or retrieval quality: relevance labels and patient-disjoint split
are still required before reporting retrieval metrics.

## 2026-08-15 — Retrieval-first structured EHR SSL, Stage 3 encoder contract

- **Host/environment:** `vaipe_aiotlab`, direct interpreter
  `/mnt/disk1/khangdp/conda_envs/scr_env/bin/python` (Python 3.11.15,
  PyTorch 2.4.1+cu121); no package was installed.
- **Input scope:** only the five structured Parquet tables below
  `/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/ehr_preprocessed_full/`.
  Clinical-note, `visit_ehr`, graph text fields, diagnosis descriptions, PDF,
  and images were not read.
- **Split/snapshot:** deterministic visit-disjoint 70/15/15, seed `20260812`,
  `full_visit`; not patient-disjoint and retrospective only.
- **Predecessor:** strict Stage-2 checkpoint from
  `retrieval_first_ssl_structured_strict_s2_e2_20260815/best.pt`, validated
  against the full data fingerprint, vocabulary, IDF, numeric statistics, and
  manifest.
- **Contract correction verified:** Stage 3 applies VICReg to the unnormalized
  encoder readout and exports its L2-normalized form. MI corruption is
  pre-encoder and limited to same-type, exact known 24-hour buckets. Quality
  gates are calculated on validation only; all-split values are descriptive.
- **Fixture verification before run:** 8/8 unit tests passed on Vaipe,
  including code-only diagnosis, exact-time MI corruption, encoder-only
  export, validation-only gates, candidate self-exclusion, and finite SSL
  objective tests.

### One-epoch B=8 run (completed)

- **Run directory (server-only):**
  `/mnt/disk4/similar_cases_retrieval/data/experiments/retrieval_first_ssl_structured_strict_s3_encoder_b8_e1_20260815/`
- **Configuration:** Stage 3, 4 relation-attention layers, 8 heads, 256-D
  hidden/output, AMP, `ssl_max_graphs=8`, `ssl_max_nodes=1200`, one epoch.
- **Exit:** `0`; the training process recorded a peak of 759 MiB allocated
  and 1,066 MiB reserved. This fits the approximately 6 GiB free-VRAM budget
  without interrupting other users' processes.
- **Validation proxy:** reconstruction loss 4.8869; cross-view Recall@1/5/10
  = 0.5811/0.8057/0.9038 versus shuffled-null Recall@1 = 0.0019.
- **Validation engineering gates:** finite/unit norm and top-1 hub fraction
  (1.32%) passed; effective rank was 11.09/64 and absolute graph-size
  correlation was 0.490, so the overall gate failed. No FAISS index or
  candidate pool was created.

### Interrupted three-epoch retry (not a result)

- **Run directory:**
  `/mnt/disk4/similar_cases_retrieval/data/experiments/retrieval_first_ssl_structured_strict_s3_encoder_b8_e3_20260815/`
- The server-side wrapper ended abruptly before it wrote an epoch, exit code,
  traceback, or usable artifact. Do not interpret this directory as a failed
  model run or compare it with the completed run.
- Immediately afterward `/mnt/disk4` reported 100% utilization with roughly
  4 KiB free. The disk-full condition also blocked a subsequent source sync;
  no cleanup of other users' files or jobs was attempted.
