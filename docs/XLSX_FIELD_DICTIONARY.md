# Từ điển dữ liệu và cách chuẩn hóa tệp XLSX

**Nguồn:** tệp Excel duy nhất trong `/mnt/disk4/similar_cases_retrieval/data/raw/`
trên `vaipe_aiotlab`

**Ngày kiểm tra:** 2026-08-13

**Đơn vị chính:** `SoBenhAn` = một lượt khám

Tài liệu này giải thích toàn bộ cột của 5 trang tính và đề xuất cột nào đi
vào ba nhóm sự kiện lõi:

- `Chẩn đoán`: chẩn đoán;
- `Thuốc`: thuốc;
- `Thủ thuật`: dịch vụ kỹ thuật, thủ thuật hoặc phẫu thuật.

## 1. Cách đọc bảng

| Ký hiệu | Ý nghĩa |
|---|---|
| `P0` | Khóa bắt buộc để liên kết và truy vết nguồn; không dùng làm đặc trưng lâm sàng |
| `P1` | Thông tin lâm sàng cốt lõi |
| `P2` | Thông tin bối cảnh hoặc thông tin phụ hữu ích |
| `P3` | Chỉ dùng sau khi có bảng giải mã hoặc xác minh thêm chất lượng |
| `X` | Loại khỏi mô hình: thông tin định danh, hành chính, hằng số, rỗng hoặc làm lộ thông tin tương lai |

| Đích | Ý nghĩa |
|---|---|
| `D` | Chuẩn hóa vào Chẩn đoán (`Chẩn đoán`) |
| `M` | Chuẩn hóa vào Thuốc (`Thuốc`) |
| `P` | Chuẩn hóa vào Thủ thuật/dịch vụ kỹ thuật (`Thủ thuật`) |
| `N` | Ghi chú hoặc báo cáo lâm sàng; đưa qua bộ mã hóa văn bản |
| `O` | Quan sát lâm sàng: dấu hiệu sinh tồn, xét nghiệm và giá trị đo; giữ riêng |
| `C` | Thông tin bối cảnh: nhân khẩu học, thời gian và kết quả điều trị |
| `L` | Chỉ dùng để liên kết và truy vết nguồn |
| `X` | Loại bỏ |

`Chẩn đoán – Thuốc – Thủ thuật` nên là ba **bảng sự kiện**, không phải ba
cột văn bản khổng lồ. Xét nghiệm, dấu hiệu sinh tồn và ghi chú lâm sàng vẫn
cần cách biểu diễn riêng.

Trong tài liệu này, **mốc giới hạn dữ liệu** là thời điểm muộn nhất mà mô hình
được phép nhìn thấy. Ví dụ, nếu cần biểu diễn bệnh nhân tại thời điểm nhập
viện, mọi kết quả xuất hiện sau lúc nhập viện đều phải được loại ra.

## 2. Ba bảng chuẩn hóa cốt lõi

### 2.1. Bảng Chẩn đoán

Mỗi dòng của bảng chuẩn hóa đại diện cho một chẩn đoán trong một lượt khám.
Bảng nên có: mã lượt khám, mã ICD, nội dung chẩn đoán, loại chẩn đoán
(lúc nhập viện, đi kèm chỉ định, trước mổ, sau mổ hoặc lúc ra viện), thời
điểm ghi nhận và trường nguồn.

Nguồn chính: `MaICD`, `ICD_phu`, `ChanDoanRaVien`,
`KhamBenhBenhChinh`, `KhamBenhBenhKemTheo`,
`KhamBenhPhanBiet`, các cột `ChanDoan` ở những trang tính sự kiện và
chẩn đoán trước/sau phẫu thuật.

### 2.2. Bảng Thuốc

Mỗi dòng đại diện cho một thuốc được kê trong một lượt khám. Bảng nên có: mã
lượt khám, mã toa nếu xác định được, tên thuốc, hoạt chất, đường dùng, liều
sáng/trưa/chiều/tối, đơn vị, số ngày dùng, tổng số lượng, lời dặn, thời điểm
kê và trường nguồn.

Nguồn chính nằm ở trang tính `Thuốc`. `PPHoaChat` ở trang tính chính chỉ
nên dùng như bản tóm tắt phác đồ thuốc/điều trị, không thay thế các dòng
thuốc chi tiết.

### 2.3. Bảng Dịch vụ kỹ thuật, thủ thuật và phẫu thuật

Mỗi dòng đại diện cho một dịch vụ được chỉ định hoặc đã thực hiện. Bảng nên
có: mã lượt khám, mã chi tiết chỉ định, mã dịch vụ, tên dịch vụ, loại dịch
vụ, thời điểm yêu cầu, thời điểm bắt đầu/kết thúc, nơi thực hiện, phương pháp
vô cảm, biên bản thực hiện, kết quả và trường nguồn.

Nguồn chính: `chỉ định DVKT.TenDichVu` và trang tính
`Phẫu thuật thủ thuật`. Một xét nghiệm được xem là dịch vụ đã được chỉ
định, nhưng giá trị đo phải nằm trong bảng Quan sát (`Quan sát`), không
đưa `GIA_TRI` vào bảng Thủ thuật.

## 3. Trang tính `thông tin bệnh án` — 3.500 dòng, 114 cột

Một dòng tương ứng một lượt khám. Đây là nguồn tốt nhất cho ghi chú lâm sàng
cấp lượt khám, chẩn đoán tổng quát, dấu hiệu sinh tồn ban đầu và tóm tắt điều
trị.

| # | Trường | Giải thích | Mức | Đích/quyết định |
|---:|---|---|:---:|---|
| 1 | `SoBenhAn` | Số bệnh án; khóa lượt khám đã xác minh không trùng 3.500/3.500 | P0 | `L`: dùng làm mã lượt khám |
| 2 | `SoVaoVien` | Số vào viện; 3.095 không trùng, có thể lặp giữa lượt khám | P0 | `L`: khóa phụ, hỗ trợ nối DICOM; không làm mã lượt khám |
| 3 | `BenhAn_Id` | mã nội bộ bệnh án, không trùng; khớp phần tên tệp không gồm đuôi của 2.362 PDF | P0 | `L`: nối PDF/báo cáo với lượt khám |
| 4 | `NgayVaoVien` | Thời điểm nhập viện | P1 | `C`: mốc bắt đầu lượt khám và mốc giới hạn dữ liệu |
| 5 | `NgayRaVien` | Thời điểm ra viện | P1 | `C`: xác định khoảng thời gian của toàn bộ lượt khám; không dùng nếu mô hình chỉ được xem dữ liệu ở thời điểm sớm |
| 6 | `ChanDoanRaVien` | Chẩn đoán bằng văn bản lúc ra viện | P1 | `D`: chẩn đoán lúc ra viện; không dùng cho mô hình tại thời điểm nhập viện vì đây là thông tin có sau đó |
| 7 | `MaICD` | Mã ICD chính | P1 | `D`: chuẩn hóa cách viết mã, dấu chấm và phiên bản ICD |
| 8 | `ICD_phu` | Một hoặc nhiều mã ICD phụ | P1 | `D`: tách nhiều mã thành nhiều sự kiện |
| 9 | `TenPhongBan` | Khoa/phòng của lượt khám | P2 | `C`: bối cảnh khoa/phòng điều trị; không thuộc D/M/P |
| 10 | `ketquadieutri` | Kết quả điều trị dạng mã/văn bản ngắn | P2 | `C`: chỉ dùng làm kết quả điều trị/đánh giá; làm lộ thông tin tương lai nếu thời điểm truy vấn sớm |
| 11 | `BenhAnChiTiet_Id` | mã chi tiết bệnh án, không trùng | P0 | `L`: chỉ dùng để truy vết nguồn |
| 12 | `BenhAn_Id` | Bản lặp của cột 3 trong tệp xuất | P0 | `L`: kiểm tra bằng cột 3 rồi chỉ giữ một bản |
| 13 | `LyDoVaoVien` | Lý do/triệu chứng vào viện | P1 | `N`: đưa vào phần lý do vào viện của ghi chú; không tự coi là chẩn đoán |
| 14 | `QuaTrinhBenhLy` | Bệnh sử/quá trình bệnh lý | P1 | `N`: đưa vào phần bệnh sử hiện tại |
| 15 | `TienSuBanThan` | Tiền sử bản thân | P1 | `N`: đưa vào phần tiền sử bệnh; có thể trích chẩn đoán sau bằng quy tắc có kiểm soát |
| 16 | `DiUng` | Cờ có dị ứng, hiện chủ yếu 0/1 | P2 | `O/C`: cờ cho biết có dị ứng; không đủ tên tác nhân |
| 17 | `NgayDiUng` | Trường liên quan thời gian dị ứng nhưng gần như toàn `NULL` | X | Loại bỏ ở phiên bản hiện tại |
| 18 | `MaTuy` | Cờ sử dụng ma túy 0/1 | P2 | `C`: thông tin thói quen và tiền sử xã hội |
| 19 | `NgayMaTuy` | Mốc/số lượng liên quan ma túy, gần như toàn `NULL` | X | Loại bỏ; cần bảng giải mã nếu dùng |
| 20 | `RuouBia` | Cờ sử dụng rượu bia | P2 | `C`: thông tin thói quen và tiền sử xã hội |
| 21 | `NgayRuouBia` | Mốc/số lượng liên quan rượu bia, gần như toàn `NULL` | X | Loại bỏ; cần bảng giải mã |
| 22 | `ThuocLa` | Cờ hút thuốc lá | P2 | `C`: thông tin thói quen và tiền sử xã hội |
| 23 | `NgayThuocLa` | Giá trị thời lượng/số lượng hút thuốc, rất thưa và nghĩa chưa rõ | P3 | `C`: chỉ dùng sau bảng giải mã |
| 24 | `ThuocLao` | Cờ hút thuốc lào | P2 | `C`: thông tin thói quen và tiền sử xã hội |
| 25 | `NgayThuocLao` | Thời lượng/số lượng thuốc lào, rất thưa | P3 | `C`: cần bảng giải mã |
| 26 | `TienSuKhac` | Cờ có tiền sử khác | P2 | `C`: cờ; nội dung có thể ở trường văn bản ghi chú khác |
| 27 | `NgayTienSuKhac` | Mốc liên quan tiền sử khác, gần như toàn `NULL` | X | Loại bỏ |
| 28 | `TienSuGiaDinh` | Tiền sử gia đình | P2 | `N`: đưa vào phần tiền sử gia đình |
| 29 | `KhamBenhToanThan` | Mô tả khám toàn thân | P1 | `N`: đưa vào phần khám toàn thân |
| 30 | `Mach` | Mạch | P1 | `O`: tách giá trị số và đơn vị, rồi kiểm tra khoảng hợp lý |
| 31 | `NhipTho` | Nhịp thở | P1 | `O`: dấu hiệu sinh tồn dạng số |
| 32 | `NhietDo` | Nhiệt độ | P1 | `O`: dấu hiệu sinh tồn dạng số; chuẩn hóa °C |
| 33 | `CanNang` | Cân nặng | P1 | `O`: dấu hiệu sinh tồn dạng số; chuẩn hóa kg |
| 34 | `HuyetApCao` | Huyết áp tâm thu | P1 | `O`: giữ như một dấu hiệu sinh tồn dạng số |
| 35 | `HuyetApThap` | Huyết áp tâm trương | P1 | `O`: giữ như một dấu hiệu sinh tồn dạng số |
| 36 | `KhamBenhBoPhanTonThuong` | Khám bộ phận/vùng tổn thương | P1 | `N`: đưa vào phần khám tại vùng tổn thương |
| 37 | `ThanKinh` | Khám thần kinh | P2 | `N`: khám theo hệ cơ quan |
| 38 | `TuanHoan` | Khám tuần hoàn/tim mạch | P2 | `N`: khám theo hệ cơ quan |
| 39 | `HoHap` | Khám hô hấp | P2 | `N`: khám theo hệ cơ quan |
| 40 | `TieuHoa` | Khám tiêu hóa | P2 | `N`: khám theo hệ cơ quan |
| 41 | `CoXuongKhop` | Khám cơ xương khớp | P2 | `N`: khám theo hệ cơ quan |
| 42 | `TietNieu` | Khám tiết niệu | P2 | `N`: khám theo hệ cơ quan |
| 43 | `SinhDuc` | Khám sinh dục | P2 | `N`: khám theo hệ cơ quan; dữ liệu nhạy cảm |
| 44 | `KhamBenhKhac` | Khám khác | P2 | `N`: khám hệ cơ quan khác |
| 45 | `XetNghiemCLSCanLam` | Chỉ định/kế hoạch cận lâm sàng cần làm | P2 | `N/P`: giữ phần kế hoạch dạng văn bản; có thể trích tên dịch vụ nếu cần |
| 46 | `TomTatBenhAn` | Tóm tắt bệnh án | P1 | `N`: mục `tóm_tắt_bệnh_án`; loại các bản lặp với bệnh sử/diễn biến |
| 47 | `KhamBenhTienLuong` | Tiên lượng | P2 | `N/C`: tiên lượng; làm lộ thông tin tương lai tùy mốc dữ liệu quan sát |
| 48 | `HuongDanDieuTri` | Hướng dẫn/kế hoạch điều trị | P1 | `N`: đưa vào phần kế hoạch điều trị; có thể trích thuốc hoặc thủ thuật |
| 49 | `QuaTrinhBenhLyVaDienBienLamSang` | Diễn biến lâm sàng trong lượt khám | P1 | `N`: mục `diễn_biến_lâm_sàng`; thông tin tương lai làm lộ thông tin tương lai cho mô hình tại thời điểm nhập viện |
| 50 | `XNMau` | Tóm tắt xét nghiệm máu dạng văn bản ngắn | P2 | `N/O`: ưu tiên dữ liệu chi tiết ở KQCLS |
| 51 | `XNTeBao` | Tóm tắt xét nghiệm tế bào | P2 | `N/O`: tóm tắt kết quả cận lâm sàng |
| 52 | `XNBLGP` | Tóm tắt giải phẫu bệnh | P2 | `N/O`: tóm tắt kết quả giải phẫu bệnh |
| 53 | `XNXQuang` | Tóm tắt X-quang | P2 | `N`: tóm tắt kết quả chẩn đoán hình ảnh; không phải ảnh |
| 54 | `XNSieuAm` | Tóm tắt siêu âm | P2 | `N`: tóm tắt kết quả chẩn đoán hình ảnh |
| 55 | `CacXNKhac` | Tóm tắt xét nghiệm/cận lâm sàng khác | P2 | `N/O`: tóm tắt cận lâm sàng khác |
| 56 | `PhuongPhapDieuTri` | Mã nhóm điều trị (`DTTC`, `DTTD`), chưa có bảng giải mã | P3 | `C/P`: nhóm điều trị sau khi giải mã |
| 57 | `PPTienPhauTaiU` | Tham số/liều tiền phẫu tại u, đa số `NULL` | P3 | `P`: có thể là thông tin xạ trị hoặc điều trị; chỉ dùng khi đã biết rõ ý nghĩa và đơn vị |
| 58 | `PPTienPhauTaiHach` | Tham số/liều tiền phẫu tại hạch | P3 | `P`: cần bảng giải mã/đơn vị |
| 59 | `PPDonThuanTaiU` | Tham số/liều điều trị đơn thuần tại u | P3 | `P`: cần bảng giải mã/đơn vị |
| 60 | `PPDonThuanTaiHach` | Tham số/liều đơn thuần tại hạch | P3 | `P`: cần bảng giải mã/đơn vị |
| 61 | `PPPhauThuat` | Mô tả phẫu thuật | P1 | `P`: tên/tóm tắt thủ thuật |
| 62 | `PPHauPhauTaiU` | Tham số/liều hậu phẫu tại u | P3 | `P`: cần bảng giải mã/đơn vị |
| 63 | `PPHauPhauTaiHach` | Tham số/liều hậu phẫu tại hạch | P3 | `P`: cần bảng giải mã/đơn vị |
| 64 | `PPHoaChat` | Phác đồ/thuốc hóa trị dạng văn bản | P1 | `M`: tóm tắt phác đồ; rút ra thuốc/hoạt chất/liều/chu kỳ |
| 65 | `PPSoDot` | Số đợt/chu kỳ điều trị, đa số `NULL` | P3 | `M/P`: cần xác minh định nghĩa |
| 66 | `PPDapUng` | Mã đáp ứng điều trị (`BP`, `HT`, `KDU`) | P2 | `C`: kết quả/đáp ứng điều trị; cần bảng giải mã, làm lộ thông tin tương lai |
| 67 | `PPDieuTriKhac` | Mô tả điều trị khác | P2 | `N`; có thể rút ra `M`/`P` |
| 68 | `TinhTrangNguoiBenhRaVien` | Tình trạng lúc ra viện | P2 | `C/N`: kết quả điều trị; làm lộ thông tin tương lai cho thời điểm truy vấn sớm |
| 69 | `HuongDieuTriVaCheDoTiepTheo` | Kế hoạch sau ra viện/theo dõi | P2 | `N`: kế hoạch; làm lộ thông tin tương lai cho thời điểm truy vấn sớm |
| 70 | `SoToXQuang` | Số tờ X-quang trong hồ sơ | X | Số trang mang tính hành chính; loại bỏ |
| 71 | `SoToCTScanner` | Số tờ CT trong hồ sơ | X | Loại bỏ |
| 72 | `SoToSieuAm` | Số tờ siêu âm | X | Loại bỏ |
| 73 | `SoToXetNghiem` | Số tờ xét nghiệm | X | Loại bỏ |
| 74 | `SoToKhac` | Số tờ khác | X | Loại bỏ |
| 75 | `SoToHoSo` | Tổng số tờ hồ sơ | X | Loại bỏ |
| 76 | `TVaoVien` | Thành phần T lúc vào viện, gần như toàn `NULL` | P3 | `D`: thuộc tính giai đoạn ung thư sau bảng giải mã |
| 77 | `NVaoVien` | Thành phần N lúc vào viện | P3 | `D`: thuộc tính giai đoạn bệnh |
| 78 | `MVaoVien` | Thành phần M lúc vào viện | P3 | `D`: thuộc tính giai đoạn bệnh |
| 79 | `GiaiDoanVaoVien` | Giai đoạn bệnh lúc vào viện | P2 | `D`: chẩn đoán/thuộc tính giai đoạn bệnh |
| 80 | `TaiBienDoPhauThau` | Cờ tai biến phẫu thuật; toàn 0 | X | Hiện tại loại bỏ; tên có thể là lỗi chính tả của phẫu thuật |
| 81 | `TaiBienDoGayMe` | Cờ tai biến gây mê; toàn 0 | X | Hiện tại loại bỏ |
| 82 | `TaiBienDoNhiemKhuan` | Cờ tai biến nhiễm khuẩn; toàn 0 | X | Hiện tại loại bỏ |
| 83 | `TaiBienKhac` | Cờ tai biến khác; toàn 0 | X | Hiện tại loại bỏ |
| 84 | `TRaVien` | T lúc ra viện; toàn `NULL` | X | Hiện tại loại bỏ |
| 85 | `NRaVien` | N lúc ra viện; toàn `NULL` | X | Hiện tại loại bỏ |
| 86 | `MRaVien` | M lúc ra viện; toàn `NULL` | X | Hiện tại loại bỏ |
| 87 | `GiaDoanRaVien` | Giai đoạn lúc ra viện; toàn `NULL` | X | Hiện tại loại bỏ |
| 88 | `ChanDoanTruocPhauThuat` | Chẩn đoán trước phẫu thuật | P1 | `D`: `loại chẩn đoán=trước phẫu thuật` |
| 89 | `ChanDoanSauPhauThuat` | Chẩn đoán sau phẫu thuật | P1 | `D`: `loại chẩn đoán=sau phẫu thuật`; làm lộ thông tin tương lai tùy mốc thời gian giới hạn |
| 90 | `KhamBenhBenhChinh` | Bệnh/chẩn đoán chính khi khám | P1 | `D`: chẩn đoán văn bản; đồng thời giữ trong phần nhận định trong ghi chú |
| 91 | `TKhamBenh` | T khi khám, rất thưa | P3 | `D`: thuộc tính giai đoạn bệnh sau bảng giải mã |
| 92 | `NKhamBenh` | N khi khám, rất thưa | P3 | `D`: thuộc tính giai đoạn bệnh |
| 93 | `MKhamBenh` | M khi khám, rất thưa | P3 | `D`: thuộc tính giai đoạn bệnh |
| 94 | `GiaiDoanKhamBenh` | Giai đoạn tại khám, rất thưa | P3 | `D`: thuộc tính giai đoạn bệnh |
| 95 | `KhamBenhBenhKemTheo` | Bệnh kèm theo | P1 | `D`: `loại chẩn đoán=bệnh kèm theo` |
| 96 | `KhamBenhPhanBiet` | Chẩn đoán phân biệt | P2 | `D`: `loại chẩn đoán=chẩn đoán phân biệt` |
| 97 | `TongSoNgayDieuTriSauPhauThuat` | Tổng ngày điều trị sau mổ | P2 | `C`: kết quả điều trị/mức sử dụng nguồn lực; không thuộc Thủ thuật |
| 98 | `TongSoLanPhauThuat` | Tổng số lần phẫu thuật | P2 | `C`: số lượng được tính lại; ưu tiên đếm từ các sự kiện thủ thuật |
| 99 | `HinhVeHoacAnh` | Trường tham chiếu hình/ảnh trong biểu mẫu; phần lớn là giá trị giữ chỗ | P3 | `L/C`: không dùng thay cho bộ dữ liệu ảnh thật |
| 100 | `MoTaTonThuong` | Mô tả tổn thương, phần lớn giá trị giữ chỗ/rỗng | P2 | `N`: dùng khi có văn bản có nội dung |
| 101 | `LoiDanThayThuoc` | Lời dặn của thầy thuốc | P1 | `N`: kế hoạch hoặc lời dặn khi ra viện; chỉ dùng nếu có trước mốc truy vấn |
| 102 | `PPDT` | Phương pháp điều trị dạng văn bản ghi chú | P1 | `N`; rút ra `M`/`P` nếu cần |
| 103 | `BenhNganNgay` | Trường hành chính/ghi chú ngắn ngày, nghĩa không ổn định | P3 | Mặc định loại bỏ; cần bảng giải mã |
| 104 | `GhiChu` | Ghi chú lượt khám, gần như toàn `NULL` | P2 | `N`: chỉ dùng vài giá trị văn bản có nội dung |
| 105 | `DinhChiThaiNghen` | Cờ đình chỉ thai nghén | P2 | `P/C`: chỉ có ý nghĩa với nhóm bệnh nhân sản khoa; đây là dữ liệu nhạy cảm |
| 106 | `TuoiThai` | Tuổi thai; hiện toàn 0 | X | Hiện tại loại bỏ |
| 107 | `ChapHanhNoiQuy` | Đánh giá tuân thủ nội quy | X | Không phải đặc trưng phục vụ so sánh ca bệnh |
| 108 | `ThoiGianDinhChi` | Thời gian đình chỉ thai; toàn `NULL` | X | Hiện tại loại bỏ |
| 109 | `NguyenNhanDinhChi` | Nguyên nhân đình chỉ; toàn `NULL` | X | Hiện tại loại bỏ |
| 110 | `ChieuCao` | Chiều cao; toàn `NULL` trong trang tính này | X | Loại bỏ; không điền giá trị ước đoán không có căn cứ |
| 111 | `LanhDaoKhoa_Id` | mã lãnh đạo khoa; toàn `NULL` | X | Loại bỏ/thông tin định danh nhân viên y tế |
| 112 | `ThuTruongDonVi_Id` | mã thủ trưởng đơn vị; toàn `NULL` | X | Loại bỏ |
| 113 | `TenFileNew` | Tên tệp mới; toàn `NULL` | X | Loại bỏ; không dùng để nối PDF |
| 114 | `PathFileNew` | Đường dẫn tệp mới; toàn `NULL` | X | Loại bỏ |

## 4. Trang tính `chỉ định DVKT` — 151.248 dòng, 18 cột

Mỗi dòng là một chi tiết chỉ định dịch vụ kỹ thuật. Đây là nguồn chính để tạo
`Thủ thuật` dạng chỉ định và nối KQCLS/phẫu thuật về lượt khám.

| # | Trường | Giải thích | Mức | Đích/quyết định |
|---:|---|---|:---:|---|
| 1 | `TiepNhan_Id` | Mã tiếp nhận, có 3.500 giá trị khác nhau | P0 | `L`: chỉ dùng để liên kết lần tiếp nhận; không dùng làm đặc trưng lâm sàng |
| 2 | `SoBenhAn` | Khóa lượt khám | P0 | `L`: bắt buộc |
| 3 | `TenBenhNhan` | Tên bệnh nhân | X | Thông tin định danh trực tiếp; chỉ dùng kiểm tra liên kết có kiểm soát |
| 4 | `SoVaoVien` | Số vào viện | P0 | `L`: khóa phụ để liên kết với dữ liệu DICOM |
| 5 | `SoPhieuYeuCau` | Số phiếu yêu cầu/chỉ định gom nhóm | P0 | `L/P`: gom nhóm các chi tiết cùng phiếu |
| 6 | `NamSinh` | Năm sinh | P2 | `C`: dùng để tính tuổi tại lượt khám; không đưa trực tiếp năm sinh vào mô hình |
| 7 | `GioiTinh` | Giới tính được ghi bằng mã `T/G` | P2 | `C`: chỉ dùng sau khi có bảng giải thích hai mã này |
| 8 | `CLSYeuCau_Id` | Mã yêu cầu cận lâm sàng | P0 | `L/P`: dùng để gom các chi tiết thuộc cùng một chỉ định |
| 9 | `YeuCauChiTiet_Id` | mã chi tiết chỉ định, không trùng theo dòng | P0 | `L/P`: `mã sự kiện thủ thuật`; nối KQCLS/phẫu thuật/DICOM |
| 10 | `TenDichVu` | Tên dịch vụ kỹ thuật được chỉ định | P1 | `P`: `tên dịch vụ`; chuẩn hóa cách gọi khác/nhóm |
| 11 | `NgayYeuCau` | Thời điểm yêu cầu | P1 | `P`: `thời điểm yêu cầu`; dùng mốc thời gian giới hạn |
| 12 | `ChanDoan` | Chẩn đoán/nhận định lâm sàng đi kèm chỉ định | P1 | `D`: chẩn đoán đi kèm chỉ định; loại các bản lặp trong cùng lượt khám |
| 13 | `TenPhongBan` (1) | Khoa/phòng thứ nhất trong tệp xuất, khả năng nơi chỉ định | P2 | `C/P`: nơi gửi yêu cầu; cần xác minh tên gốc |
| 14 | `TenPhongBan` (2) | Khoa/phòng thứ hai, khả năng nơi thực hiện | P2 | `C/P`: nơi thực hiện; không gộp mù với cột 13 |
| 15 | `GhiChu` | Ghi chú chỉ định | P2 | `N/P`: thuộc tính ghi chú; phần lớn `NULL` |
| 16 | `loaimau` | Loại mẫu bệnh phẩm | P1 | `O/P`: loại mẫu bệnh phẩm cho dịch vụ xét nghiệm |
| 17 | `ViTriMau` | Vị trí lấy mẫu | P2 | `O/P`: vị trí lấy mẫu bệnh phẩm; phần lớn giá trị giữ chỗ |
| 18 | `KichThuocBuou` | Kích thước bướu; toàn rỗng/`NULL` trong tệp xuất | X | Hiện tại loại bỏ |

## 5. Trang tính `Thuốc` — 219.167 dòng, 36 cột

Mỗi dòng chủ yếu là một thuốc trong toa. Đây là nguồn chính cho `Thuốc`.
Không dùng tên/địa chỉ/bảo hiểm làm đặc trưng.

| # | Trường | Giải thích | Mức | Đích/quyết định |
|---:|---|---|:---:|---|
| 1 | `mayte` | Mã y tế/mã bệnh nhân hoặc mã lượt tiếp nhận | P0 | `L`: chỉ dùng để liên kết; không dùng làm đặc trưng |
| 2 | `TenBenhNhan` | Tên bệnh nhân | X | Thông tin định danh trực tiếp; loại bỏ |
| 3 | `sobenhan` | Khóa lượt khám | P0 | `L`: chuẩn hóa tên thành `SoBenhAn` |
| 4 | `SoThuTuToa` | Trường số thứ tự/toa nhưng chỉ có 2 giá trị trong tệp xuất | P3 | `L`: không đủ để làm mã toa thuốc; cần biết rõ ý nghĩa hoặc dùng khóa ghép |
| 5 | `TenDoiTuong` | Nhóm quyền lợi/đối tượng BHYT | X | Thông tin hành chính về bảo hiểm; loại bỏ |
| 6 | `Tuoi` | Tuổi dạng văn bản | P2 | `C`: nhân khẩu học; kiểm tra với năm sinh/ngày lượt khám |
| 7 | `GioiTinh` | Giới tính | P2 | `C`: nhân khẩu học; loại các bản lặp ở lượt khám |
| 8 | `DiaChi` | Địa chỉ | X | Thông tin định danh trực tiếp hoặc gián tiếp; loại bỏ |
| 9 | `thoihan_the` | Thời hạn thẻ bảo hiểm | X | Thông tin hành chính/định danh; loại bỏ |
| 10 | `ChanDoanKhoaKham` | Chẩn đoán tại khoa khám, lặp trên dòng thuốc | P1 | `D`: loại các bản lặp thành lượt khám/toa thuốc chẩn đoán |
| 11 | `strSLSang` | Liều/số lượng buổi sáng | P1 | `M`: chuyển thành số thành phần liều |
| 12 | `strSLTrua` | Liều/số lượng buổi trưa | P1 | `M` |
| 13 | `strSLChieu` | Liều/số lượng buổi chiều | P1 | `M` |
| 14 | `strSLToi` | Liều/số lượng buổi tối | P1 | `M` |
| 15 | `GhiChu` | Ghi chú thuốc | P2 | `M/N`: ghi chú dùng thuốc |
| 16 | `DuongDung` | Đường dùng | P1 | `M`: chuẩn hóa danh mục đường dùng |
| 17 | `TenDuoc` | Tên dược phẩm/biệt dược | P1 | `M`: `tên thuốc` |
| 18 | `TieuDe` | Tiêu đề; toàn `NULL` | X | Loại bỏ |
| 19 | `DonViTinh` | Đơn vị tính | P1 | `M`: chuẩn hóa đơn vị |
| 20 | `SoNgay` | Số ngày dùng | P1 | `M`: `số ngày dùng` |
| 21 | `SoLuongTong` | Tổng số lượng cấp | P1 | `M`: chuyển về dạng số |
| 22 | `LoiDan` | Lời dặn/cách dùng | P1 | `M/N`: lời dặn; tách tần suất và thời điểm so với bữa ăn nếu có |
| 23 | `NgayKham` | Thời điểm khám/kê toa | P1 | `M`: thời điểm kê đơn/mốc thời gian giới hạn |
| 24 | `TenHoatChat` | Tên hoạt chất | P1 | `M`: hoạt chất chuẩn hóa; ưu tiên hơn biệt dược khi gom nhóm |
| 25 | `HuyetAp` | Huyết áp ghi cùng toa | P2 | `O`: tách huyết áp tâm thu/tâm trương; loại các bản lặp khỏi trang tính chính |
| 26 | `Mach` | Mạch | P2 | `O`: dấu hiệu sinh tồn |
| 27 | `NhietDo` | Nhiệt độ | P2 | `O`: dấu hiệu sinh tồn |
| 28 | `CanNang` | Cân nặng | P2 | `O`: dấu hiệu sinh tồn |
| 29 | `SoBHYT` | Số bảo hiểm y tế | X | Thông tin định danh trực tiếp; loại bỏ |
| 30 | `BacSi` | Tên/mã bác sĩ | X | Thông tin định danh nhân viên y tế; loại khỏi đặc trưng |
| 31 | `LyDoTraThuoc` | Lý do trả thuốc; chỉ có `(Ra Viện)` ở 1.367 dòng | P2 | `M/C`: dùng để đánh dấu thuốc đã trả hoặc hủy; không coi là thuốc đã dùng |
| 32 | `DienGiai` | Diễn giải hành chính thanh toán, rất thưa | X | Loại bỏ |
| 33 | `STT` | Cờ/số thứ tự 0/1, nghĩa chưa rõ | P3 | Mặc định loại bỏ; cần bảng giải mã |
| 34 | `NguoiLienHe` | Người liên hệ | X | Thông tin định danh trực tiếp; loại bỏ |
| 35 | `CachGiaiQuyet` | Hằng số `Chỉ định dùng thuốc` | X | Loại bỏ |
| 36 | `HamLuong` | Tên cột sai lệch; toàn giá trị `NGƯỜI NHẬN THUỐC` | X | Lỗi do quá trình xuất dữ liệu; không phải hàm lượng, nên loại bỏ |

Lưu ý: tệp Excel hiện **không có một trường hàm lượng đáng tin cậy**. Không suy
diễn hàm lượng thuốc từ `HamLuong`; chỉ dùng lịch liều, đơn vị, số ngày, tổng số
lượng và văn bản `LoiDan` cho đến khi có nguồn hàm lượng thật.

## 6. Trang tính `KQCLS` — 312.251 dòng, 18 cột

Mỗi dòng là một chỉ số/kết quả cận lâm sàng hoặc một phần của báo cáo. Trang tính
này nên sinh `Quan sát` và `Báo cáo cận lâm sàng`, không ép toàn bộ vào
Chẩn đoán/Thủ thuật.

| # | Trường | Giải thích | Mức | Đích/quyết định |
|---:|---|---|:---:|---|
| 1 | `SoBenhAn` | Khóa lượt khám | P0 | `L` |
| 2 | `SoPhieuYeuCau` | Số phiếu yêu cầu | P0 | `L/P`: gom các kết quả theo cùng một chỉ định |
| 3 | `TenPhongBan` | Phòng thực hiện/đọc kết quả | P2 | `C/P`: địa điểm |
| 4 | `noi_gui_mau` | Nơi gửi mẫu | P2 | `C/O`: nguồn gốc dữ liệu |
| 5 | `YeuCauChiTiet_Id` | mã chi tiết chỉ định | P0 | `L`: nối `chỉ định DVKT` |
| 6 | `ChanDoan` | Chẩn đoán đi kèm yêu cầu | P1 | `D`: loại các bản lặp; không coi mỗi chỉ số là chẩn đoán mới |
| 7 | `MA_DICH_VU` | Mã dịch vụ xét nghiệm/cận lâm sàng | P1 | `P/O`: `mã dịch vụ`/mã nhóm xét nghiệm |
| 8 | `TEN_CHI_SO` | Tên chỉ số xét nghiệm hoặc mục báo cáo | P1 | `O`: `tên chỉ số quan sát` |
| 9 | `GIA_TRI` | Giá trị kết quả | P1 | `O`: chuyển thành số, giá trị phân loại hoặc văn bản tùy loại xét nghiệm |
| 10 | `khoang_tham_chieu` | Khoảng tham chiếu | P1 | `O`: tách cận dưới, cận trên hoặc giữ khoảng dạng chữ |
| 11 | `DON_VI_DO` | Đơn vị đo | P1 | `O`: chuẩn hóa đơn vị |
| 12 | `MO_TA` | Phần mô tả cận lâm sàng | P1 | `N`: đưa vào phần mô tả của báo cáo; đây là trường gần ghi chú lâm sàng nhất |
| 13 | `KET_LUAN` | Phần kết luận | P1 | `N/D`: đưa vào phần kết luận của báo cáo; chỉ trích chẩn đoán bằng quy tắc có kiểm soát |
| 14 | `NGAY_KQ` | Thời điểm có kết quả | P1 | `O/N`: thời điểm sự kiện/mốc thời gian giới hạn |
| 15 | `MA_BS_DOC_KQ` | Mã bác sĩ đọc kết quả | X | Thông tin định danh nhân viên y tế; chỉ giữ riêng để truy vết khi thật sự cần, không làm đặc trưng |
| 16 | `LoaiMau` | Loại mẫu | P1 | `O`: loại mẫu bệnh phẩm |
| 17 | `chat_luong_mau` | Chất lượng mẫu; toàn `Đạt` | X | Hiện tại loại bỏ vì hằng số |
| 18 | `DU_PHONG` | Cột dự phòng; rỗng toàn bộ | X | Loại bỏ |

Nếu bắt buộc quy về ba bảng lõi: tạo một `Thủ thuật` cho dịch vụ/nhóm xét nghiệm bằng
`MA_DICH_VU + YeuCauChiTiet_Id`, rồi treo nhiều `Quan sát` con lên
thủ thuật/dịch vụ đó. Không biến từng `GIA_TRI` thành Thủ thuật hay Chẩn đoán.

## 7. Trang tính `Phẫu thuật thủ thuật` — 11.342 dòng, 23 cột

Đây là nguồn giàu nhất cho thủ thuật/dịch vụ đã thực hiện và biên bản phẫu thuật/thủ thuật. Lượt khám
được kế thừa qua `YeuCauChiTiet_Id → chỉ định DVKT → SoBenhAn`.

| # | Trường | Giải thích | Mức | Đích/quyết định |
|---:|---|---|:---:|---|
| 1 | `ma_lk` | Mã liên kết nhưng toàn `NULL` | X | Hiện tại loại bỏ |
| 2 | `TenDichVu` | Tên dịch vụ theo nguồn chỉ định | P1 | `P`: tên thủ thuật/dịch vụ |
| 3 | `YeuCauChiTiet_Id` | mã chi tiết chỉ định, không trùng theo dòng | P0 | `L/P`: nối lượt khám và làm mã sự kiện nguồn |
| 4 | `ten_benh_nhan` | Tên bệnh nhân | X | Thông tin định danh trực tiếp; loại bỏ |
| 5 | `NamSinh` | Năm sinh | P2 | `C`: nhân khẩu học; không lặp vào đặc trưng thủ thuật nếu đã có bối cảnh của lượt khám |
| 6 | `GioiTinh` | Giới tính | P2 | `C`: nhân khẩu học |
| 7 | `noi_thuc_hien` | Nơi thực hiện | P2 | `P/C`: nơi thực hiện thủ thuật |
| 8 | `ICD_TruocPhauThuat_MoTa` | Mô tả chẩn đoán trước mổ | P1 | `D`: `loại chẩn đoán=trước phẫu thuật` |
| 9 | `ICD_SauPhauThuat_MoTa` | Mô tả chẩn đoán sau mổ | P1 | `D`: `loại chẩn đoán=sau phẫu thuật` |
| 10 | `ten_dich_vu` | Tên dịch vụ chi tiết/biến thể thứ hai | P1 | `P`: tên gọi khác/thông tin chi tiết; ưu tiên giá trị cụ thể hơn, không tạo hai sự kiện mù |
| 11 | `CanThiepPhauThuat` | Can thiệp được thực hiện | P1 | `P`: mô tả can thiệp cụ thể |
| 12 | `LoaiPhauThuat` | Loại/phân hạng PT-TT (`LDB`, `L1`, `L2`, `L3`, `KPL`) | P2 | `P`: nhóm; cần bảng giải mã |
| 13 | `pp_vocam` | Phương pháp vô cảm/gây mê | P1 | `P`: thuộc tính phương pháp vô cảm |
| 14 | `TrinhTuThucHien_Text` | Trình tự/kỹ thuật thực hiện dạng văn bản ghi chú | P1 | `P/N`: biên bản phẫu thuật/thủ thuật; đưa văn bản qua bộ mã hóa và gắn vào thủ thuật/dịch vụ |
| 15 | `DanLuu` | Thông tin dẫn lưu | P2 | `P`: thông tin về thiết bị hoặc dẫn lưu; chuẩn hóa các giá trị `không/0` |
| 16 | `ThoiGianBatDau` | Thời gian bắt đầu | P1 | `P`: thời điểm bắt đầu |
| 17 | `ThoiGianKetThuc` | Thời gian kết thúc | P1 | `P`: thời điểm kết thúc |
| 18 | `NgayCatChi` | Ngày cắt chỉ; toàn `NULL` | X | Hiện tại loại bỏ |
| 19 | `NgayRut` | Ngày rút dẫn lưu/chỉ; toàn `NULL` | X | Hiện tại loại bỏ |
| 20 | `ThoiGianTiepNhan` | Thời gian tiếp nhận thủ thuật/dịch vụ | P2 | `P`: thời điểm tiếp nhận |
| 21 | `KetQua` | Kết quả thủ thuật/phẫu thuật | P1 | `P/N/C`: kết quả thủ thuật; làm lộ thông tin tương lai tùy mốc thời gian giới hạn |
| 22 | `LoaiPT_TT` | Bản lặp chính xác phân hạng của `LoaiPhauThuat` | P2 | `P`: nếu hai cột luôn giống nhau thì chỉ giữ một cột |
| 23 | `nhom_chiphi` | Nhóm chi phí/dịch vụ (`THỦ THUẬT`, `PHẪU THUẬT`, PET/CT...) | P2 | `P/C`: khái quát nhóm thủ thuật/dịch vụ; không dùng chi phí |

## 8. Lựa chọn trường dữ liệu để dùng thực tế

### 8.1. Tập tối thiểu nên dùng ngay

**Khóa liên kết:**

- `SoBenhAn`, `SoVaoVien`, `BenhAn_Id`, `YeuCauChiTiet_Id`,
  `SoPhieuYeuCau`, `CLSYeuCau_Id`.

**Chẩn đoán:**

- `MaICD`, `ICD_phu`, `ChanDoanRaVien`, `KhamBenhBenhChinh`,
  `KhamBenhBenhKemTheo`, `KhamBenhPhanBiet`;
- các `ChanDoan` ở chỉ định/KQCLS, `ChanDoanKhoaKham`;
- `ChanDoanTruocPhauThuat`, `ChanDoanSauPhauThuat`,
  `ICD_TruocPhauThuat_MoTa`, `ICD_SauPhauThuat_MoTa`.

**Thuốc:**

- `TenDuoc`, `TenHoatChat`, `DuongDung`, bốn trường liều theo buổi,
  `DonViTinh`, `SoNgay`, `SoLuongTong`, `LoiDan`, `NgayKham`;
- `PPHoaChat` làm tóm tắt phác đồ bổ sung.

**Thủ thuật:**

- `YeuCauChiTiet_Id`, `TenDichVu`, `NgayYeuCau`;
- `ten_dich_vu`, `CanThiepPhauThuat`, `LoaiPhauThuat`/`LoaiPT_TT`,
  `pp_vocam`, `TrinhTuThucHien_Text`, `ThoiGianBatDau`,
  `ThoiGianKetThuc`, `KetQua`;
- `MA_DICH_VU` đại diện cho dịch vụ hoặc nhóm xét nghiệm đã được chỉ định.

**Không ép vào ba bảng nhưng vẫn quan trọng:**

- ghi chú lâm sàng: bệnh sử, khám, tóm tắt, diễn biến, kế hoạch;
- dấu hiệu sinh tồn: mạch, nhịp thở, nhiệt độ, cân nặng, huyết áp;
- xét nghiệm/báo cáo: `TEN_CHI_SO`, `GIA_TRI`, khoảng tham chiếu, đơn vị, `MO_TA`, `KET_LUAN`;
- thời gian/bối cảnh: nhập viện, ra viện, khoa/phòng và mẫu bệnh phẩm.

### 8.2. Loại bỏ ngay

- Thông tin định danh trực tiếp: tên bệnh nhân, địa chỉ, số BHYT, người liên hệ và bác sĩ.
- Cột rỗng hoặc hằng số: `DU_PHONG`, `TieuDe`, `ma_lk`, `NgayCatChi`, `NgayRut`,
  `ChieuCao` ở trang tính chính, `TenFileNew`, `PathFileNew`, `chat_luong_mau`,
  các cờ tai biến toàn 0.
- Thông tin hành chính hoặc lỗi xuất dữ liệu: số tờ hồ sơ, `CachGiaiQuyet`,
  `HamLuong` và các trường bảo hiểm/chi trả.

### 8.3. Chỉ dùng sau bảng giải mã

- `PhuongPhapDieuTri`, các trường liều `PPTienPhau*`, `PPDonThuan*`,
  `PPHauPhau*`, `PPSoDot`, `PPDapUng`;
- các TNM/giai đoạn rất thưa;
- `LoaiPhauThuat`/`LoaiPT_TT`, `STT`, `BenhNganNgay`.

## 9. Quy tắc chống làm lộ thông tin tương lai

- Nếu véc-tơ biểu diễn cho **toàn bộ lượt khám nhìn lại sau khi kết thúc**, có thể dùng
  chẩn đoán lúc ra viện, diễn biến, kết quả thủ thuật và toàn bộ PDF/báo cáo.
- Nếu véc-tơ biểu diễn tại **thời điểm nhập viện hoặc 24 giờ đầu**, loại mọi sự kiện sau mốc thời gian giới hạn và
  không dùng `ChanDoanRaVien`, `TinhTrangNguoiBenhRaVien`, kế hoạch sau ra viện,
  chẩn đoán sau mổ, kết quả sau mốc giới hạn hoặc phần PDF sinh sau mốc đó.
- Chẩn đoán lặp trên hàng nghìn chỉ định/thuốc phải loại các bản lặp theo
  `(mã lượt khám, nội dung hoặc mã chẩn đoán đã chuẩn hóa, loại chẩn đoán, nhóm thời gian)`.
- Một chỉ định thủ thuật/dịch vụ và thủ thuật/dịch vụ thực hiện không phải hai thủ thuật/dịch vụ độc lập:
  nối qua `YeuCauChiTiet_Id`, giữ trạng thái `đã chỉ định/đã thực hiện`.
- Một dòng thuốc không đồng nghĩa thuốc đã dùng; các dòng có
  `LyDoTraThuoc=(Ra Viện)` phải mang trạng thái đã trả/đã hủy.

## 10. Kết luận

Ba nhóm `Chẩn đoán – Thuốc – Thủ thuật` bao phủ phần lớn sự kiện lâm sàng
có cấu trúc, nhưng cách biểu diễn đầy đủ cho một lượt khám vẫn cần:

```
Lượt khám = Chẩn đoán + Thuốc + Thủ thuật + Ghi chú lâm sàng + Quan sát + Thời gian/bối cảnh
```

Với mạng nơ-ron đồ thị, nên tạo nút `VISIT` (lượt khám), rồi nối với các nút
`DIAGNOSIS` (chẩn đoán), `MEDICINE` (thuốc), `PROCEDURE` (thủ thuật),
`NOTE_SECTION` (một phần của ghi chú) và `OBSERVATION` (kết quả đo hoặc xét
nghiệm). Không nên ép mọi trường vào ba nhóm Chẩn đoán, Thuốc và Thủ thuật.

## 11. Ví dụ cho từng trường và lý do loại

Các ví dụ văn bản ghi chú bên dưới là **minh họa tổng hợp**, không phải nội dung
chép từ một bệnh nhân. Các mã nhận diện đã được che. Các mã phân loại và hằng số
được nêu là giá trị đã quan sát ở mức tổng hợp. `NULL 100%` nghĩa là không
có một giá trị hữu ích nào trong toàn bộ cột.

- Ví dụ về giá trị phân loại, thuốc, dịch vụ, chỉ số và kết luận ngắn được chọn từ các
  giá trị phổ biến đã quan sát ở mức tổng hợp.
- Ví dụ văn bản ghi chú dài là câu tổng hợp cụ thể, cùng loại nội dung với trường
  nhưng không chép nguyên ghi chú bệnh nhân.
- Ví dụ mã nhận diện, tên, địa chỉ, bảo hiểm và bác sĩ được thay bằng hai mã giả.
- Cột toàn rỗng hoặc hằng số chỉ có một ví dụ vì bộ dữ liệu thực sự không có giá
  trị thứ hai; tài liệu ghi cả mẫu số dòng để tránh hiểu nhầm.

### 11.1. `thông tin bệnh án`

| # | Trường | Một vài ví dụ an toàn | Giữ/bỏ và lý do |
|---:|---|---|---|
| 1 | `SoBenhAn` | `<luot_kham_000001>`; `<luot_kham_000002>` | Giữ làm khóa lượt khám; không đưa giá trị mã vào véc-tơ biểu diễn |
| 2 | `SoVaoVien` | `<vao_vien_0001>`; `<vao_vien_0002>` | Giữ để liên kết; có thể bị lặp nên không dùng một mình làm khóa lượt khám |
| 3 | `BenhAn_Id` | `<benh_an_001>`; `<benh_an_002>` | Giữ để nối PDF/báo cáo |
| 4 | `NgayVaoVien` | `2026-01-10 08:30`; `2026-01-11 14:00` | Giữ làm thời gian bắt đầu lượt khám |
| 5 | `NgayRaVien` | `2026-01-15 10:00`; `2026-01-20 09:15` | Giữ cho toàn bộ lượt khám; loại nếu thời điểm truy vấn xảy ra trước khi ra viện |
| 6 | `ChanDoanRaVien` | `Rối loạn tiền đình`; `Viêm dạ dày ruột`; `ung thư phổi giai đoạn IV` | Giữ trong Chẩn đoán cho toàn bộ lượt khám; làm lộ thông tin tương lai cho mô hình tại thời điểm nhập viện |
| 7 | `MaICD` | `I10`; `C50.9` | Giữ, chuẩn hóa ICD |
| 8 | `ICD_phu` | `E11.9`; `I10; E78.5` | Giữ; tách chuỗi thành nhiều mã chẩn đoán |
| 9 | `TenPhongBan` | `Khoa Nội`; `Khoa Ngoại` | Giữ làm bối cảnh khoa/phòng điều trị; chuẩn hóa tên khoa |
| 10 | `ketquadieutri` | `Đỡ`; `Khỏi`; `Không thay đổi`; `Nặng hơn` | Giữ làm kết quả điều trị; không dùng cho truy hồi ở thời điểm sớm |
| 11 | `BenhAnChiTiet_Id` | `<chi_tiet_001>`; `<chi_tiet_002>` | Giữ chỉ dùng để truy vết nguồn |
| 12 | `BenhAn_Id` (lặp) | `<benh_an_001>`; `<benh_an_002>` | Bỏ một bản sau khi xác minh bằng cột 3; cột lặp do quá trình xuất dữ liệu |
| 13 | `LyDoVaoVien` | `Đau bụng`; `Khó thở`; `Chóng mặt`; `Đau hông lưng trái` | Giữ trong ghi chú lâm sàng |
| 14 | `QuaTrinhBenhLy` | `đau bụng tăng dần trong 3 ngày`; `ho, sốt và khó thở 2 ngày`; `chóng mặt tái diễn một tuần` | Giữ, ghi chú dạng văn bản cốt lõi; đây là câu minh họa cụ thể đã loại định danh |
| 15 | `TienSuBanThan` | `tăng huyết áp`; `chưa ghi nhận bệnh nền` | Giữ trong tiền sử/bệnh sử; có thể rút ra chẩn đoán |
| 16 | `DiUng` | `0`; `1` | Giữ như cờ cho biết có dị ứng; không suy ra tác nhân |
| 17 | `NgayDiUng` | `NULL` (3.499 dòng); `0` (1 dòng) | Bỏ: không có thời gian dị ứng hợp lệ |
| 18 | `MaTuy` | `0`; `1` | Giữ như cờ về tiền sử xã hội |
| 19 | `NgayMaTuy` | `NULL` (3.499); `0` (1) | Bỏ: gần như rỗng và chưa rõ đơn vị |
| 20 | `RuouBia` | `0`; `1` | Giữ như cờ về tiền sử xã hội |
| 21 | `NgayRuouBia` | `NULL` (3.499); `0` (1) | Bỏ: không có giá trị định lượng đáng tin cậy |
| 22 | `ThuocLa` | `0`; `1` | Giữ như cờ hút thuốc |
| 23 | `NgayThuocLa` | `NULL`; `20`; `360` | Chỉ dùng sau bảng giải mã; không rõ ngày, năm hay số lượng |
| 24 | `ThuocLao` | `0`; `1` | Giữ như cờ về tiền sử xã hội |
| 25 | `NgayThuocLao` | `NULL`; `60` | Chỉ dùng sau bảng giải mã; rất thưa |
| 26 | `TienSuKhac` | `0`; `1` | Giữ như cờ nếu cần |
| 27 | `NgayTienSuKhac` | `NULL` (3.499); `0` (1) | Bỏ: không có thông tin thời gian hữu ích |
| 28 | `TienSuGiaDinh` | `Chưa ghi nhận bất thường`; `Khỏe mạnh`; `chưa ghi nhận bệnh lý liên quan` | Giữ trong phần tiền sử gia đình |
| 29 | `KhamBenhToanThan` | `tỉnh, tiếp xúc tốt`; `da niêm hồng, không sốt`; `thể trạng trung bình, không phù` | Giữ trong ghi chú khám bệnh |
| 30 | `Mach` | `72`; `95` lần/phút | Giữ dưới dạng giá trị đo dạng số |
| 31 | `NhipTho` | `18`; `22` lần/phút | Giữ |
| 32 | `NhietDo` | `36.8`; `38.2` °C | Giữ; chuyển đổi và kiểm tra khoảng hợp lệ |
| 33 | `CanNang` | `55`; `70` kg | Giữ; chuyển thành số |
| 34 | `HuyetApCao` | `120`; `140` mmHg | Giữ làm huyết áp tâm thu |
| 35 | `HuyetApThap` | `70`; `90` mmHg | Giữ làm huyết áp tâm trương |
| 36 | `KhamBenhBoPhanTonThuong` | `rung thận (-), chạm thận (-)`; `sẹo mổ liền tốt, không u cục`; `tự tiểu vàng, không gắt buốt` | Giữ trong khám tại vùng tổn thương |
| 37 | `ThanKinh` | `không yếu liệt`; `cổ mềm, không dấu thần kinh định vị`; `không có dấu thần kinh khu trú` | Giữ trong khám theo hệ cơ quan |
| 38 | `TuanHoan` | `tim đều, T1 T2 rõ`; `không âm thổi bệnh lý`; `chưa ghi nhận bất thường` | Giữ |
| 39 | `HoHap` | `phổi êm, không ran`; `không ho, không khó thở`; `phổi thông khí đều` | Giữ |
| 40 | `TieuHoa` | `bụng mềm, ấn không đau`; `không điểm đau khu trú`; `phản ứng thành bụng (-)` | Giữ |
| 41 | `CoXuongKhop` | `chưa ghi nhận bất thường`; `vận động bình thường`; `chưa phát hiện bệnh lý` | Giữ |
| 42 | `TietNieu` | `chưa ghi nhận bất thường`; `cầu bàng quang (-)`; `tự tiểu bình thường` | Giữ |
| 43 | `SinhDuc` | `chưa ghi nhận bất thường`; `chưa phát hiện bệnh lý`; `không ghi nhận tổn thương` | Chỉ giữ nếu phù hợp với nhóm bệnh nhân đang nghiên cứu; cần bảo vệ dữ liệu nhạy cảm |
| 44 | `KhamBenhKhac` | `chưa ghi nhận bất thường`; `chưa phát hiện bệnh lý`; `không ghi nhận tổn thương` | Giữ văn bản có ý nghĩa; bỏ giá trị giữ chỗ |
| 45 | `XetNghiemCLSCanLam` | `Hoàn thành các xét nghiệm thường quy`; `Xét nghiệm tiền phẫu`; `công thức máu và điện giải đồ` | Giữ như kế hoạch/chỉ định văn bản; có thể rút ra Thủ thuật |
| 46 | `TomTatBenhAn` | `đau bụng 3 ngày, khám bụng mềm, đã chỉ định xét nghiệm`; `khó thở, phổi có ran, theo dõi viêm phổi`; `chóng mặt tái diễn, sinh hiệu ổn` | Giữ; loại phần trùng hoàn toàn hoặc gần trùng với trường 14 và 49; ví dụ là câu tổng hợp |
| 47 | `KhamBenhTienLuong` | `Trung bình`; `Nặng`; `Vừa`; `Dè dặt` | Giữ làm tiên lượng; kiểm soát làm lộ thông tin tương lai |
| 48 | `HuongDanDieuTri` | `Nội khoa`; `đánh giá giai đoạn bệnh, hội chẩn điều trị`; `kháng sinh, giảm đau và dinh dưỡng` | Giữ trong kế hoạch; có thể rút ra Thuốc/Thủ thuật |
| 49 | `QuaTrinhBenhLyVaDienBienLamSang` | `ngày 1 còn sốt, ngày 2 giảm sốt sau điều trị`; `đau giảm dần, ăn uống khá hơn`; `sinh hiệu ổn định, chưa ghi nhận biến chứng` | Giữ cho toàn bộ lượt khám; loại phần sau mốc thời gian giới hạn ở mô hình dùng dữ liệu ở thời điểm sớm; ví dụ là câu tổng hợp |
| 50 | `XNMau` | `bạch cầu tăng nhẹ`; `hemoglobin giảm`; `công thức máu trong giới hạn` | Giữ văn bản có nội dung; ưu tiên KQCLS chi tiết |
| 51 | `XNTeBao` | `không thấy tế bào ác tính`; `tế bào viêm`; `mẫu không đủ đánh giá` | Giữ văn bản có nội dung; bỏ giá trị giữ chỗ |
| 52 | `XNBLGP` | `mô viêm mạn`; `tổn thương lành tính`; `carcinoma biệt hóa vừa` | Giữ văn bản có nội dung |
| 53 | `XNXQuang` | `X-quang ngực chưa thấy tổn thương`; `thâm nhiễm đáy phổi phải`; `không thấy gãy xương` | Giữ như tóm tắt kết quả chẩn đoán hình ảnh, không coi đây là tệp ảnh |
| 54 | `XNSieuAm` | `gan nhiễm mỡ độ I`; `chưa thấy bất thường ổ bụng`; `nang thận đơn giản` | Giữ văn bản có nội dung |
| 55 | `CacXNKhac` | `điện tim trong giới hạn`; `nội soi viêm dạ dày`; `chức năng hô hấp giảm nhẹ` | Giữ văn bản có nội dung |
| 56 | `PhuongPhapDieuTri` | `DTTC`; `DTTD` | Chỉ dùng sau bảng giải mã; mã chưa được giải nghĩa |
| 57 | `PPTienPhauTaiU` | `NULL`; `50.4`; `60` | Chỉ dùng sau bảng giải mã/đơn vị; đa số NULL |
| 58 | `PPTienPhauTaiHach` | `NULL`; `45`; `60` | Chỉ dùng sau bảng giải mã/đơn vị |
| 59 | `PPDonThuanTaiU` | `NULL`; `42.56`; `30` | Chỉ dùng sau bảng giải mã/đơn vị |
| 60 | `PPDonThuanTaiHach` | `NULL`; `42.56`; `30` | Chỉ dùng sau bảng giải mã/đơn vị |
| 61 | `PPPhauThuat` | `thay khớp háng toàn phần`; `nội soi tái tạo dây chằng chéo trước`; `đoạn nhũ và nạo hạch` | Giữ văn bản có nội dung vào Thủ thuật; bỏ NULL |
| 62 | `PPHauPhauTaiU` | `NULL`; `42.56`; `50.4` | Chỉ dùng sau bảng giải mã/đơn vị |
| 63 | `PPHauPhauTaiHach` | `NULL`; `42.56`; `30` | Chỉ dùng sau bảng giải mã/đơn vị |
| 64 | `PPHoaChat` | `CAPOX`; `Oxaliplatin + Capecitabine`; `Carboplatin + Pemetrexed, chu kỳ 21 ngày` | Giữ và tách các thuốc trong phác đồ |
| 65 | `PPSoDot` | `NULL`; `4`; `9`; `28` | Chỉ dùng sau xác minh định nghĩa đợt/chu kỳ |
| 66 | `PPDapUng` | `BP`; `HT`; `KDU` | Giữ làm kết quả điều trị sau bảng giải mã; không dùng cho truy hồi ở thời điểm sớm |
| 67 | `PPDieuTriKhac` | `vật lý trị liệu`; `điều trị triệu chứng` | Giữ văn bản; rút ra Thuốc/Thủ thuật nếu có |
| 68 | `TinhTrangNguoiBenhRaVien` | `Ổn định`; `sinh hiệu ổn định`; `hô hấp và huyết động ổn định` | Giữ kết quả điều trị cho toàn bộ lượt khám; làm lộ thông tin tương lai nếu thời điểm truy vấn sớm |
| 69 | `HuongDieuTriVaCheDoTiepTheo` | `Ra viện`; `ra viện uống thuốc theo toa`; `nghỉ ngơi và tái khám theo hẹn` | Giữ trong kế hoạch; làm lộ thông tin tương lai tùy mốc dữ liệu quan sát |
| 70 | `SoToXQuang` | `NULL/giá trị giữ chỗ`; `2` tờ | Bỏ: số trang hành chính, không phải kết quả X-quang |
| 71 | `SoToCTScanner` | `NULL/giá trị giữ chỗ`; `1` tờ | Bỏ: số trang |
| 72 | `SoToSieuAm` | `NULL/giá trị giữ chỗ`; `3` tờ | Bỏ: số trang |
| 73 | `SoToXetNghiem` | `NULL/giá trị giữ chỗ`; `10` tờ | Bỏ: số trang |
| 74 | `SoToKhac` | `NULL/giá trị giữ chỗ`; `4` tờ | Bỏ: hành chính |
| 75 | `SoToHoSo` | `NULL/giá trị giữ chỗ`; `30` tờ | Bỏ: hành chính |
| 76 | `TVaoVien` | `NULL`; `2B`; `3c` | Chỉ dùng sau chuẩn hóa TNM; 3/3.500 dòng khác NULL |
| 77 | `NVaoVien` | `NULL`; `1`; `3` | Chỉ dùng sau chuẩn hóa; cực thưa |
| 78 | `MVaoVien` | `NULL`; `0` | Chỉ dùng sau chuẩn hóa; cực thưa |
| 79 | `GiaiDoanVaoVien` | `NULL`; `IIIB` | Chỉ dùng sau bảng giải mã; chỉ một giá trị có nghĩa |
| 80 | `TaiBienDoPhauThau` | `0` ở 3.500/3.500 | Bỏ: tất cả giá trị đều giống nhau nên không giúp phân biệt các lượt khám |
| 81 | `TaiBienDoGayMe` | `0` ở 3.500/3.500 | Bỏ: hằng số |
| 82 | `TaiBienDoNhiemKhuan` | `0` ở 3.500/3.500 | Bỏ: hằng số |
| 83 | `TaiBienKhac` | `0` ở 3.500/3.500 | Bỏ: hằng số |
| 84 | `TRaVien` | `NULL` 100% | Bỏ: toàn NULL |
| 85 | `NRaVien` | `NULL` 100% | Bỏ: toàn NULL |
| 86 | `MRaVien` | `NULL` 100% | Bỏ: toàn NULL |
| 87 | `GiaDoanRaVien` | `NULL` 100% | Bỏ: toàn NULL |
| 88 | `ChanDoanTruocPhauThuat` | `thoái hóa khớp gối`; `sỏi niệu quản`; `u vú trái` | Giữ văn bản có nội dung vào Chẩn đoán |
| 89 | `ChanDoanSauPhauThuat` | `thoái hóa khớp gối sau nội soi`; `sỏi niệu quản đã can thiệp`; `u vú sau phẫu thuật` | Giữ cho toàn bộ lượt khám; làm lộ thông tin tương lai nếu mốc thời gian giới hạn trước mổ |
| 90 | `KhamBenhBenhChinh` | `Loãng xương`; `Thoái hóa khớp gối hai bên`; `Rối loạn tiền đình`; `Viêm dạ dày ruột` | Giữ vào Chẩn đoán/nhận định lâm sàng |
| 91 | `TKhamBenh` | `NULL`; `2b`; `3c` | Chỉ dùng sau chuẩn hóa giai đoạn TNM; rất thưa |
| 92 | `NKhamBenh` | `NULL`; `1`; `2` | Chỉ dùng sau bảng giải mã; rất thưa |
| 93 | `MKhamBenh` | `NULL`; `0`; `1` | Chỉ dùng sau bảng giải mã; rất thưa |
| 94 | `GiaiDoanKhamBenh` | `NULL`; `IIIA`; `IVC` | Chỉ dùng sau chuẩn hóa; rất thưa |
| 95 | `KhamBenhBenhKemTheo` | `Tăng huyết áp`; `Đái tháo đường típ 2`; `Trào ngược dạ dày thực quản` | Giữ thành chẩn đoán bệnh kèm theo; bỏ giá trị giữ chỗ |
| 96 | `KhamBenhPhanBiet` | `Đột quỵ não`; `Lao phổi`; `Viêm tụy cấp` | Giữ văn bản có nội dung và đánh dấu là chẩn đoán phân biệt |
| 97 | `TongSoNgayDieuTriSauPhauThuat` | `3`; `7`; `NULL/giá trị giữ chỗ` | Giữ bối cảnh/kết quả điều trị; ưu tiên tự tính từ mốc thời gian |
| 98 | `TongSoLanPhauThuat` | `0`; `1`; `2` | Giữ bối cảnh; ưu tiên đếm các sự kiện thủ thuật |
| 99 | `HinhVeHoacAnh` | `NULL`; `0`; `1`; `tên tham chiếu nội bộ` | Bỏ khỏi đặc trưng ảnh: không phải tệp ảnh hoặc đường dẫn đáng tin cậy |
| 100 | `MoTaTonThuong` | `vết mổ khô`; `khối kích thước khoảng 2 cm`; `không thấy tổn thương ngoài da` | Giữ văn bản có nội dung; phần lớn không có thông tin |
| 101 | `LoiDanThayThuoc` | `Uống thuốc theo toa`; `tái khám khi có bất thường`; `ra viện uống thuốc theo toa` | Giữ trong kế hoạch/lời dặn |
| 102 | `PPDT` | `Nội khoa`; `Điều trị triệu chứng`; `thuốc giảm đau, giảm nề`; `phẫu thuật và tập vật lý trị liệu` | Giữ ghi chú lâm sàng; rút ra Thuốc/Thủ thuật |
| 103 | `BenhNganNgay` | `NULL`; `175`; `GC29` | Bỏ mặc định: giá trị lẫn mã/văn bản, nghĩa không ổn định |
| 104 | `GhiChu` | `NULL`; `bệnh nhân không đồng ý phẫu thuật`; `bệnh nhân xin ra viện` | Giữ văn bản có nội dung nếu có; bỏ NULL |
| 105 | `DinhChiThaiNghen` | `0`; `1` | Chỉ giữ cho nhóm bệnh nhân sản khoa; nếu không thì bỏ vì không liên quan |
| 106 | `TuoiThai` | `0` ở 3.500/3.500 | Bỏ: hằng số/không có tuổi thai hữu ích |
| 107 | `ChapHanhNoiQuy` | `Tốt`; `Tốt.`; `Chấp hành tốt.` | Bỏ: hành chính, không phản ánh bệnh lý |
| 108 | `ThoiGianDinhChi` | `NULL` 100% | Bỏ: toàn NULL |
| 109 | `NguyenNhanDinhChi` | `NULL` 100% | Bỏ: toàn NULL |
| 110 | `ChieuCao` | `NULL` 100% | Bỏ: toàn NULL; không điền giá trị ước đoán không có căn cứ |
| 111 | `LanhDaoKhoa_Id` | `NULL` 100% | Bỏ: toàn rỗng và là mã nhân viên y tế/hành chính |
| 112 | `ThuTruongDonVi_Id` | `NULL` 100% | Bỏ: toàn NULL và là mã hành chính |
| 113 | `TenFileNew` | `NULL` 100% | Bỏ: toàn NULL; không dùng liên kết |
| 114 | `PathFileNew` | `NULL` 100% | Bỏ: toàn rỗng; không dùng để liên kết |

### 11.2. `chỉ định DVKT`

| # | Trường | Một vài ví dụ an toàn | Giữ/bỏ và lý do |
|---:|---|---|---|
| 1 | `TiepNhan_Id` | `<tiep_nhan_001>`; `<tiep_nhan_002>` | Giữ chỉ dùng để liên kết |
| 2 | `SoBenhAn` | `<luot_kham_000001>`; `<luot_kham_000002>` | Giữ làm khóa lượt khám |
| 3 | `TenBenhNhan` | `<TEN_BENH_NHAN_DA_CHE_001>`; `<TEN_BENH_NHAN_DA_CHE_002>` | Bỏ khỏi đặc trưng và tài liệu xuất ra: thông tin định danh trực tiếp |
| 4 | `SoVaoVien` | `<vao_vien_0001>`; `<vao_vien_0002>` | Giữ chỉ dùng để liên kết |
| 5 | `SoPhieuYeuCau` | `<phieu_yeu_cau_001>`; `<phieu_yeu_cau_002>` | Giữ để gom nhóm các chỉ định |
| 6 | `NamSinh` | `1950`; `1980` | Giữ để tính tuổi; không đưa trực tiếp năm sinh cùng mã nhận diện vào mô hình |
| 7 | `GioiTinh` | `T`; `G` | Giữ sau khi có bảng giải mã cho mã T/G |
| 8 | `CLSYeuCau_Id` | `<nhom_chi_dinh_001>`; `<nhom_chi_dinh_002>` | Giữ để liên kết và gom nhóm chỉ định |
| 9 | `YeuCauChiTiet_Id` | `<chi_tiet_chi_dinh_001>`; `<chi_tiet_chi_dinh_002>` | Giữ làm khóa dịch vụ và để liên kết các trang tính |
| 10 | `TenDichVu` | `Điện giải đồ (Na, K, Cl)`; `Tổng phân tích tế bào máu ngoại vi`; `Định lượng Creatinin`; `CT ngực` | Giữ vào Thủ thuật |
| 11 | `NgayYeuCau` | `2026-01-10 09:00`; `2026-01-11 08:15` | Giữ làm thời điểm yêu cầu |
| 12 | `ChanDoan` | `tăng huyết áp`; `viêm phổi`; `đái tháo đường típ 2`; `đau bụng chưa rõ nguyên nhân` | Giữ vào Chẩn đoán, loại các bản lặp |
| 13 | `TenPhongBan` (1) | `Khoa Nội`; `Khoa Ngoại` | Giữ bối cảnh; cần xác minh là khoa gửi hay khoa chỉ định |
| 14 | `TenPhongBan` (2) | `Khoa Xét nghiệm`; `Khoa Chẩn đoán hình ảnh` | Giữ bối cảnh; không gộp mù với cột 13 |
| 15 | `GhiChu` | `NULL`; `kiêng gà`; `mất máu cấp`; `xét nghiệm sau mổ` | Giữ văn bản có nội dung; phần lớn NULL |
| 16 | `loaimau` | `MÁU`; `ĐÀM`; `NƯỚC TIỂU` | Giữ loại mẫu bệnh phẩm; chuẩn hóa chữ hoa, chữ thường và dấu tiếng Việt |
| 17 | `ViTriMau` | `máu`; `đàm`; `giữa dòng`; `dịch màng phổi` | Giữ khi có giá trị thật; phần lớn giá trị giữ chỗ |
| 18 | `KichThuocBuou` | `NULL` hoặc rỗng ở 151.248/151.248 | Bỏ: không có giá trị hữu ích |

### 11.3. `Thuốc`

| # | Trường | Một vài ví dụ an toàn | Giữ/bỏ và lý do |
|---:|---|---|---|
| 1 | `mayte` | `<ma_y_te_001>`; `<ma_y_te_002>` | Giữ chỉ dùng để liên kết; có tính định danh |
| 2 | `TenBenhNhan` | `<TEN_BENH_NHAN_DA_CHE_001>`; `<TEN_BENH_NHAN_DA_CHE_002>` | Bỏ: thông tin định danh trực tiếp |
| 3 | `sobenhan` | `<luot_kham_000001>`; `<luot_kham_000002>` | Giữ và đổi về tên chuẩn `SoBenhAn` |
| 4 | `SoThuTuToa` | hai giá trị tệp xuất dạng `<gia_tri_toa_A>` và `<gia_tri_toa_B>` | Không dùng làm mã toa thuốc: chỉ có 2 giá trị trong 219.167 dòng |
| 5 | `TenDoiTuong` | `BHYT 80%`; `BHYT 100%` | Bỏ: thông tin bảo hiểm/chi trả có thể làm mô hình học thiên lệch |
| 6 | `Tuoi` | `45`; `70` | Giữ bối cảnh; kiểm tra với năm sinh và ngày lượt khám |
| 7 | `GioiTinh` | `Nam`; `Nữ` | Giữ bối cảnh nhân khẩu học |
| 8 | `DiaChi` | `<DIA_CHI_DA_CHE_001>`; `<DIA_CHI_DA_CHE_002>` | Bỏ: thông tin định danh trực tiếp hoặc gián tiếp |
| 9 | `thoihan_the` | `<han_bao_hiem_2026-01>`; `<han_bao_hiem_2026-06>` | Bỏ: bảo hiểm/hành chính |
| 10 | `ChanDoanKhoaKham` | `tăng huyết áp`; `đái tháo đường típ 2`; `viêm phổi`; `đau cột sống thắt lưng` | Giữ vào Chẩn đoán nhưng loại các bản lặp giữa các dòng thuốc |
| 11 | `strSLSang` | `1`; `0.5` | Giữ lịch dùng thuốc |
| 12 | `strSLTrua` | `1`; rỗng | Giữ; ô rỗng không có nghĩa là liều bằng 0 |
| 13 | `strSLChieu` | `1`; `2` | Giữ |
| 14 | `strSLToi` | `1`; `0.5` | Giữ |
| 15 | `GhiChu` | `sau ăn`; `uống`; `tiêm tĩnh mạch chậm`; `pha kháng sinh` | Giữ văn bản có nội dung; bỏ giá trị giữ chỗ |
| 16 | `DuongDung` | `Uống`; `Tiêm`; `Truyền tĩnh mạch` | Giữ và chuẩn hóa đường dùng |
| 17 | `TenDuoc` | `Natri clorid 0,9% 100 ml`; `Paratramol 37,5 mg + 325 mg`; `Amlodac 5 mg` | Giữ làm tên thuốc |
| 18 | `TieuDe` | `NULL` 100% | Bỏ: toàn NULL |
| 19 | `DonViTinh` | `viên`; `ống`; `ml` | Giữ và chuẩn hóa đơn vị |
| 20 | `SoNgay` | `3`; `5`; `7` | Giữ số ngày dùng |
| 21 | `SoLuongTong` | `10`; `20`; `30` | Giữ tổng số lượng |
| 22 | `LoiDan` | `uống sau ăn`; `dùng theo hướng dẫn` | Giữ hướng dẫn dùng thuốc |
| 23 | `NgayKham` | `2026-01-10 09:30`; `2026-01-12 08:00` | Giữ thời điểm kê đơn |
| 24 | `TenHoatChat` | `paracetamol`; `amoxicillin` | Giữ hoạt chất chuẩn hóa |
| 25 | `HuyetAp` | `120/80`; `140/90` | Giữ Quan sát, không thuộc Thuốc |
| 26 | `Mach` | `72`; `90` | Giữ Quan sát; loại các bản lặp |
| 27 | `NhietDo` | `36.8`; `38.0` | Giữ Quan sát |
| 28 | `CanNang` | `55`; `70` | Giữ Quan sát |
| 29 | `SoBHYT` | `<SO_BAO_HIEM_DA_CHE_001>`; `<SO_BAO_HIEM_DA_CHE_002>` | Bỏ: thông tin định danh trực tiếp |
| 30 | `BacSi` | `<NHAN_VIEN_Y_TE_DA_CHE_001>`; `<NHAN_VIEN_Y_TE_DA_CHE_002>` | Bỏ khỏi đặc trưng: thông tin định danh nhân viên y tế/sai lệch do cơ sở hoặc nhân viên y tế |
| 31 | `LyDoTraThuoc` | rỗng; `(Ra Viện)` | Giữ làm trạng thái cấp/dùng thuốc; không coi thuốc trả là đã dùng |
| 32 | `DienGiai` | rỗng; `Đơn không có giá trị thanh toán BHYT` | Bỏ: hành chính và chỉ 585 dòng |
| 33 | `STT` | `0`; `1` | Bỏ mặc định: chưa biết ý nghĩa của hai mã 0 và 1 |
| 34 | `NguoiLienHe` | `<NGUOI_LIEN_HE_DA_CHE_001>`; `<NGUOI_LIEN_HE_DA_CHE_002>` | Bỏ: thông tin định danh trực tiếp |
| 35 | `CachGiaiQuyet` | `Chỉ định dùng thuốc` ở 219.167/219.167 | Bỏ: tất cả giá trị đều giống nhau nên không giúp phân biệt lượt khám |
| 36 | `HamLuong` | `NGƯỜI NHẬN THUỐC` ở 219.167/219.167 | Bỏ: lỗi do quá trình xuất dữ liệu, không phải hàm lượng |

### 11.4. `KQCLS`

| # | Trường | Một vài ví dụ an toàn | Giữ/bỏ và lý do |
|---:|---|---|---|
| 1 | `SoBenhAn` | `<luot_kham_000001>`; `<luot_kham_000002>` | Giữ để liên kết lượt khám |
| 2 | `SoPhieuYeuCau` | `<phieu_yeu_cau_001>`; `<phieu_yeu_cau_002>` | Giữ để gom nhóm báo cáo/kết quả |
| 3 | `TenPhongBan` | `Khoa Xét nghiệm`; `Khoa Chẩn đoán hình ảnh` | Giữ nguồn gốc dữ liệu/bối cảnh |
| 4 | `noi_gui_mau` | `Khoa Nội`; `Khoa Ngoại` | Giữ nguồn bối cảnh |
| 5 | `YeuCauChiTiet_Id` | `<chi_tiet_chi_dinh_001>`; `<chi_tiet_chi_dinh_002>` | Giữ để nối với chỉ định tương ứng |
| 6 | `ChanDoan` | `tăng huyết áp`; `viêm phổi`; `đái tháo đường`; `theo dõi nhiễm trùng` | Giữ Chẩn đoán, loại các bản lặp |
| 7 | `MA_DICH_VU` | `<MA_XET_NGHIEM_001>`; `<MA_CHAN_DOAN_HINH_ANH_002>`; `<MA_DIEN_TIM_003>` | Giữ làm mã dịch vụ; mã thật chỉ được dùng trong tầng xử lý dữ liệu bảo mật |
| 8 | `TEN_CHI_SO` | `HCT`; `Na`; `Kali`; `Clo`; `WBC` | Giữ tên chỉ số quan sát |
| 9 | `GIA_TRI` | `0.0`; `0.1`; `NEGATIVE`; `5.2`; `Âm tính` | Giữ; chuyển thành số, giá trị phân loại hoặc văn bản |
| 10 | `khoang_tham_chieu` | `3.5–5.5`; `<10` | Giữ làm khoảng tham chiếu |
| 11 | `DON_VI_DO` | `g/L`; `mmol/L`; `%` | Giữ và chuẩn hóa đơn vị |
| 12 | `MO_TA` | `Hồng cầu xen lẫn lympho bào`; `chỉ thấy chất dịch`; `mô hoại tử xen tế bào viêm cấp`; `RichEditControl1` | Giữ văn bản có nội dung vào phần mô tả báo cáo; loại `RichEditControl1` vì đây là lỗi của biểu mẫu xuất dữ liệu |
| 13 | `KET_LUAN` | `Điện tim trong giới hạn bình thường`; `X-quang ngực thẳng trong giới hạn bình thường`; `Gan nhiễm mỡ độ I` | Giữ vào phần kết luận trong báo cáo; không tự coi toàn bộ là chẩn đoán |
| 14 | `NGAY_KQ` | `2026-01-10 12:00`; `2026-01-11 15:30` | Giữ thời điểm sự kiện/mốc thời gian giới hạn |
| 15 | `MA_BS_DOC_KQ` | `<NHAN_VIEN_Y_TE_DA_CHE_001>`; `<NHAN_VIEN_Y_TE_DA_CHE_002>` | Bỏ khỏi đặc trưng: thông tin định danh nhân viên y tế |
| 16 | `LoaiMau` | `Máu toàn phần`; `Nước tiểu`; `Đàm` | Giữ loại mẫu bệnh phẩm |
| 17 | `chat_luong_mau` | `Đạt` ở 312.251/312.251 | Bỏ: tất cả giá trị đều giống nhau nên không giúp phân biệt lượt khám |
| 18 | `DU_PHONG` | rỗng/NULL 312.251/312.251 | Bỏ: toàn rỗng |

### 11.5. `Phẫu thuật thủ thuật`

| # | Trường | Một vài ví dụ an toàn | Giữ/bỏ và lý do |
|---:|---|---|---|
| 1 | `ma_lk` | `NULL` ở 11.342/11.342 | Bỏ: toàn NULL |
| 2 | `TenDichVu` | `Xạ trị bằng máy gia tốc`; `Khí dung đường thở`; `Thông khí nhân tạo không xâm nhập`; `Lấy máu toàn phần` | Giữ tên dịch vụ |
| 3 | `YeuCauChiTiet_Id` | `<chi_tiet_chi_dinh_001>`; `<chi_tiet_chi_dinh_002>` | Giữ để nối lượt khám với chỉ định |
| 4 | `ten_benh_nhan` | `<TEN_BENH_NHAN_DA_CHE_001>`; `<TEN_BENH_NHAN_DA_CHE_002>` | Bỏ: thông tin định danh trực tiếp |
| 5 | `NamSinh` | `1950`; `1980` | Giữ để tính tuổi; không dùng làm đặc trưng riêng của thủ thuật |
| 6 | `GioiTinh` | `Nam`; `Nữ` | Giữ bối cảnh; loại các bản lặp tại lượt khám |
| 7 | `noi_thuc_hien` | `Phòng mổ`; `Khoa thủ thuật` | Giữ nơi thực hiện thủ thuật |
| 8 | `ICD_TruocPhauThuat_MoTa` | `thoái hóa khớp gối`; `sỏi niệu quản`; `u vú trái` | Giữ và đánh dấu là chẩn đoán trước phẫu thuật |
| 9 | `ICD_SauPhauThuat_MoTa` | `thoái hóa khớp gối sau nội soi`; `sỏi niệu quản đã can thiệp`; `u vú sau phẫu thuật` | Giữ cho toàn bộ lượt khám; làm lộ thông tin tương lai nếu mốc thời gian sớm |
| 10 | `ten_dich_vu` | `Xạ trị bằng máy gia tốc`; `Khí dung đường thở (chưa bao gồm thuốc)`; `Thở oxy lưu lượng cao HFNC` | Giữ làm tên gọi khác/thông tin chi tiết; không tạo sự kiện trùng cột 2 |
| 11 | `CanThiepPhauThuat` | `nội soi tái tạo dây chằng chéo trước`; `đặt VAC`; `đặt sonde tiểu`; `thay khớp háng toàn phần` | Giữ văn bản có nội dung vào Thủ thuật |
| 12 | `LoaiPhauThuat` | `LDB`; `L1`; `L2`; `L3`; `KPL` | Giữ sau bảng giải mã; nhóm thủ thuật/dịch vụ |
| 13 | `pp_vocam` | `Gây tê tuỷ sống`; `Gây mê nội khí quản`; `NULL` | Giữ thuộc tính phương pháp vô cảm; chuẩn hóa các cách viết khác nhau |
| 14 | `TrinhTuThucHien_Text` | `sát khuẩn, trải khăn, rạch da và bộc lộ tổn thương`; `đặt dụng cụ, thực hiện can thiệp, kiểm tra cầm máu`; `đóng vết mổ và băng vô khuẩn` | Giữ, biên bản thủ thuật/phẫu thuật cốt lõi; ví dụ là câu tổng hợp |
| 15 | `DanLuu` | `Không`; `0`; `01`; `VAC` | Giữ sau khi chuẩn hóa thành: không có, có hoặc tên thiết bị dẫn lưu |
| 16 | `ThoiGianBatDau` | `2026-01-10 09:00`; `2026-01-11 13:30` | Giữ thời điểm bắt đầu |
| 17 | `ThoiGianKetThuc` | `2026-01-10 10:30`; `2026-01-11 15:00` | Giữ thời điểm kết thúc |
| 18 | `NgayCatChi` | `NULL` ở 11.342/11.342 | Bỏ: toàn NULL |
| 19 | `NgayRut` | `NULL` ở 11.342/11.342 | Bỏ: toàn NULL |
| 20 | `ThoiGianTiepNhan` | `2026-01-10 08:30`; `2026-01-11 13:00` | Giữ làm thời điểm tiếp nhận |
| 21 | `KetQua` | `An toàn`; `bệnh nhân dễ thở`; `kết nối máy thở an toàn`; `không ghi nhận biến chứng` | Giữ văn bản có nội dung; làm lộ thông tin tương lai tùy mốc thời gian giới hạn |
| 22 | `LoaiPT_TT` | `LDB`; `L1`; `L2`; `L3`; `KPL` | Nếu luôn giống `LoaiPhauThuat` thì chỉ giữ một cột; đây là cột lặp do quá trình xuất dữ liệu |
| 23 | `nhom_chiphi` | `THỦ THUẬT`; `PHẪU THUẬT`; `KẾT QUẢ PET/CT` | Giữ khái quát nhóm thủ thuật/dịch vụ; bỏ ý nghĩa chi phí/bảo hiểm/chi trả |

## 12. Danh sách cột toàn rỗng và cột hằng số đã xác minh

Phép kiểm tra này coi cả ô rỗng và chuỗi `"NULL"` là giá trị rỗng về mặt ý nghĩa.

### Toàn rỗng về mặt ý nghĩa

- `thông tin bệnh án`: `TRaVien`, `NRaVien`, `MRaVien`,
  `GiaDoanRaVien`, `ThoiGianDinhChi`, `NguyenNhanDinhChi`, `ChieuCao`,
  `LanhDaoKhoa_Id`, `ThuTruongDonVi_Id`, `TenFileNew`, `PathFileNew`.
- `chỉ định DVKT`: `KichThuocBuou`.
- `Thuốc`: `TieuDe`.
- `KQCLS`: `DU_PHONG`.
- `Phẫu thuật thủ thuật`: `ma_lk`, `NgayCatChi`, `NgayRut`.

Tất cả các cột này bị loại ở phiên bản bộ dữ liệu hiện tại. Nếu một phiên bản
dữ liệu mới có giá trị khác rỗng, phải kiểm tra lại trước khi tái sử dụng.

### Hằng số không giúp phân biệt các lượt khám

- `thông tin bệnh án`: `TaiBienDoPhauThau=0`,
  `TaiBienDoGayMe=0`, `TaiBienDoNhiemKhuan=0`, `TaiBienKhac=0`,
  `TuoiThai=0`.
- `Thuốc`: `CachGiaiQuyet="Chỉ định dùng thuốc"`,
  `HamLuong="NGƯỜI NHẬN THUỐC"`.
- `KQCLS`: `chat_luong_mau="Đạt"`.

Các cột hằng số bị loại vì không giúp phân biệt lượt khám. Riêng `HamLuong` còn là
lỗi xuất dữ liệu làm sai nghĩa tên cột, nên tuyệt đối không được dùng như hàm lượng
hoặc liều thuốc.
