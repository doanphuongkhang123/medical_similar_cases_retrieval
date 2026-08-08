# AGENTS.md — SimilarCasesRetrieval

## 1. Mục đích của file này

File này là hướng dẫn làm việc lâu dài cho AI và người phát triển trong dự án
`SimilarCasesRetrieval`. Mọi agent phải đọc file này trước khi sửa code hoặc
chạy tác vụ tốn tài nguyên.

Nếu có tài liệu dự án cụ thể hơn trong `docs/`, tài liệu đó được dùng để bổ
sung ngữ cảnh. Nếu có mâu thuẫn, yêu cầu trực tiếp mới nhất của người dùng
được ưu tiên, sau đó là file này, rồi đến các tài liệu cũ.

## 2. Bối cảnh dự án

Đây là dự án nghiên cứu hệ thống truy hồi các ca bệnh tương tự, hiện sử dụng
dữ liệu MIMIC-IV/MIMIC-IV-Note và các pipeline xử lý ghi chú lâm sàng, xét
nghiệm, embedding và retrieval.

Các khu vực chính hiện có:

- `code/scr_pipeline/`: mã nguồn pipeline SCR hiện tại.
- `code/third_party/`: mã nguồn và dữ liệu bên thứ ba, không coi là mã nguồn
  sản phẩm của dự án.
- `data/`: dữ liệu MIMIC, dữ liệu mẫu, dữ liệu trung gian và kết quả xử lý.
- `sync_to_server.sh`: đồng bộ mã nguồn từ máy local lên server.

Không được tự suy diễn định nghĩa lâm sàng, nhãn hoặc tiêu chí đánh giá. Khi
thay đổi các nội dung đó, phải ghi rõ nguồn, giả định và ảnh hưởng trong
`docs/DATA.md`, `docs/REQUIREMENTS.md` hoặc `docs/DECISIONS.md` nếu các file
đó đã tồn tại.

## 3. Hai môi trường làm việc

### Máy local

- Repository root: `/Users/k/Documents/work/SimilarCasesRetrieval`
- Mục đích: phát triển code, đọc/sửa tài liệu, chạy smoke test nhỏ và quản lý
  lịch sử Git.
- Không giả định máy local có toàn bộ dữ liệu MIMIC hoặc GPU đủ lớn.

### Server

- SSH host: `vaipe_aiotlab`
- Repository root bắt buộc: `/mnt/disk4/khangdp/similar_cases_retrieval/`
- Dataset riêng của nhóm: `/mnt/disk4/trangtth/data_subset/`
- Mục đích: chạy test đầy đủ, preprocessing trên dữ liệu hoàn chỉnh, huấn
  luyện, embedding, retrieval benchmark và các tác vụ GPU.

Khi cần chạy test hoặc tác vụ nặng, phải SSH vào server và chạy từ đúng
repository root:

```bash
ssh vaipe_aiotlab \
  'cd /mnt/disk4/khangdp/similar_cases_retrieval && <command>'
```

Không đổi sang một đường dẫn repository khác trên server. Không chạy toàn bộ
dataset, huấn luyện hoặc embedding nặng trên local trừ khi người dùng yêu
cầu rõ ràng.

Dataset riêng của nhóm tại `/mnt/disk4/trangtth/data_subset/` chỉ được đọc và
xử lý trên server. Không copy dataset này về local, không đưa vào thư mục
repository, không đồng bộ qua `sync_to_server.sh`, và không commit hoặc upload
nó lên bất kỳ Git remote/dịch vụ bên ngoài nào. Khi chạy pipeline với dataset
này, phải ghi rõ path dataset, phiên bản hoặc mốc dữ liệu, cùng các tham số
lọc/chia dữ liệu trong log thí nghiệm.

## 4. Quy tắc đồng bộ local/server/GitHub

Local là **nguồn code chính thức**. Server là bản sao thực thi dùng cho dữ
liệu và GPU. GitHub là remote private để lưu lịch sử và chia sẻ/backup code
từ local; GitHub không phải cơ chế đồng bộ code lên server.

Code được đưa từ local lên server bằng `rsync`, thông qua
`sync_to_server.sh`. Luồng chuẩn là:

1. Kiểm tra thay đổi hiện tại bằng `git status` và đọc các commit gần đây.
2. Sửa code/tài liệu trên local.
3. Chạy smoke test local nếu phù hợp.
4. Chạy `./sync_to_server.sh` để đồng bộ code local → server.
5. SSH vào server và chạy test/thí nghiệm từ
   `/mnt/disk4/khangdp/similar_cases_retrieval/`.
6. Nếu thay đổi đạt yêu cầu, commit code trên local.
7. Push commit từ local lên GitHub private bằng `git push origin main`.
8. Ghi commit hash, lệnh chạy, cấu hình, dataset version và kết quả vào
   `docs/EXPERIMENTS.md` hoặc `docs/STATUS.md`.

`sync_to_server.sh` hiện đồng bộ một chiều local → server và loại trừ `.git`,
`data/`, virtualenv, checkpoint và output. Không chạy `git pull` từ GitHub trên
server để thay thế cho rsync. Không dùng rsync ngược nếu trên server có thay
đổi code chưa được đưa về local; việc đó có thể làm mất thay đổi.

Không sửa code trực tiếp trên server trong quy trình thông thường. Nếu bắt
buộc phải sửa để chẩn đoán, phải đưa diff về local, kiểm tra và commit tại
local trước lần đồng bộ kế tiếp. Output/checkpoint trên server không thay thế
cho code commit hoặc GitHub history.

Không tự ý đổi `REMOTE_HOST`, `REMOTE_DIR`, `LOCAL_DIR` hoặc đường dẫn server
đã quy định ở trên.

## 5. Git và lịch sử dự án

Git root là thư mục repository này. Chỉ commit những thứ cần để tái tạo và
hiểu mã nguồn:

Repository và mọi remote Git của dự án phải ở chế độ **private**. Hiện tại
repository này chỉ được lưu local và chưa cấu hình remote. Không tự ý thêm
remote, push code, hoặc kết nối repository này với một public repository. Nếu
sau này cần dùng GitHub/GitLab/Bitbucket hay máy chủ Git khác, phải xác nhận
remote là private trước khi push.

- mã nguồn dự án;
- script chạy pipeline;
- file dependency/configuration;
- tài liệu Markdown và metadata nhỏ;
- test và fixture nhỏ, không chứa dữ liệu nhạy cảm.

Không commit:

- dữ liệu MIMIC hoặc dữ liệu bệnh nhân/raw clinical notes;
- file trong `data/`;
- virtualenv, cache, log, checkpoint, embedding và model weights;
- output lớn như Parquet/CSV/NPZ/JSONL được sinh ra từ pipeline;
- repository Git lồng nhau, archive hoặc mã nguồn bên thứ ba đã được quản lý
  riêng.

Trước khi commit phải kiểm tra:

```bash
git status
git diff --check
git diff --stat
```

Quy ước commit:

- `feat:` thêm chức năng;
- `fix:` sửa lỗi;
- `data:` thay đổi định nghĩa/cohort/preprocessing dữ liệu;
- `exp:` thay đổi hoặc ghi nhận thí nghiệm;
- `docs:` cập nhật tài liệu;
- `refactor:` thay đổi cấu trúc nhưng không đổi mục đích;
- `chore:` thay đổi tooling/phụ trợ.

Mỗi commit nên trả lời được: thay đổi gì, vì sao, và có ảnh hưởng gì đến kết
quả trước đó. Không rewrite hoặc xóa lịch sử Git đã có nếu chưa được người
dùng yêu cầu rõ ràng.

## 6. Kiểm thử và xác minh

Mức kiểm tra mặc định:

- Local: syntax check, import check, unit test nhỏ và smoke test với dữ liệu
  mẫu.
- Server: test đầy đủ, preprocessing thật, benchmark, huấn luyện và mọi tác
  vụ cần GPU hoặc dữ liệu đầy đủ.

Trước khi báo hoàn thành một thay đổi, phải xác minh ở mức phù hợp và ghi lại:

- command đã chạy;
- môi trường/hostname;
- commit hash;
- kết quả pass/fail;
- nếu chưa chạy được, lý do và bước còn thiếu.

Không báo “đã test” nếu chỉ kiểm tra bằng mắt hoặc mới chạy một phần không đại
diện cho thay đổi.

## 7. Chạy tác vụ dài trên server

Mọi tác vụ trên server có khả năng chạy lâu, cần GPU hoặc không thể theo dõi
liên tục phải được khởi chạy ở chế độ nền/detached. Không yêu cầu người dùng
giữ SSH mở hoặc theo dõi terminal 24/7.

Quy tắc mặc định:

1. Ưu tiên `tmux` với session có tên duy nhất theo experiment/job ID.
2. Nếu không có `tmux`, dùng `nohup` hoặc cơ chế detached tương đương.
3. Redirect đầy đủ stdout/stderr vào log trên server; không để log quan trọng
   chỉ tồn tại trong terminal SSH.
4. Ghi lại command, thời điểm bắt đầu, commit hash, dataset path, PID hoặc
   session name, đường dẫn log và cấu hình VRAM/batch size.
5. Sau khi khởi chạy phải kiểm tra một lần rằng process còn chạy, đúng GPU và
   log đã được tạo. Sau đó có thể để job tự chạy.
6. Khi cần báo kết quả, phải kiểm tra exit status, log cuối và output chính;
   không suy luận job thành công chỉ vì process đã được khởi chạy.

Mẫu khởi chạy được ưu tiên:

```bash
ssh vaipe_aiotlab \
  'cd /mnt/disk4/khangdp/similar_cases_retrieval && \
   mkdir -p logs && \
   tmux new-session -d -s exp_001 \
   "bash -lc '\''<command> > logs/exp_001.log 2>&1'\''"'
```

Kiểm tra sau khi khởi chạy:

```bash
ssh vaipe_aiotlab \
  'tmux has-session -t exp_001 && tail -n 40 \
   /mnt/disk4/khangdp/similar_cases_retrieval/logs/exp_001.log'
```

Không dùng `&` đơn lẻ cho job quan trọng nếu chưa redirect log và stdin/stdout;
job có thể chết khi SSH đóng hoặc không để lại thông tin chẩn đoán. Không khởi
chạy trùng job GPU nếu chưa kiểm tra process/session hiện có. Log, PID, session
metadata và output sinh ra trên server không được commit vào Git.

## 8. Chính sách sử dụng VRAM

Mục tiêu mặc định là dùng batch size lớn nhất chạy ổn định trên GPU server,
không dùng một batch size nhỏ cố định chỉ vì an toàn.

Khi chạy training/inference/embedding:

1. Kiểm tra GPU và VRAM bằng `nvidia-smi`.
2. Bắt đầu từ batch size lớn hợp lý theo giới hạn của tác vụ hoặc dùng chế độ
   auto-tuning nếu pipeline hỗ trợ.
3. Nếu gặp CUDA out-of-memory, giải phóng cache, khởi tạo lại trạng thái cần
   thiết và giảm batch size từng bước; không bỏ qua lỗi bằng cách tiếp tục với
   kết quả không đầy đủ.
4. Sau khi tìm được batch size chạy được, thử tăng lại để xác nhận batch size
   lớn nhất thực sự ổn định. Có thể dùng tìm kiếm nhị phân giữa cận chạy được
   và cận OOM để tiết kiệm thời gian.
5. Ghi batch size cuối cùng, precision, sequence length, gradient accumulation
   và các lần OOM vào log thí nghiệm.

Các biện pháp tối ưu VRAM được ưu tiên khi không làm thay đổi mục tiêu thí
nghiệm:

- mixed precision phù hợp với GPU;
- giải phóng tensor/cache giữa các lần thử;
- gradient accumulation để giữ effective batch size khi cần;
- padding động và giới hạn sequence length có chủ đích;
- gradient checkpointing khi training model lớn.

Không âm thầm thay đổi precision, sequence length, sampling hoặc effective
batch size nếu điều đó làm thay đổi khả năng so sánh giữa các thí nghiệm.

## 9. Tính tái lập và chống leakage

Mọi pipeline hoặc thí nghiệm mới phải cố gắng lưu/ghi nhận:

- random seed;
- commit hash;
- đường dẫn và version dataset;
- tham số preprocessing;
- model/tokenizer và version dependency;
- train/validation/test split;
- metric và cách tính metric.

Với dữ liệu bệnh án, phải đặc biệt kiểm tra leakage theo `subject_id`,
`hadm_id`, thời gian quan sát và nội dung chỉ xuất hiện sau thời điểm truy vấn.
Không dùng diagnosis, procedure, discharge outcome hoặc thông tin tương lai
làm input nếu thiết kế thí nghiệm không cho phép.

## 10. Bảo vệ dữ liệu

Không upload raw data, clinical notes, model artifact chứa dữ liệu hoặc log có
thể nhận diện bệnh nhân lên dịch vụ bên ngoài. Không đưa nội dung bệnh án vào
commit message, issue, Markdown hoặc output báo cáo nếu không cần thiết.

Khi cần minh họa, dùng ID giả, dữ liệu mẫu tối thiểu và đường dẫn local/server
thay vì chép nội dung clinical note vào tài liệu.

## 11. Cập nhật tài liệu sau mỗi thay đổi lớn

- Mục tiêu/phạm vi thay đổi → `docs/PROJECT_BRIEF.md` hoặc
  `docs/REQUIREMENTS.md`.
- Luồng module/định dạng interface thay đổi → `docs/ARCHITECTURE.md`.
- Cohort, label, split, schema hoặc preprocessing thay đổi → `docs/DATA.md`.
- Kết quả chạy mới → `docs/EXPERIMENTS.md`.
- Quyết định kỹ thuật có ảnh hưởng lâu dài → `docs/DECISIONS.md`.
- Việc đã làm, việc tiếp theo, blocker → `docs/STATUS.md`.

Nếu một tài liệu chưa tồn tại, tạo nó khi thay đổi đầu tiên cần đến tài liệu
đó; không ghi chú quan trọng chỉ trong hội thoại.

## 12. Nguyên tắc làm việc của agent

Trước khi hành động, agent phải:

- kiểm tra `git status` để không ghi đè thay đổi của người dùng;
- đọc tài liệu liên quan và README của module;
- xác định tác vụ đang chạy ở local hay server;
- ưu tiên thay đổi nhỏ, có thể kiểm tra và dễ rollback;
- không xóa dữ liệu hoặc output lớn nếu chưa được yêu cầu rõ ràng.

Khi có lỗi, phải phân biệt rõ lỗi code, lỗi môi trường, thiếu dữ liệu, thiếu
quyền truy cập và lỗi do giới hạn tài nguyên GPU.
