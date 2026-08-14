# Handoff — Medical Similar Cases Retrieval

**Ngày cập nhật:** 2026-08-13
**Trạng thái:** GT-BEHRT-Visit structured full-visit baseline đã sinh embedding; chưa có đánh giá clinical retrieval

## 0. Ràng buộc truy cập dữ liệu hiện hành

- Từ ngày 2026-08-13, chỉ được đọc dữ liệu thật trên môi trường/máy được người
  dùng gọi là `vaipe`; SSH host chính xác là `vaipe_aiotlab`.
- Sau khi xác định đúng `vaipe`, được tự chủ đọc và thống kê dữ liệu mà không
  cần xin phép lại từng thao tác read-only.
- Dữ liệu trên `vaipe` là read-only: không sửa, xóa, di chuyển, đổi tên hoặc
  ghi artifact vào vùng dữ liệu.
- Dataset được phép đọc là
  `/mnt/disk4/similar_cases_retrieval/data/` trên `vaipe_aiotlab`.
- Không được truy cập server/host khác nếu chưa có xác nhận rõ ràng của người
  dùng.

## 1. Path chuẩn trên vaipe

- SSH host: `vaipe_aiotlab`
- Project root: `/mnt/disk4/similar_cases_retrieval/`
- Dataset root: `/mnt/disk4/similar_cases_retrieval/data/`
- Code/repository root: `/mnt/disk4/similar_cases_retrieval/code/`

Hai thư mục `data/` và `code/` trên đều đã được kiểm tra trực tiếp và đang tồn
tại. Mọi lệnh chạy code trên server về sau phải bắt đầu từ code root mới:

```bash
ssh vaipe_aiotlab \
  'cd /mnt/disk4/similar_cases_retrieval/code && <command>'
```

Lệnh SSH trên được phép dùng cho kiểm tra read-only. Không ghi hoặc sinh
artifact vào dataset root.

## 2. Data mapping cấp cao đã xác minh

Raw data nằm trong `data/raw/`; dataset root chỉ chứa raw, experiment và
processed-area cấp cao.

| Thành phần | Path dưới dataset root | Vai trò dự kiến | Trạng thái mapping |
|---|---|---|---|
| CT | `raw/CT/` | Ảnh CT | Chưa xác minh schema/ID |
| MRI | `raw/MRI/` | Ảnh MRI | Chưa xác minh schema/ID |
| X-quang | `raw/XQ/` | Ảnh X-quang | Chưa xác minh schema/ID |
| PET/CT | `raw/2025 PET CT/` | Ảnh PET/CT | Chưa xác minh schema/ID |
| PDF | `raw/PDF-grBA/` | Tài liệu/bệnh án dạng PDF | Chưa xác minh schema/ID |
| Metadata | `raw/thông tin bệnh án.xlsx` | Metadata bệnh án | Chưa đọc schema cột |

Tên thư mục chỉ cho biết loại nguồn dữ liệu. Chưa được coi chúng là đã liên
kết theo bệnh nhân, ca khám hoặc study cho đến khi kiểm tra schema Excel, tên
file và quy tắc ID. Dữ liệu chỉ được đọc/xử lý trên server; không copy về local
hoặc đưa vào Git.

### Cập nhật linkage ngày 2026-08-13

- Đã xác minh read-only trên `vaipe_aiotlab`: 2.362/2.362 PDF có filename
  stem khớp duy nhất `BenhAn_Id`, nối được vào 2.362/3.500 visit (67,5%).
- Theo quyết định của người dùng, mỗi PDF được coi là một report cấp visit;
  extraction nội dung report thực hiện sau.
- Forced merge metadata DICOM nối 481/1.352 nhóm ảnh về duy nhất một visit;
  sau de-duplicate có 435 visit chứa ảnh.
- Có 305 visit chứa đủ XLSX + ảnh + PDF/report. Image + PDF cũng có 305 case
  khi lấy giao qua visit; chưa có direct study–report link.
- 871 nhóm ảnh không nối được nên bị loại, trong đó 98 nhóm xung đột nhiều
  visit.
- Patient count chính xác chưa có; estimate theo tên chuẩn hóa là 2.773
  patient trên 3.500 visit.
- Đã cài `pydicom==3.0.2` vào environment
  `/mnt/disk1/khangdp/conda_envs/scr_env` theo cho phép của người dùng.

### Clinical-note audit ngày 2026-08-13

- Nguồn narrative cấp visit mạnh nhất là
  `QuaTrinhBenhLyVaDienBienLamSang` (93,8% visit có >=50 ký tự),
  `QuaTrinhBenhLy` (90,1%) và `TomTatBenhAn` (87,8%).
- Report cận lâm sàng ưu tiên `KQCLS.MO_TA` và `KQCLS.KET_LUAN`;
  operative note ưu tiên `TrinhTuThucHien_Text`.
- Toàn bộ 2.362 PDF extract được text ở ba trang đầu/cuối; PDF có median 40
  trang nên phải section/chunk, không encode nguyên tài liệu.
- Có 9 DICOM SR trong 4.642 ZIP CT/MRI/XQ; coverage quá thấp để làm report
  branch chính.
- Chi tiết field, coverage, redundancy và note contract nằm trong
  `docs/DATA.md`.

### XLSX field dictionary ngày 2026-08-13

- Đã audit toàn bộ 209 cột của 5 sheet và phân loại theo
  `Diagnosis/Medicine/Procedure/Note/Observation/Link/Drop`.
- Data dictionary và field selection nằm tại
  `docs/XLSX_FIELD_DICTIONARY.md`.
- Mỗi cột đã có ví dụ cụ thể: categorical lấy từ thống kê aggregate,
  narrative dài dùng câu tổng hợp không định danh, ID được che; cột
  toàn-null/hằng số ghi rõ số dòng và lý do loại.
- Không ép lab, vital và narrative vào ba bảng D/M/P; chúng được giữ làm
  Observation/Note.
- `Thuốc.SoThuTuToa` chỉ có 2 giá trị nên chưa đủ làm prescription ID.
- `Thuốc.HamLuong` là export artifact có một hằng số
  `NGƯỜI NHẬN THUỐC`, không phải hàm lượng thuốc.

## 3. Trạng thái code

- Code root mới `/mnt/disk4/similar_cases_retrieval/code/` đã được đồng bộ từ
  repository local ngày 2026-08-12. Checksum của các file đại diện đã được xác
  minh khớp giữa local và server.
- Code hiện có trên server vẫn ở path legacy
  `/mnt/disk4/khangdp/similar_cases_retrieval/code/`.
- Chưa xóa hoặc sửa code ở path legacy.
- `sync_to_server.sh` và `sync_to_server.ps1` đã trỏ `REMOTE_DIR` tới code root
  mới. Script PowerShell là lựa chọn trực tiếp trên máy Windows hiện tại.
- Local Git đã khôi phục đủ 6 commit, branch `main` đang tracking
  `origin/main`, và Git Credential Manager đã lưu tài khoản GitHub.
- Pipeline local `code/scr_pipeline/` hiện xử lý MIMIC-IV clinical text và lab
  events. Chưa có bằng chứng pipeline này tương thích trực tiếp với dataset
  ảnh, PDF và Excel ở data root mới.

## 4. Việc tiếp theo

1. Đọc schema của `thông tin bệnh án.xlsx` ngay trên server và chỉ ghi lại tên
   cột/kiểu dữ liệu cần thiết, không đưa dữ liệu bệnh nhân vào tài liệu hoặc log.
2. Kiểm tra quy tắc đặt tên trong các thư mục ảnh và PDF để xác định khóa liên
   kết an toàn với metadata.
3. Chốt đơn vị retrieval: bệnh nhân, lượt khám, study ảnh hay tài liệu.
4. Viết `docs/DATA.md` mô tả schema, data lineage, khóa liên kết, split và các
   biện pháp chống leakage.
5. Xác nhận khi nào có thể ngừng sử dụng hoặc lưu trữ code legacy; không xóa
   path legacy nếu chưa có yêu cầu rõ ràng.
6. Đánh giá phần nào của pipeline MIMIC hiện tại có thể tái sử dụng và phần nào
   cần thay bằng ingestion/embedding cho ảnh và PDF.

## 5. Blocker và nội dung chưa chốt

- Chưa xác minh schema và khóa liên kết giữa Excel, PDF và các modality ảnh.
- Chưa chốt đơn vị retrieval và định nghĩa ca “tương tự”.
- Data contract, kiến trúc và kết quả baseline hiện được ghi tại `docs/DATA.md`,
  `docs/ARCHITECTURE.md` và `docs/EXPERIMENTS.md`.

## 6. Cập nhật GT-BEHRT-Visit (2026-08-12)

- Đã thêm `code/ehr_graph_pipeline/` cho canonicalization, sparse visit graph,
  masked-node Graph Transformer pretraining và export embedding.
- Đã chạy full-visit baseline trên workbook server và tạo embedding 256 chiều,
  L2-normalize cho 3.500 `SoBenhAn`. Artifact chỉ ở server data root.
- `docs/DATA.md`, `docs/ARCHITECTURE.md`, `docs/EXPERIMENTS.md` mô tả data
  contract, kiến trúc, split tạm thời và kết quả chạy.
- Các vector hiện là self-supervised baseline, chưa được clinical validation;
  không được dùng để đưa ra kết luận về chất lượng retrieval trước khi có nhãn
  relevance và patient ID pseudonymized cho split chống leakage.

## 7. Cập nhật bộ EHR một dòng/mỗi visit (2026-08-13)

- Đã thêm `code/preprocess_code/preprocess_ehr_tables.py` và kiểm thử bằng
  dữ liệu giả.
- Đã chạy thành công trên workbook thật bằng Python 3.11.15, pandas 3.0.5 và
  openpyxl 3.1.5 trong `scr_env`; không cài thêm package.
- Dữ liệu gốc trên `vaipe` chỉ được đọc. Kết quả tạm được sinh trong `/tmp`,
  sau đó chuyển về thư mục local `preprocessed/`.
- Kết quả có 3.500 dòng visit với khóa chính `(patient_id, visit_id)`, trong đó
  `patient_id=SoVaoVien`, `visit_id=SoBenhAn`.
- Đã tạo các bảng Diagnosis, Medicine, Procedure, Clinical Note, Observation
  và cặp bảng `graph_nodes/graph_edges` cho đúng mục tiêu một visit là một graph.
- Kiểm tra chất lượng: khóa chính duy nhất, không khóa rỗng, không sự kiện mồ
  côi, 3.500 graph, 828.481 nút và 2.309.290 cạnh.
- Workbook `preprocessed/ehr_preprocessed.xlsx` đã được render và kiểm tra hai
  sheet `Tổng_quan`, `Visit_EHR`; không có lỗi công thức.
- Chưa chạy GNN hoặc tạo embedding trong bước này.
- Đã xuất thêm 9 bảng CSV UTF-8 vào `preprocessed/csv/`. Tất cả số dòng, số
  cột, độ rộng bản ghi, dung lượng và checksum đã được đối chiếu thành công.
- Đã tạo `preprocessed/preview_100_visits/` bằng seed `20260813`: 100 visit
  thuộc 99 patient, 23.586 node và 65.216 edge. Mọi bảng con chỉ chứa khóa
  thuộc mẫu; không có khóa visit/node trùng hoặc edge thiếu endpoint.
- Script tái lập việc lấy mẫu là
  `code/preprocess_code/create_csv_preview.py`.

## 8. Đóng gói và đồng bộ EHR preprocessing (2026-08-13)

- Code tái tạo bảng EHR, CSV, preview và archive được tập trung tại
  `code/preprocess_code/`; không bao gồm code/file chỉ phục vụ báo cáo Word.
- Hai archive đã được đồng bộ tới
  `/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/` trên
  `vaipe_aiotlab`:
  - `ehr_preprocessed_full_20260813.tar.gz`;
  - `ehr_preprocessed_preview_100_20260813.tar.gz`.
- `sha256sum -c SHA256SUMS.txt` trên Vaipe trả `OK` cho cả hai archive.
- Test trên `/mnt/disk1/khangdp/conda_envs/scr_env/bin/python` (Python 3.11.15):
  2/2 test preprocessing mới và 5/5 test toàn bộ EHR graph pipeline pass.
- Package đã có sẵn: numpy 2.4.6, pandas 3.0.5, openpyxl 3.1.5,
  pyarrow 25.0.1 và PyYAML 6.0.3; không cài thêm package trong lần này.

## 9. Tổng hợp EHR và image–report audit (2026-08-14)

- Tài liệu handoff đầy đủ được lưu tại
  `docs/EHR_PREPROCESS_AND_IMAGE_REPORT_AUDIT.md`.
- Đã xác minh một ZIP CT có cả CT scout, Enhanced SR dose record và Secondary
  Capture dose-report screen save trong cùng study.
- Dose report là technical radiation report, không phải kết luận chẩn đoán của
  bác sĩ; phải phân loại riêng và khử định danh burned-in text trước khi dùng.
- Hai gói EHR full/preview đã giải nén tại
  `/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/`; checksum của
  toàn bộ CSV sau giải nén khớp manifest.

## 10. Supervised retrieval pipeline (2026-08-14)

- Đã thêm pipeline tạo candidate để review, fine-tune projection từ pairwise
  relevance label, và đánh giá `Precision@k`/`mAP@k`/`nDCG@k` tại
  `code/ehr_graph_pipeline/supervised_retrieval.py`.
- Contract nhãn và lệnh chạy được ghi tại `docs/RETRIEVAL_PIPELINE.md`; code
  không tự suy diễn relevance từ ICD, diagnosis, medication hoặc outcome.
- Test fixture giả trên `vaipe_aiotlab`, Python
  `/mnt/disk1/khangdp/conda_envs/scr_env/bin/python` 3.11.15: 5/5 pass.
- SSH shell `zsh` hiện không expose lệnh `conda`; pipeline dùng trực tiếp
  executable đã xác minh của `scr_env`, không đổi sang environment khác.
- Chưa chạy pipeline trên dữ liệu thật và chưa tạo retrieval artifact; blocker
  là rubric relevance được phê duyệt cùng split patient-disjoint.
