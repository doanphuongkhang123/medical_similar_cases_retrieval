# EHR preprocessing code

Thư mục này là nguồn code chính thức để tái tạo bộ EHR table/graph hiện có
trong `preprocessed/`. Dữ liệu thật chỉ được đọc trên `vaipe_aiotlab` tại
`/mnt/disk4/similar_cases_retrieval/data/`; không đưa dữ liệu bệnh nhân vào Git.

## Các bước

1. `preprocess_ehr_tables.py`: đọc workbook, chuẩn hóa theo khóa
   `(patient_id, visit_id)`, tạo Diagnosis, Medicine, Procedure, Clinical Note,
   Observation và graph node/edge dạng Parquet.
2. `export_parquet_to_csv.py`: xuất toàn bộ chín bảng Parquet sang CSV UTF-8
   và tạo `manifest.csv` có SHA-256.
3. `create_csv_preview.py`: chọn visit bằng seed cố định và giữ toàn bộ dòng,
   node, edge liên quan để tạo preview có quan hệ hoàn chỉnh.
4. `package_preprocessed_data.py`: tạo riêng gói `.tar.gz` cho bản full và
   preview, kèm file checksum.

## Lệnh tái tạo

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate /mnt/disk1/khangdp/conda_envs/scr_env

python code/preprocess_code/preprocess_ehr_tables.py \
  --workbook '/mnt/disk4/similar_cases_retrieval/data/thông tin bệnh án.xlsx' \
  --output /tmp/ehr_preprocessed

python code/preprocess_code/export_parquet_to_csv.py \
  --input /tmp/ehr_preprocessed \
  --output /tmp/ehr_preprocessed/csv

python code/preprocess_code/create_csv_preview.py \
  --input /tmp/ehr_preprocessed/csv \
  --output /tmp/ehr_preprocessed/preview_100_visits \
  --n-visits 100 \
  --seed 20260813
```

Không ghi đầu ra trực tiếp vào dataset root nếu tác vụ chỉ là kiểm thử. Các
trường clinical free text chưa được xác nhận đã khử định danh hoàn toàn.
