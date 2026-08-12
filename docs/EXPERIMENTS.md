# Experiments

## 2026-08-12 — GT-BEHRT-Visit structured full-visit baseline

- **Host/environment:** `vaipe_aiotlab`, `/mnt/disk1/khangdp/conda_envs/scr_env`, Python 3.11.15.
- **Source dataset:** `/mnt/disk4/similar_cases_retrieval/data/thông tin bệnh án.xlsx` (server-only; no raw data copied to local or Git).
- **Observation policy:** `full_visit`, retrospective only.
- **Graph unit:** `SoBenhAn`; 3,500 visits.
- **Canonical result:** 760,276 event nodes, 542,760 business relations, 0 unmatched lab-order links.
- **Graph result:** 3,500 sparse independent graphs.
- **Split:** deterministic visit-disjoint 70/15/15, seed `20260812`; not patient-disjoint because no approved pseudonymized patient ID is available.
- **Model:** 2-layer relation-aware GT-BEHRT-Visit, hidden/output dimension 256, 4 heads, dropout 0.2.
- **Pretraining:** masked node-concept prediction, mask rate 15%, 5 epochs, 2,464 train graphs. Loss by epoch: 2.8682, 2.2787, 2.1282, 2.0438, 1.9894.
- **Artifacts (server only):**
  - `/mnt/disk4/similar_cases_retrieval/data/ehr_graph_preprocessed/`
  - `/mnt/disk4/similar_cases_retrieval/data/ehr_graph_dataset/`
  - `/mnt/disk4/similar_cases_retrieval/data/ehr_graph_model/gt_behrt_visit.pt`
  - `/mnt/disk4/similar_cases_retrieval/data/ehr_graph_embeddings/visit_embeddings.parquet`

This produces model-trained vectors only. It does not validate clinical
similarity or retrieval quality: relevance labels and patient-disjoint split
are still required before reporting retrieval metrics.
