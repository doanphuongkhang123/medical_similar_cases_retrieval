# Agent operating contract

This file is mandatory project context. Every agent must read it before
inspecting data, editing code, running tests, launching jobs, syncing files, or
publishing changes.

## 1. Local workstation, primary H100 server, and legacy Vaipe server

These environments have distinct roles. Do not treat their paths, code, or
artifacts as interchangeable.

### Default server policy — effective 2026-10-08

- H100 (`brev-h100`) is the primary server for running code, tests, data
  processing, model downloads, training, inference, and deployment.
- Use the old Vaipe server (`vaipe_aiotlab`) only when the user explicitly
  requests it. In particular, retrieve code from Vaipe only when the user
  clearly says to take that code from the old server.
- Do not automatically connect to Vaipe, retrieve/sync its code or data, or
  fall back to it when an H100 path, dependency, dataset, or connection is
  unavailable. Report the missing requirement on H100 instead.
- This policy takes precedence over legacy Vaipe-only commands and paths in
  pipeline READMEs, handoffs, and status/support documents. Those references
  describe earlier runs; they do not authorize using Vaipe for new work.
- This policy does not assert that all Vaipe pipelines or datasets have been
  migrated to H100. Verify the required H100 paths and runtime before use.

### Local workstation — code editing only

- Workspace: `/Users/k/Documents/work/SimilarCasesRetrieval`
- Purpose: inspect and edit source code, review diffs, prepare scripts, and
  create local-only supporting material.
- The real clinical datasets and server GPUs are not local.
- Do not claim that a pipeline was tested on real data or that embeddings were
  generated based on a local or synthetic run.

### Primary H100 server — tests, data processing, and compute

- SSH alias: `brev-h100`.
- Verified identity on 2026-10-08: hostname `brev-jkkk35yxw`, user `nvidia`.
- Project root: `/data/khangdp/scr/`.
- Verified web code mapping:
  local `code/verify_web_h100/` → `/data/khangdp/scr/verify_web/code/`.
- Web runtime/data root: `/data/khangdp/scr/verify_web/`.
- Raw imaging root: `/data/khangdp/scr/raw/`.
- Canonical project agent instructions: `/data/khangdp/scr/AGENTS.md`.
- Other pipeline code, EHR raw input, data, experiment, and Python/environment
  paths must be verified on H100 before execution. Do not translate
  `/mnt/disk4/...` paths mechanically or use another pipeline's derived data
  as a replacement raw source.

### Legacy Vaipe server — explicit user request only

- SSH alias: `vaipe_aiotlab`
- Code root: `/mnt/disk4/similar_cases_retrieval/code`
- Data root: `/mnt/disk4/similar_cases_retrieval/data`
- Structured-EHR code root:
  `/mnt/disk4/similar_cases_retrieval/code/code/ehr/`
- Structured-EHR derived-data root:
  `/mnt/disk4/similar_cases_retrieval/data/ehr/`
- Canonical raw EHR workbook:
  `/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx`
- `/mnt/disk4/similar_cases_retrieval/data/ehr/ehr_preprocessed/` contains
  downstream derived artifacts. Do not silently use those artifacts as the
  source of a new pipeline that is required to start from raw data.
- These paths document the legacy server and do not imply that corresponding
  files already exist on H100.

### Data and execution rules on the selected server

- Run unit/integration tests, schema audits, preprocessing, model downloads,
  training, and inference on H100 by default. Use Vaipe only when explicitly
  requested by the user.
- For every new data pipeline, record the raw input path and SHA-256 in its
  manifest. Intermediate normalized tables must live inside that pipeline's
  own data folder so lineage does not depend on another pipeline's outputs.
- Clinical data, embeddings, checkpoints, caches, logs, and experiment outputs
  stay under the server data/experiment areas and never enter Git.
- Keep the canonical raw EHR workbook unchanged under `data/raw/`. Place only
  structured-EHR derived artifacts below `data/ehr/`; image, PDF,
  text-embedding, and cross-modal retrieval artifacts remain in their
  modality-specific roots.

Before H100 server work, verify identity and the project root, then verify the
specific code/data paths required by the task:

```bash
ssh -o BatchMode=yes brev-h100 \
  'hostname; whoami; test -d /data/khangdp/scr'
```

If SSH fails, stop and report that server execution did not happen. A local
synthetic test or automatic fallback to Vaipe is not a substitute. When the
user explicitly requests Vaipe work, verify its identity and paths with:

```bash
ssh -o BatchMode=yes vaipe_aiotlab \
  'hostname; whoami; test -d /mnt/disk4/similar_cases_retrieval/code; test -d /mnt/disk4/similar_cases_retrieval/data'
```

## 2. Required workflow

Follow this order for every code task:

1. Read this file plus `docs/DATA.md`, `docs/STATUS.md`, and the relevant
   pipeline README/handoff.
2. Edit code in the local workspace. Local is the source of truth for code.
3. Review the exact local diff and preserve unrelated user changes.
4. Verify the matching H100 path and dry-run a targeted rsync to it. A Vaipe
   target requires an explicit user request.
5. Perform the real rsync without `--delete`.
6. Run tests and data/compute work through `ssh brev-h100` by default.
7. Verify output counts, schemas, finite values, IDs, manifests, and artifact
   paths on the server.
8. Only then report the task as tested or complete, explicitly naming the host
   and server artifact path.
9. Publish only the allowed main-pipeline files to GitHub as described below.

Never say “full test passed,” “data processed,” “weights downloaded,” or
“embeddings generated” unless the corresponding server command completed and
the resulting server artifacts were checked.

## 3. Rsync is the code synchronization mechanism

The server code directory may not be a Git worktree. Synchronize code from
local to server with `rsync`; do not assume `git pull` exists on the server.

Example for the verified H100 web-code mapping:

```bash
LOCAL=/Users/k/Documents/work/SimilarCasesRetrieval/code/verify_web_h100/
REMOTE=/data/khangdp/scr/verify_web/code/

rsync -avhn --itemize-changes \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  "$LOCAL" "brev-h100:$REMOTE"

rsync -avh --itemize-changes \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  "$LOCAL" "brev-h100:$REMOTE"
```

Rules:

- Sync only the file or pipeline directory in scope, not the whole workspace
  by default.
- Always dry-run first with `-n` and inspect the itemized changes.
- Do not use `--delete` unless the user explicitly authorizes deletion and the
  exact remote target has been verified.
- If a server-side code change exists, compare it before overwriting. Bring a
  deliberate code hotfix back into local source; do not let two versions drift.
  Access to legacy Vaipe code still requires the user's explicit request.
- Root agent instructions are an exception to targeted pipeline sync. Whenever
  `AGENTS.md` changes, sync it explicitly to:
  `brev-h100:/data/khangdp/scr/AGENTS.md`.
- Update `/mnt/disk4/similar_cases_retrieval/code/AGENTS.md` on Vaipe only when
  the user explicitly requests legacy-server synchronization. Its historical
  copy is not part of the default three-copy requirement below.

## 4. Shared-GPU policy

Treat server GPUs as shared resources. Before any command that can allocate
CUDA memory, inspect utilization and running processes:

```bash
ssh brev-h100 \
  'nvidia-smi --query-gpu=index,name,memory.total,memory.free,utilization.gpu \
   --format=csv,noheader; \
   nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader'
```

- Never kill, pause, renice, or interfere with another user's process.
- When feasibility or OOM behavior is uncertain, first run one deliberately
  bounded CUDA smoke using the real production batch/configuration whenever
  possible. An explicit per-process CUDA memory cap may be used to reproduce a
  constrained-memory condition. Record the observed free memory, any hard cap,
  batch/configuration, peak allocated/reserved memory, and pass/OOM result.
- If that representative smoke passes, launch the requested full job without a
  fixed free-VRAM threshold or GPU-utilization threshold. These GPU metrics are
  diagnostic log fields, not launch gates. If the run actually OOMs, preserve
  the error and nonzero exit status and report it; do not repeatedly relaunch it.
- If the representative smoke OOMs, or no representative smoke can be run,
  report the evidence instead of inventing a resource threshold. Create a
  wait-and-run job only when the user explicitly requests one.
- CPU-only preprocessing and network-only model downloads must explicitly hide
  GPUs with `CUDA_VISIBLE_DEVICES=""` when practical.
- Put Hugging Face/model caches in a verified data/cache directory under
  `/data/khangdp/scr/` on H100, not a full system disk. For explicitly requested
  Vaipe work, use `/mnt/disk4`.

When the user explicitly requests a server-side wait-and-run script, it must:

- poll `nvidia-smi` at a reasonable interval (normally 60 seconds);
- use only a launch condition explicitly requested by the user; do not infer a
  free-memory or utilization threshold;
- log the observed GPU state whenever it polls;
- select/export the chosen `CUDA_VISIBLE_DEVICES` only after the requested
  condition is met;
- write a PID and timestamped log under the server experiment/output folder;
- use a lock or other guard so the same job is not launched twice;
- preserve the exact command/configuration for reproducibility;
- exit nonzero and log the reason if the final command fails.

Launch an explicitly requested waiter in a durable way such as `nohup`/`tmux`,
then report its PID, log path, exact launch condition, and eventual artifact
path. A waiting job is “queued,” not “completed.”

## 5. GitHub publishing policy

Remote repository: `origin` (`medical_similar_cases_retrieval`).

GitHub contains only files required for the main runnable project:

- source code for the EHR, Context Clues, text, image, retrieval, and review
  pipelines;
- tests, runtime shell scripts, dependency/config files;
- essential pipeline contracts/READMEs;
- maintained model/pipeline explanations under `docs/support/` that directly
  describe the current runnable pipeline and contain no clinical data;
- this `AGENTS.md` file and other explicitly designated agent instructions.

Do not publish auxiliary or one-off material, including:

- slides, presentation builds, figures made only for explanation;
- ad-hoc or stale explanations outside `docs/support/`, scratch analyses,
  temporary reports, chat exports;
- local visualization artifacts, recovered files, caches, or generated media;
- real data, derived Parquet/CSV files, embeddings, checkpoints, model weights,
  experiment outputs, logs, credentials, or tokens.

Keep auxiliary material in local-only ignored directories such as
`.local_artifacts/` or another clearly local path. Agent instruction Markdown
is a deliberate exception: it must be present locally, tracked in GitHub, and
synced to the server.

An explanation may be promoted from `.local_artifacts/` to `docs/support/`
only when the user explicitly requests publication and the document has been
checked against the current code/data contract. Do not promote slide build
trees, recovered chats, rendered media, runtime audits, or obsolete variants.

Before every commit/push:

```bash
git status --short
git diff --check
git diff --cached --name-only
git diff --cached
```

- Stage explicit paths; never use a broad add when unrelated files are dirty.
- Confirm every staged file belongs to the main runnable pipeline or is an
  agent instruction.
- Commit and push only after relevant tests have passed on the selected server
  (H100 by default; Vaipe only when explicitly requested). An instruction-only
  Markdown change needs content/sync verification rather than GPU tests.
- Do not rewrite history or force-push unless the user explicitly requests it.

## 6. Three-copy requirement for agent instructions

Agent instruction Markdown must match in all three locations:

1. Local workspace: `/Users/k/Documents/work/SimilarCasesRetrieval/AGENTS.md`
2. GitHub: tracked on the active project branch
3. Primary H100 server: `brev-h100:/data/khangdp/scr/AGENTS.md`

After updating it, compare SHA-256 checksums across local, GitHub checkout, and
server. Do not report the update complete until all reachable copies match. If
GitHub or SSH is unavailable, state exactly which copy remains unsynchronized.
Do not connect to Vaipe just to update or checksum its legacy copy; that requires
an explicit user request.

## 7. Không tự ý tạo file lớn bất hợp lý

- Trước khi xuất dữ liệu, ước lượng số bản ghi và dung lượng từ schema, số lượng
  dữ liệu và một mẫu đại diện nhỏ. Kiểm tra thiết kế có phù hợp với mục đích sử
  dụng hay không trước khi ghi toàn bộ file.
- Không tự ý tạo CSV hoặc artifact khổng lồ do chọn sai đơn vị bản ghi, lặp lại
  report/text/metadata trên hàng triệu dòng, hoặc xuất chi tiết không cần thiết.
  Phải sửa thiết kế để tránh lặp dữ liệu; không chỉ nén một đầu ra bất hợp lý.
- Nếu một đầu ra lớn thực sự cần thiết, báo trước dung lượng ước tính, lý do và
  phương án gọn hơn, rồi chờ người dùng đồng ý trước khi tạo. Không lấy việc người
  dùng chưa trả lời làm đồng ý. Đầu ra có dung lượng hợp lý trong phạm vi đã được
  yêu cầu thì tiếp tục thực hiện, không cần hỏi lại mọi lựa chọn triển khai.
- Với CSV nối ảnh–bệnh án này, đơn vị đã được chốt là một lần chụp/một dòng
  `(modality, StudyInstanceUID)`. Lưu các cách nối và ngoại lệ trong dòng tương ứng;
  không nhân bản report trên từng lát cắt. Chi tiết dùng để tra từng ảnh phải có
  cách lưu gọn, giữ được liên kết với bảng chính.
- Sau khi xuất, kiểm tra dung lượng thực tế, số dòng, tính duy nhất của khóa và
  việc bảo toàn dữ liệu. Nếu dung lượng vượt xa dự tính hoặc bộc lộ lặp dữ liệu
  bất hợp lý, sửa đầu ra trước khi giao cho người dùng.

## 8. Giữ nguyên định dạng Excel, không tự ý làm đẹp

- Khi sửa file Excel, mặc định giữ nguyên định dạng sẵn có của file gốc.
  Tập trung sửa nội dung, thông tin nối và cấu trúc tab theo yêu cầu.
- Không tự ý đổi font, cỡ chữ, màu sắc, theme, đường viền hoặc trang trí thêm.
  Chỉ làm đẹp hay thay đổi phong cách trình bày khi người dùng yêu cầu rõ ràng.
- Với file Excel mới, dùng định dạng mặc định của Excel nếu người dùng không
  yêu cầu định dạng riêng.
- Chỉ điều chỉnh độ rộng cột, chiều cao dòng, xuống dòng, bộ lọc hoặc cố định
  tiêu đề khi cần để đọc được dữ liệu; không coi đây là lý do để thiết kế lại
  toàn bộ file.

## 9. Excel Top-K retrieval: đặt report query và candidate cạnh nhau

- Khi tạo hoặc sửa Excel Top-K retrieval, luôn đặt `query_report` và
  `candidate_report` ở hai cột liền nhau trên cùng một dòng của bảng đối chiếu,
  để đọc và so sánh trực tiếp từng cặp query–candidate.
- Không chỉ cung cấp ID hoặc buộc người đọc chuyển tab để xem hai report.
  Giữ ID, rank và score tương ứng để truy vết, không thay đổi thứ hạng retrieval
  chỉ để bố trí bảng.
- Nếu một phía thiếu report hoặc chưa nối được report xác nhận, giữ trạng thái
  rõ ràng ngay trong bảng đối chiếu; không tự gán report của ca khác.
- Bố cục này vẫn phải tuân thủ quy tắc dung lượng ở mục 7 và giữ nguyên định
  dạng Excel ở mục 8.
