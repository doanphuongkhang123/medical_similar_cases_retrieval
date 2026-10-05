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
