# Project Brief — Medical Similar Cases Retrieval

**Trạng thái:** Bản nháp ban đầu
**Phiên bản:** 0.2
**Ngày cập nhật:** 2026-08-12

## 1. Tóm tắt dự án

Đây là một hệ thống **medical similar cases retrieval**. Hệ thống nhận thông
tin của một bệnh nhân mới làm truy vấn và trả về thông tin của `top-k` bệnh
nhân hoặc ca bệnh liên quan nhất trong kho dữ liệu tham chiếu.

Mục tiêu của hệ thống là giúp người dùng tìm nhanh những ca bệnh tương tự để
tham khảo trong quá trình phân tích và nghiên cứu. Hệ thống tập trung vào
việc truy hồi các ca tương tự; nó không tự động đưa ra chẩn đoán hoặc thay thế
quyết định của nhân viên y tế.

## 2. Mục tiêu

### Mục tiêu chính

Xây dựng một pipeline có khả năng:

1. Nhận thông tin lâm sàng của bệnh nhân mới.
2. Biểu diễn thông tin đó thành dạng có thể so sánh với dữ liệu tham chiếu.
3. Tính độ tương đồng giữa bệnh nhân mới và các ca trong kho dữ liệu.
4. Trả về `top-k` ca liên quan nhất cùng thông tin cần thiết để người dùng
   kiểm tra và tham khảo.

### Mục tiêu kỹ thuật

- Xây dựng pipeline preprocessing có thể tái lập.
- Hỗ trợ dữ liệu lâm sàng phù hợp với dữ liệu hiện có, bao gồm clinical notes
  và các dữ liệu cấu trúc nếu được xác định trong thiết kế chi tiết.
- Đảm bảo việc chia dữ liệu và đánh giá hạn chế data leakage.
- Theo dõi được dataset version, model version, cấu hình và kết quả của từng
  thí nghiệm.
- Có thể chạy smoke test trên local và chạy pipeline đầy đủ trên server.

## 3. Người dùng và tình huống sử dụng

### Người dùng dự kiến

Người dùng chính và bối cảnh sử dụng cụ thể hiện chưa được xác định đầy đủ.
Các khả năng hiện tại gồm:

- nhà nghiên cứu medical AI;
- bác sĩ hoặc nhân viên y tế dùng như công cụ tham khảo;
- kỹ sư hoặc data scientist đánh giá các phương pháp retrieval.

**TBD:** Xác định người dùng chính, mức độ chuyên môn và giao diện sử dụng
(command line, notebook, API hay giao diện web).

### Tình huống sử dụng ban đầu

Người dùng cung cấp thông tin của một bệnh nhân mới. Hệ thống tìm kiếm trong
kho dữ liệu tham chiếu và hiển thị `top-k` bệnh nhân/ca bệnh tương tự nhất,
kèm các trường thông tin được phép hiển thị để người dùng tự đánh giá mức độ
liên quan.

## 4. Input và output

### Input

Input là thông tin của một bệnh nhân mới. Thành phần chính xác cần được xác
định trong thiết kế dữ liệu, nhưng có thể bao gồm:

- clinical notes hoặc mô tả lâm sàng;
- kết quả xét nghiệm;
- thông tin thời gian và bối cảnh nhập viện;
- các trường dữ liệu cấu trúc khác nếu được phê duyệt.

**TBD:** Chốt schema input, các trường bắt buộc, trường tùy chọn, giới hạn độ
dài văn bản và mốc thời gian quan sát được phép sử dụng.

### Output

Với mỗi truy vấn, hệ thống trả về tối đa `k` kết quả có độ tương đồng cao nhất.
Mỗi kết quả nên bao gồm:

- định danh ca bệnh/bệnh nhân ở dạng được phép sử dụng;
- similarity score hoặc ranking score;
- các thông tin lâm sàng liên quan để kiểm tra kết quả;
- metadata về thời điểm và bối cảnh của ca bệnh;
- các nhãn hoặc outcome chỉ dùng cho đánh giá nếu chúng không phải input của
  retrieval.

**TBD:** Xác định chính xác `k`, định nghĩa “liên quan nhất”, các trường được
phép hiển thị và có cần giải thích lý do một ca được truy hồi hay không.

## 5. Luồng xử lý dự kiến

```text
Thông tin bệnh nhân mới
          ↓
Kiểm tra và chuẩn hóa input
          ↓
Tạo embedding / representation
          ↓
Tìm kiếm trong kho ca bệnh tham chiếu
          ↓
Xếp hạng theo similarity score
          ↓
Trả về top-k ca liên quan nhất
```

Các thành phần cụ thể của embedding, index, similarity function và ranking
chưa được chốt trong project brief này.

## 6. Phạm vi ban đầu

### Trong phạm vi

- Xây dựng dữ liệu và pipeline preprocessing.
- Xây dựng baseline similarity retrieval.
- Thử nghiệm các biểu diễn từ clinical text và dữ liệu cấu trúc phù hợp.
- Đánh giá chất lượng truy hồi bằng các metric được thống nhất.
- Theo dõi thí nghiệm và bảo đảm khả năng tái lập.
- Chạy dữ liệu đầy đủ trên server được chỉ định.

### Chưa nằm trong phạm vi mặc định

- Tự động chẩn đoán bệnh.
- Đề xuất phác đồ hoặc quyết định điều trị.
- Thay thế đánh giá của bác sĩ.
- Đưa hệ thống vào sử dụng lâm sàng thực tế khi chưa có quy trình kiểm định,
  bảo mật và phê duyệt phù hợp.
- Chia sẻ dữ liệu riêng của nhóm ra ngoài môi trường được cấp quyền.

## 7. Dữ liệu và môi trường hiện có

- Project root trên server: `/mnt/disk4/similar_cases_retrieval/`
- Dataset root chuẩn: `/mnt/disk4/similar_cases_retrieval/data/`
- Code/repository root chuẩn: `/mnt/disk4/similar_cases_retrieval/code/`
- Host server: `vaipe_aiotlab`
- Máy local dùng để phát triển và chạy smoke test nhỏ.
- Raw data nằm tại `data/raw/`: các nhóm `CT`, `MRI`, `XQ`, `2025 PET CT`,
  `PDF-grBA` cùng file metadata `thông tin bệnh án.xlsx`. Derived artifact
  phải nằm trong `data/experiments/<experiment_id>/` hoặc khu vực xử lý riêng.
- Code root mới đã được đồng bộ từ repository local ngày 2026-08-12. Code ở
  path legacy `/mnt/disk4/khangdp/similar_cases_retrieval/code/` vẫn được giữ
  nguyên để đối chiếu và chưa bị xóa.
- Pipeline local hiện tại trong `code/scr_pipeline/` được xây dựng cho
  MIMIC-IV/MIMIC-IV-Note và lab events; chưa được xác nhận là đã map với dataset
  ảnh/PDF/Excel ở data root mới.

Chi tiết schema, quy tắc liên kết ID giữa Excel/PDF/ảnh, cohort, label, split
và data lineage phải được ghi trong `docs/DATA.md`, không chỉ ghi trong file
này. Không được suy diễn quan hệ giữa các nguồn dữ liệu khi chưa kiểm tra
schema và quy ước đặt tên trên server.

## 8. Tiêu chí thành công ban đầu

Các tiêu chí định lượng chưa được chốt. Phiên bản đầu tiên được xem là đạt
mốc kỹ thuật khi:

- có thể chạy end-to-end từ input đến top-k output;
- kết quả có thể tái lập từ cùng commit, dataset version và configuration;
- không có leakage giữa các nhóm bệnh nhân theo quy tắc đã thống nhất;
- có baseline để so sánh với các phương pháp cải tiến;
- ghi nhận được metric, runtime, VRAM và cấu hình chạy;
- người dùng có thể kiểm tra được vì sao một kết quả được trả về ở mức thông
  tin mà hệ thống hỗ trợ.

**TBD:** Chốt metric chính, ngưỡng chấp nhận, baseline bắt buộc và tiêu chí
đánh giá bởi chuyên gia y tế.

## 9. Các câu hỏi cần làm rõ

1. Đơn vị retrieval là bệnh nhân, hospital admission hay ICU stay?
2. Input ban đầu gồm clinical text, lab data hay cả hai?
3. Kho dữ liệu tham chiếu gồm những loại ca nào?
4. “Tương tự” được đánh giá bằng similarity định lượng, nhãn lâm sàng,
   đánh giá chuyên gia hay kết hợp các cách trên?
5. Những trường thông tin nào được phép xuất hiện trong output?
6. Giá trị `k` mặc định là bao nhiêu và có cho phép người dùng thay đổi không?
7. Có yêu cầu giải thích/rationale cho từng kết quả không?
8. Metric và test set chính thức là gì?
9. Người dùng cuối và giao diện đầu tiên là ai/cái gì?
10. Các yêu cầu về quyền truy cập, audit log và bảo mật khi hiển thị kết quả
    là gì?

## 10. Liên kết tài liệu

- Quy tắc làm việc: [`AGENTS.md`](../AGENTS.md)
- Định nghĩa dữ liệu: `docs/DATA.md` — sẽ bổ sung
- Kiến trúc: `docs/ARCHITECTURE.md` — sẽ bổ sung
- Theo dõi trạng thái: `docs/STATUS.md` — sẽ bổ sung
- Theo dõi thí nghiệm: `docs/EXPERIMENTS.md` — sẽ bổ sung
