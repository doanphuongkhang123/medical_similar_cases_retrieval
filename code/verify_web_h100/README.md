# Patient review on H100

This deployment preserves the comparison and LLM review tools from Verify_web
and adds a catalogue for every patient in the mounted review dataset. Each
admission includes all available EHR fields, lab result details, studies,
series metadata, and access to every slice, including XQ series beyond the
first two. Missing source data remains missing rather than being inferred.
Diagnosis, medication and service/procedure tabs are supplied by a separate
compact preparation stage that reads the canonical raw workbook directly.
The raw workbook stays unchanged. Additional canonical EHR fields are shown
with a source label when they differ from the existing review packet. Age is
derived from admission year and birth year and labelled accordingly; gender
codes remain source codes rather than receiving an unverified interpretation.

The comparison view uses shared rows for EHR fields and lab names, so long
text and missing data cannot shift the two sides out of alignment. Each side
retains its own admission and lab date selection. Diagnosis, medication and
procedure entries are grouped by their displayed name, preserving every
occurrence and its source details; grouping does not match event dates.

Images stay outside SQL and Docker images. A request reads one NPY slice,
applies window/level and returns a grayscale PNG. The user can choose quick
preview or native resolution, pan, zoom, and select a slice. This is a 2D
review viewer, not a 3D/MPR implementation. Rescale metadata is respected;
files with unsupported layout, truncated payloads or excessive slice sizes
are rejected. Nginx does not buffer API responses to its system disk.

Accounts and reviews use Node 22's SQLite module. The database is
`runtime/review.sqlite3`, with WAL, full synchronization and transactional
review history. Legacy users.json, verifications.json and optional LLM
reviews are imported once, without changing the source files. The current
pair review is the latest decision; every rescore remains in review_history
with its reviewer. Login sessions are in memory and expire on backend restart.

## Layout and launch

Code: `/data/khangdp/scr/verify_web/code` on `brev-h100`.
Runtime data: `/data/khangdp/scr/verify_web/` (outside Git):

```
raw/<patient>/<admission>/{EHR,lab_result,CT,MRI,XQ}/
runtime/{users.json,verifications.json,review.sqlite3}
retrieval/backend/src/data/retrieval.json
retrieval/top20_related_patients.csv
llm_retrieval/
structured_v2/{records/<patient>/<visit>.json,tables/,manifest.json}
logs/
```

Copy existing hashed users and reviews into runtime before initial startup.
For a fresh database, configure ADMIN_USERNAME/ADMIN_PASSWORD in the backend
environment; the initializer requires at least twelve password characters.

```
WEB_DATA_ROOT=/data/khangdp/scr/verify_web docker compose -p scr-verify-h100 up --build -d
```

The frontend serves on loopback port 5178, with all API calls under `/api`.
Clinical endpoints require the application's bearer login. The public HTTPS
tunnel points to this frontend, never directly to the raw file directory.
All clinical responses are no-store. The tunnel runs in a dedicated user
service; quick-tunnel hostnames change on restart and are intended for review
and testing, with no uptime guarantee.

## Complete structured records

Run on Vaipe using Python with openpyxl, pandas and pyarrow:

```
python scripts/build_structured.py \
  --workbook '/mnt/disk4/similar_cases_retrieval/data/raw/thông tin bệnh án.xlsx' \
  --raw-web-root /mnt/disk4/namtn/similar_case_retrieval/working/Verify_web/app/data/raw \
  --output /mnt/disk4/similar_cases_retrieval/data/ehr/verify_web_h100/raw_pipeline_v2 \
  --preprocessor /mnt/disk4/similar_cases_retrieval/code/code/ehr/ehr_graph_embedding/preprocessing/preprocess_ehr_tables.py
```

The stage selects the exact 184 patient/admission pairs in the review cohort,
streams workbook sheets, and uses the maintained EHR builders for the selected
rows. It estimates export size before writing. Normalized tables live in its
own output directory; the manifest records workbook and builder SHA-256,
row counts and a checksum for every visit packet. Medication display preserves
the original prescription rows, strength and instructions alongside normalized
tables. Source order and performed-procedure details are attached by verified
order/admission identity. Direct identity fields omitted from review are listed
in the manifest. Copy this output to the H100 structured_v2 directory and verify
those checksums before use. Clinical
packets and normalized tables stay on the servers and never enter Git.

## Verification

Run backend tests on Vaipe before deployment and on H100 after building:

```
docker compose -p scr-verify-h100 exec backend npm test
```

Check dataset inventory, lineage/transfer manifest, SQLite integrity,
protected endpoints, all selected query/candidate IDs, EHR and lab counts,
NPY header/size alignment, and decoded slices through the public URL. Unit
tests alone do not prove the clinical dataset or public deployment works.
Do not commit runtime data, public login credentials, logs or manifests.

## Retrieval by modality

The separate `Retrieval theo từng modality` utility reads an immutable compact
bundle with five methods: neural biochemistry39 (fixed seed 20261004), patient
text Qwen3-Embedding-0.6B, CT-CLIP, 3DINO MRI and MedSigLIP X-ray. It preserves
patient/visit/source-embedding retrieval units and every original image/lab
rank and decimal score. Text Top20 uses the existing instructed query and
uninstructed document embeddings and the same float32 exact-cosine contract
as the Qwen demo, without running an encoder or calling an external API.

Prepare on Vaipe with GPUs hidden and BLAS threads limited to two:

```
python scripts/build_modality_bundle.py --data-root /mnt/disk4/similar_cases_retrieval/data --output NEW_SERVER_OUTPUT
```

The stage verifies raw workbook/source fingerprints, estimates size before
export, enforces a 64 MiB budget, reads every output back and validates ranks,
scores, overlap, missingness, IDs and same-patient exclusion. Reports are stored
once in dictionaries; Top20 uses integer references rather than repeated text.
The bundle contains its own normalized values/reports/identities and provenance,
and is a cross-modal review artifact, so its server source output lives under
`data/modality_review_web/`, not the EHR-derived-data root. Copy the verified
bundle to H100 `WEB_DATA_ROOT/modalities/` and mount it read-only. Never add it
to Git. Searchable/paginated query catalogues expose all eligible original
queries. A report is displayed only for that embedding's confirmed selectors;
uncertain reports are labelled and never arbitrarily assigned.

A CPU-only `imaging` service reads frames directly from the existing canonical
DICOM ZIPs in `DICOM_DATA_ROOT` (default `/data/khangdp/scr/raw`). It exposes no
host port; authenticated backend routes proxy requests. ZIP members are read
without extraction, matched by exact PatientID/StudyUID/SeriesUID, sorted by
position/instance and deduplicated by SOP/frame. Header catalogues have a bounded
32-entry cache and two concurrent decoding slots. Source archives stay read-only;
no second copy or whole-cohort converted NPY dataset is created. The grayscale
source-series viewer is not the encoder's resampled/cropped input tensor.
Frame rendering includes CT rescale, MONOCHROME1 inversion, window/level and
preview/native dimensions. Missing archives/identity matches or unsupported
frames produce a visible error without changing the ranking or substituting
another series. Tests run via `python -m unittest test_server` in this service.
Frame selection uses the [pydicom pixel-array API](https://pydicom.github.io/pydicom/stable/reference/generated/pydicom.pixels.pixel_array.html)
with a file-like source and frame index, plus pinned decompression plugins.

Each modality review stores one 1–5 rating and note in the `modality_reviews`
SQLite namespace with history. Its key includes the bundle method SHA-256,
method, query and candidate IDs, keeping it separate from fusion reviews and
other modalities/model versions. Admins can export reviews for a query as
CSV/JSON. This is a review interface; original scores are not clinical relevance
probabilities, lab full-visit medians are retrospective, and 12 lab unit labels
remain `inferred_unverified`.
