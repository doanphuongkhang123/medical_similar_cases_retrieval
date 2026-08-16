# Clinical-note text embedding

Pipeline gom toàn bộ section/note theo `visit_id`, chạy
`Qwen/Qwen3-Embedding-8B` và xuất một vector cố định cho mỗi visit. Note dài
ngắn khác nhau vẫn cho cùng dimension; context tối đa là 32.768 token.

Hai output được tạo đồng thời:

- 4096-D: model output đã L2-normalize;
- 256-D: lấy prefix 256 chiều từ vector 4096-D rồi L2-normalize lại, dùng để
  khớp dimension EHR embedding.

Output không chứa raw clinical text.

```bash
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
"$PYTHON" code/text_embedding_pipeline/embed_clinical_notes.py \
  --input-notes /mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/ehr_preprocessed_full/clinical_notes.parquet \
  --input-visits /mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/ehr_preprocessed_full/visits.parquet \
  --output-dir /mnt/disk4/similar_cases_retrieval/data/note_emb \
  --model Qwen/Qwen3-Embedding-8B \
  --max-length 32768 --quantization 8bit --precision fp16
```

Run hiện tại đã embed đủ 3.500 visit. Artifact chính là
`visit_note_embeddings_qwen3_8b_4096d.csv`,
`visit_note_embeddings_qwen3_8b_256d.csv` và `manifest.json` trong
`/mnt/disk4/similar_cases_retrieval/data/note_emb/`.
