# Qwen3 patient retrieval

Thư mục này chỉ chứa pipeline retrieval bệnh nhân chạy local bằng
`Qwen/Qwen3-Embedding-0.6B`. Pipeline không dùng API key, không gọi hosted
inference API và không gửi dữ liệu lâm sàng ra ngoài Vaipe.

## Phạm vi

- Nguồn duy nhất: workbook raw
  `/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx`.
- Đơn vị retrieval: bệnh nhân với ID giả danh `Pxxxxx`.
- Mỗi bệnh nhân giữ tối đa ba lượt khám gần nhất.
- Text encoder chỉ gồm `MaICD`, `ICD_phu`, `TomTatBenhAn` và
  `ChanDoanRaVien`; không đưa raw patient/visit ID, ngày hoặc số dòng nguồn vào
  `embedding_text`.
- Mỗi bệnh nhân có một document vector và một query vector 1.024-D. Query
  được thêm retrieval instruction; cả hai ma trận được L2-normalize.
- Retrieval dùng exact cosine bằng tích vô hướng và luôn loại self-match.

## Source được giữ lại

| File | Vai trò |
|---|---|
| `qwen3_patient_embeddings.py` | Prepare, download model, CUDA smoke, full embedding, verify và retrieve. |
| `prepare_qwen3_inputs.py` | Dựng/kiểm tra input bundle riêng trực tiếp từ workbook raw. |
| `profiles.py` | Đọc raw workbook và tạo hồ sơ tối đa ba visit. |
| `common.py` | SHA-256 và ghi/đọc JSON an toàn. |
| `tests/test_qwen3_inputs.py` | Kiểm tra input contract. |
| `tests/test_qwen3_patient_embeddings.py` | Kiểm tra pooling, vector contract và cosine retrieval. |

Các pipeline ranking qua Gemini, OpenAI, Groq và Alibaba đã bị loại bỏ. Không
còn `.env`, provider adapter, prompt/schema API, study bundle runner hoặc test
API trong source này.

## Chạy trên Vaipe

Tuân thủ chính sách GPU trong `AGENTS.md`: kiểm tra `nvidia-smi` trước smoke và
full run. Download và các bước CPU phải ẩn GPU.

```bash
PYTHON=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
CODE=/mnt/disk4/similar_cases_retrieval/code/code/genai_ranking
RAW='/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx'
OUT=/mnt/disk4/similar_cases_retrieval/data/ehr/genai_ranking/qwen3_patient_retrieval_NEW
CACHE=/mnt/disk4/similar_cases_retrieval/data/ehr/genai_ranking/models

cd "$CODE"
CUDA_VISIBLE_DEVICES="" "$PYTHON" qwen3_patient_embeddings.py prepare \
  --workbook "$RAW" --output "$OUT"
CUDA_VISIBLE_DEVICES="" "$PYTHON" qwen3_patient_embeddings.py download \
  --output "$OUT" --cache-dir "$CACHE"
CUDA_VISIBLE_DEVICES=0 "$PYTHON" qwen3_patient_embeddings.py smoke \
  --output "$OUT" --batch-size 1
CUDA_VISIBLE_DEVICES=0 "$PYTHON" qwen3_patient_embeddings.py run \
  --output "$OUT" --batch-size 1
CUDA_VISIBLE_DEVICES="" "$PYTHON" qwen3_patient_embeddings.py verify \
  --output "$OUT"
CUDA_VISIBLE_DEVICES="" "$PYTHON" qwen3_patient_embeddings.py retrieve \
  --output "$OUT" --query P01262 --top-k 20
```

`prepare` và `download` từ chối ghi đè artifact đã tồn tại. `smoke` dùng input
dài nhất thật với đúng precision, batch size và max length; full run chỉ chạy
khi cấu hình khớp smoke đã pass. Model snapshot được pin theo commit và ghi
SHA-256 từng file. `verify` kiểm tra lineage raw, hash output, shape, finite
values, L2 norm và self-match exclusion.

## Artifact đã hoàn tất

Artifact production được giữ tại:

`/mnt/disk4/similar_cases_retrieval/data/ehr/genai_ranking/qwen3_patient_retrieval_0_6b_v1/`

Trạng thái đã kiểm tra trên `vaipe_aiotlab`:

- 3.095 bệnh nhân, 3.484 visit được giữ.
- Model `Qwen/Qwen3-Embedding-0.6B`, revision
  `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`.
- Hai ma trận `3095 × 1024`, `float32`, finite và L2-normalized.
- Smoke và full run dùng `bf16`, batch size 1, max length 32.768.
- Document dài nhất 1.338 Qwen token; query dài nhất 1.365 token.
- Raw SHA-256
  `4d621a576164aef695f7349fa770b916216401632d93078d62639842da1ec899`.
- `clinical_data_sent=false`, `api_calls=0`.
- Trạng thái model output là `complete_not_clinically_validated`; kết quả
  cosine chưa phải ground truth lâm sàng.

Model cache duy nhất cần giữ:

`/mnt/disk4/similar_cases_retrieval/data/ehr/genai_ranking/models/models--Qwen--Qwen3-Embedding-0.6B/`

## Tests

Chạy trên Vaipe, không chạy trên workstation:

```bash
cd /mnt/disk4/similar_cases_retrieval/code/code/genai_ranking
CUDA_VISIBLE_DEVICES="" /mnt/disk1/khangdp/conda_envs/scr_env/bin/python \
  -m unittest discover -s tests -p 'test_*.py' -v
```
