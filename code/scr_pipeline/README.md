# SCR preprocessing: MIMIC-IV text + lab events

This prepares one model example per hospital admission (`hadm_id`) from the
local MIMIC-IV v3.1 and MIMIC-IV-Note v2.2 folders.

The text preprocessing follows the public [CliniBench](https://github.com/DATEXIS/CliniBench)
idea: extract admission-time sections from the discharge note (chief complaint,
HPI, past history, medications on admission, allergies, physical, family and
social history). This prevents discharge diagnoses and hospital-course text
from leaking into an admission-time query.

The laboratory input is an irregular event sequence. By default only numeric
`labevents` in the first 24 hours after `admittime` are retained. Every event
contains an item id, normalized value, time since admission and abnormality
flag. Normalization statistics and the item vocabulary are learned from the
training split only. Splits are made by `subject_id`, while the retrieval unit
remains `hadm_id`, so one patient cannot appear in both train and test.

The resulting model contracts are deliberately simple: tokenize `samples.parquet:text`
with `emilyalsentzer/Bio_ClinicalBERT` (pool the CLS vector), and pass each row of
`lab_sequences.parquet` through an event encoder (for example STraTS, GRU/LSTM,
or a small Transformer). Each lab event is represented by
`(item_indices, values_norm, times_hours, is_abnormal)`; `lab_events.parquet`
keeps the ungrouped rows for debugging and alternative aggregations.

## Run

```bash
python preprocess_scr.py \
  --mimic-iv /path/to/mimic-iv-3.1 \
  --notes /path/to/mimic-iv-note-deidentified-free-text-clinical-notes-2.2 \
  --out /path/to/scr_preprocessed \
  --lab-window-hours 24 \
  --min-lab-count 5 \
  --max-events 512
```

For a local smoke test, add `--limit-notes 100`; the bundled local sample has
only 100 rows per source file and may legitimately produce zero joined lab
events. The server's full files are required for a meaningful count.

## Outputs

- `samples.parquet`: one row per `hadm_id`, with `subject_id`, `split`, admission
  timestamps and admission-only `text`. It also records the number of lab events.
- `lab_events.parquet`: one row per numeric event, including `item_index`,
  `value_norm`, `time_hours`, `is_abnormal`, raw unit and reference ranges.
- `lab_sequences.parquet`: variable-length lists ready for a PyTorch collator:
  item indices, normalized values, event times and abnormality flags.
- `lab_vocab.json`, `lab_stats.json`: train-only vocabulary and normalization
  statistics.
- `manifest.json`: source paths, window, split rule and row counts.

The output is not yet a learned embedding: it is the leakage-safe input layer
for the later BioClinicalBERT + lab-event encoder + fusion experiment.

## Create and reuse embeddings

Install the model dependencies once on the server, then create embeddings:

```bash
python embed_scr.py \
  --input /path/to/scr_preprocessed \
  --output /path/to/scr_embeddings \
  --text-model emilyalsentzer/Bio_ClinicalBERT \
  --batch-size 8
```

This writes `text_embeddings.parquet` separately. If that file and its JSON
metadata are present with the same model and maximum length, later runs reuse
it instead of running BioClinicalBERT again. `scr_embeddings.parquet` contains
the text, lab and fused vectors keyed by `hadm_id`.

Without `--lab-checkpoint`, the GRU is only an architecture smoke test and its
lab vectors are not meaningful for retrieval. Train it against the cached text
vectors with the paired-modality InfoNCE baseline:

```bash
python train_lab_encoder.py \
  --input /path/to/scr_preprocessed \
  --text-embeddings /path/to/scr_embeddings/text_embeddings.parquet \
  --output /path/to/scr_embeddings/lab_gru.pt \
  --epochs 5

python embed_scr.py \
  --input /path/to/scr_preprocessed \
  --output /path/to/scr_embeddings \
  --lab-checkpoint /path/to/scr_embeddings/lab_gru.pt
```

The training objective aligns lab sequences with the same admission's cached
text embedding; it does not use diagnosis labels. This is a baseline for the
SCR experiment, not a claim that the untrained GRU output is already useful.

## Retrieve similar admissions

After creating `scr_embeddings.parquet`, retrieve from the train split:

```bash
python retrieve_scr.py \
  --embeddings /path/to/scr_embeddings/scr_embeddings.parquet \
  --query-hadm-id 12345678 \
  --embedding-column fused_embedding \
  --candidate-split train \
  --top-k 10
```

The script does not use diagnosis, procedure or discharge outcome fields as
model inputs. Those can be added later as labels or evaluation annotations.
