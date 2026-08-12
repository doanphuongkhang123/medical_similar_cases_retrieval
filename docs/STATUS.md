# Handoff — Medical Similar Cases Retrieval

**Ngày cập nhật:** 2026-08-12
**Trạng thái:** GT-BEHRT-Visit structured full-visit baseline đã sinh embedding; chưa có đánh giá clinical retrieval

## 1. Path chuẩn trên server

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

## 2. Data mapping cấp cao đã xác minh

Dataset root hiện có các nhóm dữ liệu cấp cao:

| Thành phần | Path dưới dataset root | Vai trò dự kiến | Trạng thái mapping |
|---|---|---|---|
| CT | `CT/` | Ảnh CT | Chưa xác minh schema/ID |
| MRI | `MRI/` | Ảnh MRI | Chưa xác minh schema/ID |
| X-quang | `XQ/` | Ảnh X-quang | Chưa xác minh schema/ID |
| PET/CT | `2025 PET CT/` | Ảnh PET/CT | Chưa xác minh schema/ID |
| PDF | `PDF-grBA/` | Tài liệu/bệnh án dạng PDF | Chưa xác minh schema/ID |
| Metadata | `thông tin bệnh án.xlsx` | Metadata bệnh án | Chưa đọc schema cột |

Tên thư mục chỉ cho biết loại nguồn dữ liệu. Chưa được coi chúng là đã liên
kết theo bệnh nhân, ca khám hoặc study cho đến khi kiểm tra schema Excel, tên
file và quy tắc ID. Dữ liệu chỉ được đọc/xử lý trên server; không copy về local
hoặc đưa vào Git.

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
