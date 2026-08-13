# Data contract — GT-BEHRT-Visit

**Dataset host:** `vaipe` via SSH host `vaipe_aiotlab`
**Raw data path (read-only):** `/mnt/disk4/similar_cases_retrieval/data/raw/`
**Workbook:** `/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx`
**Graph unit:** one `SoBenhAn` = one visit graph.
**Baseline snapshot:** `full_visit` (retrospective retrieval only).

Data dictionary đầy đủ cho 209 cột, mức ưu tiên và mapping
`Diagnosis/Medicine/Procedure` nằm tại
`docs/XLSX_FIELD_DICTIONARY.md`.

## Multimodal linkage audit

Read-only audit ngày 2026-08-13:

| Link | Kết quả | Trạng thái |
|---|---:|---|
| PDF filename stem → `BenhAn_Id` | 2.362/2.362 PDF | Verified, unique visit |
| Visit có PDF theo `BenhAn_Id` | 2.362/3.500 visit (67,5%) | Verified |
| Imaging group → visit qua DICOM metadata | 481 group → 435 visit | Conservative forced merge |
| Visit có cả ảnh và PDF | 305/3.500 visit (8,7%) | Merged through visit |
| DICOM SR → imaging study | Có ứng viên SR, cần kiểm tra UID/reference | Candidate |

Phép nối PDF được định nghĩa:

```text
PDF filename stem = BenhAn_Id
BenhAn_Id → SoBenhAn
```

`BenhAn_Id` unique trong 3.500 dòng sheet chính nên 2.362 PDF trên quy về
duy nhất 2.362 visit. Theo quyết định của người dùng ngày 2026-08-13, mỗi PDF
được coi là một `report` ở cấp visit; nội dung/section report sẽ được extract
ở giai đoạn sau. ID chỉ phục vụ linkage/lineage, không được đưa vào feature
hoặc embedding.

### Thống kê cohort merge

Đơn vị `case` trong bảng dưới là một `SoBenhAn`/visit sau de-duplicate:

| Cohort | Số case | Tỷ lệ trên 3.500 visit |
|---|---:|---:|
| XLSX + ảnh | 435 | 12,4% |
| XLSX + PDF/report | 2.362 | 67,5% |
| Ảnh + PDF/report | 305 | 8,7% |
| XLSX + ảnh + PDF/report | 305 | 8,7% |

`Ảnh + PDF` hiện được xác định bằng giao của hai tập visit sau khi từng
modality đã nối về XLSX; chưa phải direct study–report link. Trong 435 visit
có ảnh, 305 visit (70,1%) đồng thời có PDF/report.

### Quy tắc forced merge ảnh

Đã đọc một DICOM đại diện cho mỗi 1.352 nhóm ảnh và ưu tiên các cặp khóa:

1. DICOM `PatientID` → XLSX `SoVaoVien`;
2. DICOM `PerformedProcedureStepID` → XLSX `YeuCauChiTiet_Id`;
3. DICOM `AccessionNumber` → XLSX `YeuCauChiTiet_Id`;
4. tên bệnh nhân + ngày chỉ dùng làm fallback.

Kết quả:

- 481/1.352 nhóm ảnh quy về duy nhất một visit;
- sau de-duplicate còn 435 visit có ít nhất một nhóm ảnh;
- theo modality có 168 nhóm CT, 151 nhóm MRI và 162 nhóm XQ được nối;
- 871 nhóm không nối được; trong số này có 98 nhóm cho kết quả xung đột/nhiều
  visit và toàn bộ 761 nhóm PET/CT trong audit hiện tại;
- fallback tên + ngày không bổ sung được case hợp lệ nào.

Liên kết PDF–visit không tự chứng minh report mô tả một imaging study cụ thể.
Cho đến khi có `StudyInstanceUID`, referenced SOP hoặc bridge table chính
thức:

- PDF/report được gắn ở cấp visit với `report_scope=visit`;
- không tạo cạnh `REPORTS_ON → imaging_study`;
- không dùng cùng-thư-mục, tên bệnh nhân hoặc thời gian gần nhau để nâng
  candidate thành verified.

Số patient chính xác chưa xác định được vì XLSX không có patient ID đã xác
minh. Sheet chỉ định có 2.773 tên bệnh nhân khác nhau sau chuẩn hóa trên 3.500
visit, không có xung đột tên trong cùng visit. Vì trùng tên và biến thể cách
viết có thể tồn tại, `2.773` chỉ là **patient estimate by normalized name**,
không phải patient count dùng cho patient-disjoint split.

## Clinical-note and report source audit

Audit read-only ngày 2026-08-13 xác định nguồn text giống ghi chú/report của
bác sĩ nhất cho mỗi visit. Hiện chỉ tạo note chắc chắn ở cấp `SoBenhAn`;
chưa được gộp nhiều visit thành patient longitudinal record vì chưa có
patient ID đã xác minh.

### Clinical narrative trong sheet chính

Ngưỡng `>=50 ký tự` chỉ dùng để đo coverage có nội dung đủ dài, không phải
tiêu chí loại dữ liệu cuối cùng:

| Field | Visit có >=50 ký tự | Coverage | Median / P95 ký tự |
|---|---:|---:|---:|
| `QuaTrinhBenhLyVaDienBienLamSang` | 3.284 | 93,8% | 262 / 542 |
| `QuaTrinhBenhLy` | 3.152 | 90,1% | 227 / 510 |
| `TomTatBenhAn` | 3.074 | 87,8% | 266 / 650 |
| `ChanDoanRaVien` | 2.786 | 79,6% | 82 / 261 |
| `KhamBenhToanThan` | 2.704 | 77,3% | 83 / 167 |
| `PPDT` | 2.095 | 59,9% | 64 / 138 |
| `HuongDieuTriVaCheDoTiepTheo` | 1.697 | 48,5% | 49 / 163 |
| `HuongDanDieuTri` | 1.687 | 48,2% | 47 / 135 |
| `KhamBenhBoPhanTonThuong` | 1.634 | 46,7% | 45 / 227 |
| `TienSuBanThan` | 1.038 | 29,7% | 25 / 137 |
| `LyDoVaoVien` | 43 | 1,2% | 13 / 36 |

Hợp của các field narrative được audit có nội dung >=50 ký tự ở 3.489/3.500
visit. `LyDoVaoVien` thường ngắn nhưng vẫn có giá trị lâm sàng, nên không
được loại chỉ vì không đạt 50 ký tự.

Ba field dài nhất có nội dung trùng nhau:

- `QuaTrinhBenhLy` và `QuaTrinhBenhLyVaDienBienLamSang`: 884 visit giống
  hệt; median word-set Jaccard 0,643.
- `QuaTrinhBenhLy` và `TomTatBenhAn`: 429 visit giống hệt.
- `TomTatBenhAn` và `QuaTrinhBenhLyVaDienBienLamSang`: 436 visit giống
  hệt.

Vì vậy phải giữ section label và deduplicate text giống hệt, không nối thô ba
field rồi coi là ba bằng chứng độc lập.

### Narrative/report ở các sheet event

| Nguồn | Field | Visit có >=50 ký tự | Vai trò |
|---|---|---:|---|
| Chỉ định DVKT | `ChanDoan` | 2.233 | Chẩn đoán đi kèm order; thường lặp |
| Thuốc | `ChanDoanKhoaKham` | 2.618 | Chẩn đoán tại khoa; thường lặp theo dòng thuốc |
| Thuốc | `LoiDan` | 929 | Hướng dẫn dùng thuốc |
| KQCLS | `MO_TA` | 3.080 | Findings/mô tả cận lâm sàng |
| KQCLS | `KET_LUAN` | 2.940 | Impression/kết luận cận lâm sàng |
| Phẫu thuật/thủ thuật | `TrinhTuThucHien_Text` | 2.020 | Operative/procedure note |
| Phẫu thuật/thủ thuật | `KetQua` | 581 | Kết quả thủ thuật |

`KQCLS.MO_TA` và `KQCLS.KET_LUAN` là cặp field gần report chuyên khoa
nhất. Chúng phải giữ quan hệ với order qua `YeuCauChiTiet_Id` và được pool
theo visit; không flatten thành một chuỗi mất nguồn gốc.

`ChanDoan` và `ChanDoanKhoaKham` xuất hiện lặp lại trên nhiều order/dòng
thuốc. Chúng là assessment/context, không được đếm như các note độc lập.

### PDF/report

Toàn bộ 2.362 PDF đều extract được text ở ba trang đầu và ba trang cuối:

- số trang median 40, P95 111, tối đa 389;
- ba trang đầu median 3.377 ký tự;
- ba trang cuối median 2.612 ký tự;
- ba trang đầu: 100% có dấu hiệu section xét nghiệm và kết luận;
- ba trang cuối: 100% có dấu hiệu khám bệnh, xét nghiệm và phẫu thuật/thủ
  thuật;
- dấu hiệu chẩn đoán hình ảnh xuất hiện ở 2,8% ba trang đầu và 12,3% ba trang
  cuối.

PDF là report/document hỗn hợp cấp visit, không phải một radiology report
ngắn. Không encode nguyên PDF thành một sequence. Phải section/chunk, loại
header/footer lặp và pool các chunk thành `z_report`.

Section audit trên chỉ đọc ba trang đầu/cuối của toàn bộ PDF. Full-text scan
toàn bộ 40--389 trang mỗi PDF vượt giới hạn thời gian của audit hiện tại.

### DICOM Structured Report

Đã đọc DICOM header đầu tiên của toàn bộ 4.642 ZIP CT/MRI/XQ:

- 4.641 ZIP đọc được, 1 ZIP lỗi `BadZipFile`;
- có 9 DICOM SR: 5 CT, 3 MRI và 1 XQ;
- cả 9 có nội dung text; tổng cộng 153 text items và 2.764 ký tự.

DICOM SR là report gần ảnh nhất nhưng coverage quá thấp, nên chỉ dùng làm
nguồn bổ sung khi có, không dùng làm nhánh report chính.

### Clinical-note contract đề xuất

```text
visit_clinical_note
├── history
│   ├── LyDoVaoVien
│   ├── QuaTrinhBenhLy
│   ├── TienSuBanThan
│   └── TienSuGiaDinh
├── examination
│   ├── KhamBenhToanThan
│   ├── KhamBenhBoPhanTonThuong
│   └── các system-exam fields
├── summary
│   └── TomTatBenhAn
├── clinical_course
│   └── QuaTrinhBenhLyVaDienBienLamSang
├── assessment
│   ├── KhamBenhBenhChinh
│   └── diagnosis fields
├── plan
│   ├── PPDT
│   ├── HuongDanDieuTri
│   └── HuongDieuTriVaCheDoTiepTheo
├── ancillary_reports[]
│   ├── KQCLS.MO_TA
│   └── KQCLS.KET_LUAN
├── procedure_notes[]
│   ├── TrinhTuThucHien_Text
│   └── KetQua
└── pdf_report_chunks[]
```

Với snapshot admission/24 giờ, không được dùng
`QuaTrinhBenhLyVaDienBienLamSang`, `ChanDoanRaVien`, kết quả sau cutoff
hoặc phần cuối PDF. Với full-visit retrospective embedding, được dùng các
section này nhưng phải gắn timestamp/source rõ ràng.

## Verified workbook links

| Source sheet | Visit key | Event key / link |
|---|---|---|
| `thông tin bệnh án` | `SoBenhAn` | one main visit row |
| `chỉ định DVKT` | `SoBenhAn` | `YeuCauChiTiet_Id` defines `ORDER` |
| `Thuốc` | `sobenhan` | `SoThuTuToa` defines `PRESCRIPTION` |
| `KQCLS` | `SoBenhAn` | `YeuCauChiTiet_Id` → `ORDER` |
| `Phẫu thuật thủ thuật` | inherited through `YeuCauChiTiet_Id` | `YeuCauChiTiet_Id` → `ORDER` → visit |

`SoVaoVien` is not used as the graph key. Join IDs are retained only for
lineage and graph edge construction; they are not model features.

## Feature and privacy policy

The initial structured baseline permits approved admission text-section names,
vitals, services, drugs/active ingredients, lab test/value/unit/time, and
procedure service/time. Raw text is normalized then hashed before the canonical
tables are written, and does not enter graph tensors in this version.

Direct identifiers and administrative fields are excluded, including names,
addresses, insurance numbers, clinicians, contacts, and administrative IDs.
Discharge diagnosis, outcome, post-treatment fields, and `MaICD`/`ICD_phu` are
also excluded from features pending confirmation that they are available at the
chosen observation snapshot.

## Split and leakage limitations

The current deterministic split is visit-disjoint (seed `20260812`, 70/15/15).
It is **not patient-disjoint**, because no approved pseudonymized patient ID has
been supplied. Vocabulary and numeric robust statistics are fitted on the train
visits only. A patient-disjoint split must replace this provisional split when
such an ID is available.

`first_24h` is supported by the code but should not be used until timestamp
precision has been audited. Query and candidate embeddings must always use the
same snapshot policy.

## Bản EHR một dòng cho mỗi lượt khám — 2026-08-13

Theo mục tiêu mới nhất, bộ dữ liệu đã xử lý dùng khóa chính ghép:

- `patient_id = SoVaoVien`; đã đối chiếu với `Thuốc.mayte` và không thấy xung
  đột ánh xạ trong các lượt khám có dữ liệu thuốc;
- `visit_id = SoBenhAn`; có 3.500 giá trị duy nhất trên 3.500 lượt khám;
- khóa chính của một dòng EHR là `(patient_id, visit_id)`.

`SoVaoVien` được dùng như mã bệnh nhân vận hành trong bộ dữ liệu hiện tại vì
nó có 3.095 giá trị trên 3.500 lượt khám và một mã có thể xuất hiện ở nhiều
lượt khám. Đây chưa phải khẳng định rằng mã này là mã bệnh nhân chuẩn dùng
xuyên suốt mọi hệ thống bên ngoài workbook.

Đầu ra local nằm trong `preprocessed/` và không được commit:

- `visit_ehr.parquet`: một dòng cho mỗi lượt khám; có `diagnosis`, `medicine`,
  `procedure`, `clinical_note`;
- `diagnoses.parquet`, `medicines.parquet`, `procedures.parquet`: các bảng sự
  kiện chi tiết;
- `clinical_notes.parquet`: từng phần ghi chú/báo cáo lâm sàng;
- `observations.parquet`: xét nghiệm và dấu hiệu sinh tồn;
- `graph_nodes.parquet`, `graph_edges.parquet`: đồ thị đã bung theo từng visit;
- `ehr_preprocessed.xlsx`: bản kiểm tra trực quan, gồm tổng quan và 3.500 dòng
  `Visit_EHR`.

Số liệu đầu ra: 3.095 bệnh nhân vận hành, 3.500 visit, 34.332 chẩn đoán,
219.105 thuốc, 151.248 dịch vụ/thủ thuật, 90.594 phần ghi chú, 329.702 quan
sát, 828.481 nút và 2.309.290 cạnh. Không có khóa rỗng hoặc sự kiện mồ côi.

Đây là bản `full_visit`, có thể chứa chẩn đoán ra viện và thông tin sau thủ
thuật. Các cột định danh trực tiếp có cấu trúc đã bị loại, nhưng nội dung văn
bản tự do chưa được khử định danh; không chia sẻ đầu ra ra ngoài môi trường
được phép.
