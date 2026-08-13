# Tổng hợp EHR preprocessing, visit graph và kiểm tra image–report

**Ngày cập nhật:** 2026-08-14
**Môi trường dữ liệu:** `vaipe_aiotlab`
**Phạm vi:** EHR table, clinical note, visit graph, full/preview export,
liên kết ảnh–PDF và kiểm tra DICOM report.

Tài liệu này không ghi tên, mã bệnh nhân, ngày sinh, bác sĩ, UID DICOM gốc
hoặc nội dung tự do có thể nhận diện người bệnh. ID minh họa đã được băm.

## 1. Đường dẫn hiện hành

```text
/mnt/disk4/similar_cases_retrieval/
├── code/                         # bản code thực thi trên Vaipe
└── data/
    ├── raw/                      # dữ liệu gốc, chỉ đọc
    │   ├── thông tin bệnh án.xlsx
    │   ├── CT/
    │   ├── MRI/
    │   ├── XQ/
    │   ├── 2025 PET CT/
    │   └── PDF-grBA/
    ├── ehr_preprocessed/         # gói EHR đã đồng bộ và giải nén
    ├── experiments/              # artifact thí nghiệm
    └── processed/                # vùng dữ liệu xử lý chung
```

Environment dùng để kiểm tra:

```text
/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
Python 3.11.15
```

Các package đã có sẵn, không cài thêm trong lần xử lý này:

- numpy 2.4.6;
- pandas 3.0.5;
- openpyxl 3.1.5;
- pyarrow 25.0.1;
- PyYAML 6.0.3;
- pydicom 3.0.2;
- Pillow 12.3.0.

## 2. Kết quả tiền xử lý EHR full

Đơn vị trung tâm là một lượt khám/visit. Khóa chính:

```text
(patient_id, visit_id)
patient_id = SoVaoVien
visit_id   = SoBenhAn
graph_id   = patient_id + "::" + visit_id
```

| Thành phần | Số lượng |
|---|---:|
| Patient | 3.095 |
| Visit | 3.500 |
| Diagnosis | 34.332 |
| Medicine | 219.105 |
| Procedure | 151.248 |
| Clinical-note section | 90.594 |
| Observation | 329.702 |
| Graph node | 828.481 |
| Graph edge | 2.309.290 |

Các kiểm tra đã đạt:

- khóa `(patient_id, visit_id)` duy nhất trong bảng visit;
- không có khóa visit rỗng;
- không có event trỏ tới visit không tồn tại;
- không có `node_id` trùng trong cùng graph;
- không có edge trỏ tới node không tồn tại;
- có đúng 3.500 graph, tương ứng 3.500 visit.

## 3. Các bảng EHR đầu ra

| Bảng | Ý nghĩa |
|---|---|
| `visits` | Một dòng tóm tắt cho mỗi visit |
| `visit_ehr` | Một dòng EHR tổng hợp cho mỗi visit |
| `diagnoses` | Chẩn đoán đã loại bản trùng trong visit |
| `medicines` | Thuốc, hoạt chất, đường dùng, liều và thời gian |
| `procedures` | Chỉ định, dịch vụ, thủ thuật và biên bản liên quan |
| `clinical_notes` | Từng section ghi chú/báo cáo có nguồn gốc rõ ràng |
| `observations` | Xét nghiệm, chỉ số và kết quả quan sát |
| `graph_nodes` | Danh sách node của từng visit graph |
| `graph_edges` | Danh sách quan hệ của từng visit graph |

`visit_ehr` có bốn trường nội dung chính:

```text
diagnosis
medicine
procedure
clinical_note
```

Ba trường đầu là danh sách JSON. `clinical_note` là chuỗi ghép các section,
có nhãn section để không làm mất nguồn gốc.

## 4. Nguồn của clinical note và report trong XLSX

Nội dung y khoa không do pipeline tự sinh. Pipeline chỉ đọc các ô có sẵn,
chuẩn hóa khoảng trắng, thêm nhãn section, loại bản trùng và gom theo visit.

| `note_type` | Sheet nguồn | Cột nguồn chính |
|---|---|---|
| `visit_note` | `thông tin bệnh án` | `LyDoVaoVien`, `QuaTrinhBenhLy`, `TomTatBenhAn`, các trường khám, diễn biến và điều trị |
| `order_note` | `chỉ định DVKT` | `GhiChu` |
| `clinical_report` | `KQCLS` | `MO_TA`, `KET_LUAN` |
| `procedure_report` | `Phẫu thuật thủ thuật` | `TrinhTuThucHien_Text`, `KetQua` |

Ví dụ cấu trúc pipeline tạo ra:

```text
Mô tả: <nội dung gốc từ KQCLS.MO_TA>
Kết luận: <nội dung gốc từ KQCLS.KET_LUAN>
```

và:

```text
Trình tự thực hiện: <nội dung gốc từ TrinhTuThucHien_Text>
Kết quả: <nội dung gốc từ KetQua>
```

Các nhãn `Mô tả`, `Kết luận`, `Trình tự thực hiện` và `Kết quả` do pipeline
thêm. Phần nội dung sau nhãn đã có sẵn trong XLSX.

Nguồn gốc các cột trong `clinical_notes`:

| Cột | Nguồn/cách tạo |
|---|---|
| `patient_id` | `SoVaoVien` |
| `visit_id` | `SoBenhAn` |
| `note_type` | Quy ước của pipeline |
| `section_name` | Nhãn tiếng Việt do pipeline ánh xạ từ tên cột |
| `note_text` | Nội dung từ XLSX sau làm sạch |
| `event_time` | Thời điểm visit/order/kết quả/thủ thuật tương ứng |
| `source_sheet` | Tên sheet chứa dữ liệu gốc |
| `source_key` | Tên field hoặc `YeuCauChiTiet_Id` để truy vết |
| `source_row_count` | Số dòng giống nhau được gom lại |
| `note_id` | Hash ổn định do pipeline tạo |

PDF ngoài workbook chưa được đưa vào `clinical_notes` hoặc `clinical_note`.
PDF vẫn là một modality report riêng.

## 5. Visit graph hiện tại

Mỗi visit tạo thành một heterogeneous graph độc lập. Node `VISIT` là node
trung tâm.

```text
VISIT
├── DIAGNOSIS
├── MEDICINE
├── PROCEDURE
├── NOTE
└── OBSERVATION
```

### 5.1. Loại node

| Node type | Nội dung |
|---|---|
| `VISIT` | Lượt khám, khoa và thời điểm nhập viện |
| `DIAGNOSIS` | Mã, tên và loại chẩn đoán |
| `MEDICINE` | Thuốc, hoạt chất, đường dùng, hướng dẫn và số lượng |
| `PROCEDURE` | Dịch vụ/thủ thuật, báo cáo và kết quả |
| `NOTE` | Một section clinical note/report |
| `OBSERVATION` | Chỉ số xét nghiệm, kết quả, đơn vị và thời gian |

Các trường node:

```text
graph_id, patient_id, visit_id, node_id, node_type,
concept_code, concept_name, text_value, numeric_value,
unit, event_time, source_event_id
```

### 5.2. Loại edge

```text
VISIT     --has_diagnosis-->   DIAGNOSIS
DIAGNOSIS --diagnosis_of-->    VISIT

VISIT     --has_medicine-->    MEDICINE
MEDICINE  --medicine_of-->     VISIT

VISIT     --has_procedure-->   PROCEDURE
PROCEDURE --procedure_of-->    VISIT

VISIT     --has_note-->        NOTE
NOTE      --note_of-->         VISIT

VISIT       --has_observation--> OBSERVATION
OBSERVATION --observation_of-->  VISIT

PROCEDURE --has_report--> NOTE
NOTE      --report_of-->  PROCEDURE

PROCEDURE  --has_result--> OBSERVATION
OBSERVATION --result_of--> PROCEDURE
```

Edge được tạo hai chiều để GNN truyền thông tin từ visit tới event và từ event
trở lại visit.

## 6. Preview 100 visit

Preview được chọn theo visit trước, sau đó giữ toàn bộ event, node và edge của
các visit đã chọn. Không lấy 100 dòng độc lập ở từng bảng.

```text
sample size = 100 visit
random seed = 20260813
sampling    = không hoàn lại
```

| Thành phần | Số lượng |
|---|---:|
| Patient | 99 |
| Visit | 100 |
| Diagnosis | 935 |
| Medicine | 6.584 |
| Procedure | 4.263 |
| Clinical-note section | 2.565 |
| Observation | 9.139 |
| Graph node | 23.586 |
| Graph edge | 65.216 |

Phân bố node:

| Node type | Số node |
|---|---:|
| `VISIT` | 100 |
| `DIAGNOSIS` | 935 |
| `MEDICINE` | 6.584 |
| `PROCEDURE` | 4.263 |
| `NOTE` | 2.565 |
| `OBSERVATION` | 9.139 |

Phân bố edge:

| Relation | Số edge |
|---|---:|
| `has_observation` | 9.139 |
| `observation_of` | 9.139 |
| `has_result` | 8.636 |
| `result_of` | 8.636 |
| `has_medicine` | 6.584 |
| `medicine_of` | 6.584 |
| `has_procedure` | 4.263 |
| `procedure_of` | 4.263 |
| `has_note` | 2.565 |
| `note_of` | 2.565 |
| `has_diagnosis` | 935 |
| `diagnosis_of` | 935 |
| `has_report` | 486 |
| `report_of` | 486 |

Preview đã đạt các kiểm tra:

- 100 khóa visit duy nhất;
- cả node và edge chứa đúng 100 graph;
- không có node trùng;
- không có edge thiếu endpoint;
- mọi bảng con chỉ chứa visit thuộc mẫu;
- checksum của 10 CSV khớp manifest.

## 7. Gói dữ liệu đã đồng bộ và giải nén

Đường dẫn:

```text
/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/
├── ehr_preprocessed_full_20260813.tar.gz
├── ehr_preprocessed_preview_100_20260813.tar.gz
├── package_manifest.json
├── SHA256SUMS.txt
├── ehr_preprocessed_full/
└── ehr_preprocessed_preview_100/
```

| Gói | Archive | Sau giải nén |
|---|---:|---:|
| Full | 298.529.190 byte | khoảng 1,05 GB, 22 file |
| Preview 100 | 3.500.051 byte | khoảng 23,9 MB, 13 file |

`sha256sum -c SHA256SUMS.txt` trên Vaipe trả `OK` cho cả hai archive.

Kiểm tra sau giải nén:

- 9 CSV full, tổng 839.121.756 byte: không có checksum mismatch;
- 10 CSV preview, tổng 23.908.563 byte: không có checksum mismatch;
- preview metadata vẫn xác nhận 100 visit graph.

File Word tại local `outputs/ehr_data_report/` không được đưa vào archive,
server hoặc Git.

## 8. Ảnh và PDF có đi kèm nhau không?

Không thể kết luận rằng mỗi ảnh có một report đi kèm.

### 8.1. File vật lý

| Nguồn | Số file đã kiểm tra |
|---|---:|
| CT | 1.345 ZIP |
| MRI | 480 ZIP |
| XQ | 2.817 ZIP |
| Tổng CT/MRI/XQ | 4.642 ZIP |
| 2025 PET CT | 795.458 file |
| PDF-grBA | 2.362 PDF |

PDF nằm trong thư mục riêng `PDF-grBA`, không nằm trực tiếp trong các thư mục
CT/MRI/XQ/PET CT.

### 8.2. Liên kết ở cấp visit

PDF được nối bằng:

```text
PDF filename stem = BenhAn_Id
BenhAn_Id → SoBenhAn/visit
```

Kết quả:

| Cohort | Số visit |
|---|---:|
| XLSX + ảnh | 435 |
| XLSX + PDF | 2.362 |
| Ảnh + PDF | 305 |
| XLSX + ảnh + PDF | 305 |

Trong 435 visit có ảnh:

- 305 visit có PDF, tương đương 70,1%;
- 130 visit không có PDF.

`Ảnh + PDF` ở đây chỉ có nghĩa hai modality cùng nối về một visit. Nó chưa
chứng minh PDF mô tả trực tiếp một imaging study cụ thể.

### 8.3. Forced merge ảnh về visit

Một DICOM đại diện được đọc cho 1.352 nhóm ảnh. Khóa nối ưu tiên:

1. `PatientID` → `SoVaoVien`;
2. `PerformedProcedureStepID` → `YeuCauChiTiet_Id`;
3. `AccessionNumber` → `YeuCauChiTiet_Id`;
4. tên + ngày chỉ là fallback.

Kết quả:

- 481/1.352 nhóm ảnh nối duy nhất về một visit;
- sau de-duplicate còn 435 visit có ảnh;
- 168 nhóm CT, 151 nhóm MRI và 162 nhóm XQ được nối;
- 871 nhóm không nối được;
- 98 nhóm cho kết quả xung đột/nhiều visit;
- toàn bộ 761 nhóm PET/CT trong audit chưa nối được.

## 9. Report nằm bên trong gói DICOM

Audit 4.642 ZIP CT/MRI/XQ phát hiện chín DICOM Structured Report:

| Modality folder | Số DICOM SR |
|---|---:|
| CT | 5 |
| MRI | 3 |
| XQ | 1 |
| Tổng | 9 |

Cả chín SR có nội dung text, tổng cộng 153 text item và 2.764 ký tự. Coverage
quá thấp để coi SR là nhánh report chính cho toàn dataset.

## 10. Preview một DICOM Dose Report

Một ZIP CT được chọn bằng ID băm:

```text
archive_id = 57649e44bbbd
```

Trong cùng ZIP có ba DICOM object:

| Object | Có pixel | Vai trò |
|---|---|---|
| `Enhanced SR Storage` | Không | X-Ray Radiation Dose Report dạng cấu trúc |
| `CT Image Storage` | Có | Ảnh CT scout/localizer |
| `Secondary Capture Image Storage` | Có | Ảnh chụp màn hình Dose Report |

Cả ba dùng cùng `StudyInstanceUID`, nên thuộc cùng study. SR mẫu không chứa
tham chiếu trực tiếp tới `SOPInstanceUID` của hai ảnh cùng ZIP.

### 10.1. Preview ASCII đã khử khả năng đọc định danh

Ảnh Secondary Capture được thu nhỏ xuống 72×36 ngay trên Vaipe. Phần lớn nội
dung nằm ở đầu ảnh, phù hợp với màn hình bảng/thông số; nửa dưới gần như trống.

```text
..:.... ..... :........::::...:.                        :.... .. ..:..:.
  . .    ....  .     . .. .                                .. ..   ....
 ......:...:..::.. ...::......                             ....... .:...
....... :. .........                                  :... ....:. .....
....... .. .........                                  ....     .   . ..
...:.:...::::........:.:..:::.:.:: ..:: .:::.:.:::::.:..:.:

                              .:....:::...
                     .... ......    ..... ..       :..       .:.......
  .:.::.    ..::.       :..::...     ..::.:     ......  .       ..:.
                        .....        ... ..     ..... ...        ..
    .       :...:
                              .          .. .      ...
                              ...............      ....
```

### 10.2. Thông tin object

| Thuộc tính | Giá trị |
|---|---|
| SOP Class | `Secondary Capture Image Storage` |
| Modality | `CT` |
| Series Description | `Dose Report` |
| Image Type | `DERIVED / SECONDARY / SCREEN SAVE` |
| Nội dung study | CT chi dưới/khớp, không tiêm thuốc |
| Protocol | Khớp gối |
| Rows × Columns | 512 × 512 |
| Pixel array | `int16`, shape 512×512 |
| Pixel min/max/mean | 0 / 1.023 / 27,27 |
| Photometric | `MONOCHROME2` |
| Samples per pixel | 1 |
| Bits allocated/stored | 16 / 16 |
| High bit | 15 |
| Window center/width | -512 / 1.024 |
| Rescale intercept/slope | -1.024 / 1 |
| Series/instance number | 999 / 1 |
| PixelData size | 524.288 byte |
| PixelData SHA-256 | `1784fa1879fd…e34e7d` |
| BurnedInAnnotation | Thiếu tag/không xác định |

### 10.3. Thiết bị và thông số phát tia

| Thuộc tính | Giá trị |
|---|---|
| Manufacturer | GE Medical Systems |
| Model | Brivo CT385 Series |
| Conversion Type | `WSD` |
| Total Number of Exposures | 1 |
| Body Part Examined | `EXTREMITY` |
| KVP | 120 |
| Exposure Time | 3.399 ms |
| X-Ray Tube Current | 10.000 µA, tương đương 10 mA |
| Acquisition Type | `CONSTANT_ANGLE` |
| Single Collimation Width | 1,25 |
| Total Collimation Width | 340 |

Object còn chứa `ExposureDoseSequence`, `CTDIPhantomTypeCodeSequence` và
`CommentsOnRadiationDose`. Nội dung text tự do không được chép vào tài liệu.

### 10.4. Tag nhạy cảm có tồn tại nhưng đã che

- `PatientName`;
- `PatientID` và `OtherPatientIDs`;
- `PatientBirthDate`, `PatientAge`, `PatientSex`;
- `AdditionalPatientHistory`;
- `AccessionNumber`;
- `InstitutionName`, `StationName`;
- `ReferringPhysicianName`, `PerformingPhysicianName`;
- toàn bộ ngày và thời gian;
- `StudyID`;
- SOP/Study/Series UID gốc;
- private tags;
- nội dung tự do không nằm trong allowlist an toàn.

UID chỉ được ghi dưới dạng hash để vẫn kiểm tra được quan hệ mà không lộ giá
trị gốc.

### 10.5. Kết luận của preview

Trong dataset có một số “report dưới dạng ảnh”, cụ thể là:

```text
Dose Report Screen Save
```

Nhưng đây là technical radiation-dose report do thiết bị tạo, không phải kết
luận chẩn đoán hình ảnh của bác sĩ. Nó không được gộp mù vào clinical report.

Phân loại đề xuất:

```text
node_type       = TECHNICAL_REPORT
report_subtype  = RADIATION_DOSE
source_format   = DICOM_SR hoặc SECONDARY_CAPTURE
clinical_report = false
```

Vì `BurnedInAnnotation` bị thiếu, không được giả định pixel đã sạch định danh.
Cần OCR và khử định danh burned-in text trước khi hiển thị hoặc đưa qua image
encoder.

## 11. Thiết kế multimodal đề xuất

Không ghép report với từng lát cắt DICOM. Đơn vị phù hợp là imaging study hoặc
visit.

```text
VISIT --has_image_study--> IMAGE_STUDY
VISIT --has_visit_pdf----> PDF_REPORT
VISIT --has_ehr_graph----> EHR_GRAPH
```

Chỉ tạo cạnh trực tiếp:

```text
REPORT --reports_on--> IMAGE_STUDY
```

khi có ít nhất một bằng chứng mạnh:

1. report tham chiếu `StudyInstanceUID`/SOP/series;
2. accession khớp duy nhất;
3. bridge table chính thức;
4. khóa nội bộ đã xác minh không xung đột.

Với technical dose report trong cùng study:

```text
IMAGE_STUDY --has_technical_report--> RADIATION_DOSE_REPORT
```

Nhánh embedding đề xuất:

```text
EHR graph --------------------> GNN ----------------> z_ehr
Image studies ----------------> image encoder -----> z_image
Clinical PDF/note chunks -----> text encoder ------> z_report
Technical dose report --------> metadata encoder --> z_technical

[z_ehr, z_image, z_report, modality_mask] --> fusion --> z_visit
```

`z_technical` nên là thông tin phụ, không thay thế `z_report`.

## 12. Code tái tạo

Code preprocessing nằm tại:

```text
code/preprocess_code/
├── preprocess_ehr_tables.py
├── export_parquet_to_csv.py
├── create_csv_preview.py
├── package_preprocessed_data.py
├── requirements.txt
└── tests/
```

Chức năng:

1. XLSX → bảng EHR/graph Parquet;
2. Parquet → CSV UTF-8 + manifest/checksum;
3. CSV full → preview 100 visit bảo toàn quan hệ;
4. đóng gói riêng full và preview.

Kiểm thử trên Vaipe:

- 2/2 test preprocessing mới: pass;
- 5/5 test toàn bộ EHR graph pipeline: pass;
- các lệnh `--help` của ba utility script: pass.

Commit chứa code preprocessing ban đầu:

```text
e83187d data: add visit EHR preprocessing exports
```

## 13. Việc cần làm tiếp

1. Audit toàn bộ SOP Class/Series Description để tách ảnh giải phẫu, DICOM SR,
   dose screen và secondary capture khác.
2. OCR chỉ chạy trên Vaipe; trước khi lưu text phải loại tên, ID, ngày sinh,
   accession và bác sĩ.
3. Xây `study_manifest` có `StudyInstanceUID` đã pseudonymize, modality,
   series, số ảnh và loại report.
4. Tạo `study_report_map` với trạng thái `verified/candidate/rejected` và lý
   do nối.
5. Không coi 305 visit cùng có ảnh+PDF là 305 direct image–report pair.
6. Giữ modality mask vì nhiều visit thiếu ảnh hoặc thiếu report.
7. Chỉ sau khi data contract ổn định mới train image/report fusion.
