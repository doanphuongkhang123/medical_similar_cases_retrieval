# Expert Review — Similar Cases

Streamlit app phục vụ expert review và tạo ground truth ở cấp `visit_id`.

## Retrieval contract

- Candidate pool: toàn bộ giao của 3.500 EHR visit embeddings và clinical-note
  embeddings.
- Không dùng image embedding, vì image linkage hiện chỉ phủ 1.005 visit.
- Mỗi block EHR/note được L2-normalize, nhân trọng số, concatenate, rồi
  L2-normalize lần cuối.
- Top 20 được tính bằng exact cosine similarity và luôn loại chính query.
- Giao diện chỉ trình bày dữ liệu EHR; embedding không được hiển thị.

## Ground-truth persistence

Mỗi lần submit được append vào `data/ground_truth.sqlite3`:

- `review_submissions`: expert, query, timestamp, số ca chọn, cấu hình retrieval,
  snapshot metadata của query và ghi chú.
- `review_selections`: candidate đã chọn, retrieval rank và cosine score.

Submission không ghi đè lịch sử cũ. Một review hợp lệ phải chọn 1–19 case, hoặc
đánh dấu rõ rằng không có case nào trong Top 20 đủ liên quan.

## Run on `vaipe_aiotlab`

```bash
cd /mnt/disk4/similar_cases_retrieval/code/web/expert_review
./run.sh
```

Hoặc:

```bash
conda activate /mnt/disk4/namtn/conda_envs/retrieval
cd /mnt/disk4/similar_cases_retrieval/code/web/expert_review
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Các đường dẫn data có thể override bằng:

- `EXPERT_REVIEW_EHR_ROOT`
- `EXPERT_REVIEW_EHR_EMBEDDINGS`
- `EXPERT_REVIEW_TEXT_EMBEDDINGS`
- `EXPERT_REVIEW_DATABASE`
- `EXPERT_REVIEW_EHR_WEIGHT`
- `EXPERT_REVIEW_TEXT_WEIGHT`
- `EXPERT_REVIEW_PORT`
- `EXPERT_REVIEW_PANEL_HEIGHT` (chiều cao hai panel cuộn độc lập, mặc định 720px)

## Tests

```bash
/mnt/disk4/namtn/conda_envs/retrieval/bin/python -m unittest discover -s tests -v
```
