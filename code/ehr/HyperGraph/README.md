# HyperGraph — HypeMed-style EHR preparation

Pipeline này đọc trực tiếp workbook EHR raw và tạo cấu trúc ba domain giống
đầu vào của HypeMed:

```text
patient -> ordered visits -> [diagnosis set, procedure set, medication set]
```

Mỗi visit đồng thời là một hyperedge trong ba incidence matrix tách biệt cho
diagnosis, procedure và medication. `YeuCauChiTiet_Id` được giữ đúng vai trò
service-event provenance; nó không được dùng làm visit ID.

## ID contract

- `patient_id = SoVaoVien`
- `visit_id = SoBenhAn`
- `service_event_id = YeuCauChiTiet_Id`

## Semantic contract

- Diagnosis giữ chuỗi ICD sau canonicalization, nhưng version ICD chưa được
  xác minh độc lập.
- Procedure dùng token hash ổn định từ tên chỉ định DVKT nội bộ. Domain này bao
  gồm cả service request xét nghiệm/hình ảnh, chưa phải tập billed procedure code
  đã được chuyên gia phân loại như MIMIC.
- Medication dùng token hash ổn định từ hoạt chất, fallback tên thuốc.
- Không tạo giả ATC mapping hoặc DDI matrix. Vì vậy artifact tương thích với
  HypeMed về cấu trúc dữ liệu/hypergraph, chưa thể chạy nguyên trạng loss DDI và
  knowledge hierarchy của repository gốc.

## Chạy trên Vaipe

```bash
CUDA_VISIBLE_DEVICES="" \
/mnt/disk1/khangdp/conda_envs/scr_env/bin/python \
  /mnt/disk4/similar_cases_retrieval/code/code/ehr/HyperGraph/prepare_hypergraph.py \
  --workbook "/mnt/disk4/similar_cases_retrieval/data/ehr/raw/thông tin bệnh án.xlsx" \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr/HyperGraph
```

Mặc định pipeline:

- giữ top 2.000 diagnosis;
- không giới hạn procedure;
- giữ top 300 medication;
- loại các dòng thuốc có `LyDoTraThuoc`;
- yêu cầu visit có đủ cả ba domain sau filtering;
- sau đó chỉ giữ bệnh nhân có ít nhất hai visit;
- sắp visit theo admission time;
- sắp patient bằng stable SHA-256 order với seed `424724` để split theo lát cắt
  của HypeMed không phụ thuộc thứ tự ID nguồn.

## Output

```text
HyperGraph/
├── structured/       # bảng normalized riêng của pipeline trước cohort filter
├── cohort/           # cohort cuối và node-hyperedge memberships
├── vocabularies/     # mapping token/index cùng local labels và frequency
├── hypergraphs/      # COO incidence arrays dạng compressed NPZ
├── hypemed/          # records_final.pkl, voc_final.pkl, ehr_adj_final.pkl
├── audit/            # counts và invariant checks
└── manifest.json     # raw path/SHA-256, config, code hash, artifact hashes
```

`records_final.pkl` có layout:

```python
records[patient][visit] = [diagnosis_ids, procedure_ids, medication_ids]
```

`voc_final.pkl` dùng `types.SimpleNamespace` với `word2idx` và `idx2word`, nên
`dill.load()` trong HypeMed có thể đọc được. `ddi_A_final.pkl` cố ý không được
tạo cho đến khi thuốc đã được review-map sang ATC và DDI source hợp lệ.

## Test

```bash
CUDA_VISIBLE_DEVICES="" \
/mnt/disk1/khangdp/conda_envs/scr_env/bin/python \
  /mnt/disk4/similar_cases_retrieval/code/code/ehr/HyperGraph/tests/test_prepare_hypergraph.py
```

File test cũng có thể chạy bằng `pytest` nếu environment đã cài package đó.

Sau mỗi lần materialize, mở lại và xác minh độc lập toàn bộ artifact:

```bash
CUDA_VISIBLE_DEVICES="" \
/mnt/disk1/khangdp/conda_envs/scr_env/bin/python \
  /mnt/disk4/similar_cases_retrieval/code/code/ehr/HyperGraph/verify_hypergraph.py \
  --root /mnt/disk4/similar_cases_retrieval/data/ehr/HyperGraph
```
