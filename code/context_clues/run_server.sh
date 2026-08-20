#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/mnt/disk4/similar_cases_retrieval/code}"
PIPELINE_ROOT="$PROJECT_ROOT/code/context_clues"
PYTHON="${CONTEXT_CLUES_PYTHON:-/mnt/disk1/khangdp/conda_envs/context_clues/bin/python}"

OUTPUT_ROOT="${CONTEXT_CLUES_OUTPUT_ROOT:-/mnt/disk4/similar_cases_retrieval/data/context_clues}"
RAW_PIPELINE_ROOT="${CONTEXT_CLUES_RAW_PIPELINE_ROOT:-$OUTPUT_ROOT/raw_pipeline_v1}"
INPUT_ROOT="$RAW_PIPELINE_ROOT/structured"
SOURCE_PREPARED_ROOT="$RAW_PIPELINE_ROOT/source_prepared"
CONCEPT_MAP="${CONTEXT_CLUES_CONCEPT_MAP:-$SOURCE_PREPARED_ROOT/concept_map.csv}"
PREPARED_ROOT="$RAW_PIPELINE_ROOT/prepared"
EMBEDDING_ROOT="$OUTPUT_ROOT/embeddings/gpt-base-4096-clmbr"

mkdir -p "$OUTPUT_ROOT"

if [[ ! -f "$INPUT_ROOT/manifest.json" ]]; then
  echo "Raw-derived structured data is missing at $INPUT_ROOT" >&2
  echo "Run $PIPELINE_ROOT/run_data_only_server.sh first." >&2
  exit 2
fi

if [[ ! -f "$CONCEPT_MAP" ]]; then
  echo "Concept map is missing at $CONCEPT_MAP" >&2
  echo "Run data-only preprocessing, then review the generated concept map." >&2
  exit 2
fi

if [[ ! -f "$PREPARED_ROOT/manifest.json" ]]; then
  "$PYTHON" "$PIPELINE_ROOT/prepare_events.py" \
    --input-root "$INPUT_ROOT" \
    --concept-map "$CONCEPT_MAP" \
    --output-root "$PREPARED_ROOT"
elif [[ "${CONTEXT_CLUES_REBUILD_PREPARED:-0}" == "1" ]]; then
  "$PYTHON" "$PIPELINE_ROOT/prepare_events.py" \
    --input-root "$INPUT_ROOT" \
    --concept-map "$CONCEPT_MAP" \
    --output-root "$PREPARED_ROOT" \
    --overwrite
else
  echo "Using existing prepared data at $PREPARED_ROOT"
fi

embed_args=(
  --prepared-root "$PREPARED_ROOT"
  --output-root "$EMBEDDING_ROOT"
  --model StanfordShahLab/gpt-base-4096-clmbr
  --timeline-mode history
  --max-length 4096
  --batch-size 8
  --max-tokens-per-batch 16384
)
if [[ "${CONTEXT_CLUES_OVERWRITE_EMBEDDINGS:-0}" == "1" ]]; then
  embed_args+=(--overwrite)
fi
"$PYTHON" "$PIPELINE_ROOT/embed_visits.py" "${embed_args[@]}"
