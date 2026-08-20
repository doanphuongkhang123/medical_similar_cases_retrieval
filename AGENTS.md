# Agent operating contract

This file is mandatory project context. Every agent must read it before
inspecting data, editing code, running tests, launching jobs, syncing files, or
publishing changes.

## 1. Two-machine setup

This project has two distinct environments. Do not treat them as interchangeable.

### Local workstation — code editing only

- Workspace: `/Users/k/Documents/work/SimilarCasesRetrieval`
- Purpose: inspect and edit source code, review diffs, prepare scripts, and
  create local-only supporting material.
- The real EHR data and the lab GPUs are not local.
- Do not claim that a pipeline was tested on real data or that embeddings were
  generated based on a local or synthetic run.

### Shared lab server — tests, data processing, and compute

- SSH alias: `vaipe_aiotlab`
- Code root: `/mnt/disk4/similar_cases_retrieval/code`
- Data root: `/mnt/disk4/similar_cases_retrieval/data`
- Canonical raw EHR workbook:
  `/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx`
- `/mnt/disk4/similar_cases_retrieval/data/ehr_preprocessed/` contains
  downstream derived artifacts. Do not silently use those artifacts as the
  source of a new pipeline that is required to start from raw data.
- The server contains the real datasets and shared NVIDIA GPUs.
- Run unit/integration tests, schema audits, preprocessing, model downloads,
  training, and inference on this server unless the user explicitly says
  otherwise.
- For every new data pipeline, record the raw input path and SHA-256 in its
  manifest. Intermediate normalized tables must live inside that pipeline's
  own data folder so lineage does not depend on another pipeline's outputs.
- Clinical data, embeddings, checkpoints, caches, logs, and experiment outputs
  stay under the server data/experiment areas and never enter Git.

Before server work, verify identity and paths:

```bash
ssh -o BatchMode=yes vaipe_aiotlab \
  'hostname; whoami; test -d /mnt/disk4/similar_cases_retrieval/code; test -d /mnt/disk4/similar_cases_retrieval/data'
```

If SSH fails, stop and report that server execution did not happen. A local
synthetic test is not a substitute.

## 2. Required workflow

Follow this order for every code task:

1. Read this file plus `docs/DATA.md`, `docs/STATUS.md`, and the relevant
   pipeline README/handoff.
2. Edit code in the local workspace. Local is the source of truth for code.
3. Review the exact local diff and preserve unrelated user changes.
4. Dry-run a targeted rsync to the matching server path.
5. Perform the real rsync without `--delete`.
6. Run tests and data/compute work through `ssh vaipe_aiotlab`.
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

Example for one pipeline:

```bash
LOCAL=/Users/k/Documents/work/SimilarCasesRetrieval/code/context_clues/
REMOTE=/mnt/disk4/similar_cases_retrieval/code/code/context_clues/

rsync -avhn --itemize-changes \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  "$LOCAL" "vaipe_aiotlab:$REMOTE"

rsync -avh --itemize-changes \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  "$LOCAL" "vaipe_aiotlab:$REMOTE"
```

Rules:

- Sync only the file or pipeline directory in scope, not the whole workspace
  by default.
- Always dry-run first with `-n` and inspect the itemized changes.
- Do not use `--delete` unless the user explicitly authorizes deletion and the
  exact remote target has been verified.
- Do not rsync server datasets, checkpoints, embeddings, logs, or outputs back
  to the local workspace.
- If a server-side code change exists, compare it before overwriting. Bring a
  deliberate code hotfix back into local source; do not let two versions drift.
- Root agent instructions are an exception to targeted pipeline sync. Whenever
  `AGENTS.md` changes, sync it explicitly to:
  `/mnt/disk4/similar_cases_retrieval/code/AGENTS.md`.

## 4. Shared-GPU policy

The GPUs belong to a shared lab server. Before any command that can allocate
CUDA memory, inspect utilization and running processes:

```bash
ssh vaipe_aiotlab \
  'nvidia-smi --query-gpu=index,name,memory.total,memory.free,utilization.gpu \
   --format=csv,noheader; \
   nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader'
```

- Never kill, pause, renice, or interfere with another user's process.
- Never start a heavy job on a full/busy GPU.
- CPU-only preprocessing and network-only model downloads must explicitly hide
  GPUs with `CUDA_VISIBLE_DEVICES=""` when practical.
- Put Hugging Face/model caches on `/mnt/disk4`, not a full system disk.

If no GPU has enough free memory, prepare a server-side wait-and-run script
instead of repeatedly launching the job. The script must:

- poll `nvidia-smi` at a reasonable interval (normally 60 seconds);
- require an explicit free-memory threshold suitable for the job;
- select/export the chosen `CUDA_VISIBLE_DEVICES` only after the threshold is met;
- write a PID and timestamped log under the server experiment/output folder;
- use a lock or other guard so the same job is not launched twice;
- preserve the exact command/configuration for reproducibility;
- exit nonzero and log the reason if the final command fails.

Launch the waiter in a durable way such as `nohup`/`tmux`, then report its PID,
log path, GPU threshold, and eventual artifact path. A waiting job is “queued,”
not “completed.”

## 5. GitHub publishing policy

Remote repository: `origin` (`medical_similar_cases_retrieval`).

GitHub contains only files required for the main runnable project:

- source code for the EHR, Context Clues, text, image, retrieval, and review
  pipelines;
- tests, runtime shell scripts, dependency/config files;
- essential pipeline contracts/READMEs;
- this `AGENTS.md` file and other explicitly designated agent instructions.

Do not publish auxiliary or one-off material, including:

- slides, presentation builds, figures made only for explanation;
- ad-hoc explanations, scratch analyses, temporary reports, chat exports;
- local visualization artifacts, recovered files, caches, or generated media;
- real data, derived Parquet/CSV files, embeddings, checkpoints, model weights,
  experiment outputs, logs, credentials, or tokens.

Keep auxiliary material in local-only ignored directories such as
`.local_artifacts/` or another clearly local path. Agent instruction Markdown
is a deliberate exception: it must be present locally, tracked in GitHub, and
synced to the server.

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
- Commit and push only after relevant tests have passed on
  `vaipe_aiotlab` (an instruction-only Markdown change needs content/sync
  verification rather than GPU tests).
- Do not rewrite history or force-push unless the user explicitly requests it.

## 6. Three-copy requirement for agent instructions

Agent instruction Markdown must match in all three locations:

1. Local workspace: `/Users/k/Documents/work/SimilarCasesRetrieval/AGENTS.md`
2. GitHub: tracked on the active project branch
3. Lab server: `/mnt/disk4/similar_cases_retrieval/code/AGENTS.md`

After updating it, compare SHA-256 checksums across local, GitHub checkout, and
server. Do not report the update complete until all reachable copies match. If
GitHub or SSH is unavailable, state exactly which copy remains unsynchronized.
