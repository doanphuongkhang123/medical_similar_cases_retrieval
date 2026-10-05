# Full workbook at visit level

Server-only export of all five sheets of the canonical raw EHR workbook to a
new XLSX. The main `Visits` sheet has exactly one row per source `SoBenhAn`.
All 114 encounter fields are retained, including duplicate header occurrences.
Orders, medicines, each distinct KQCLS indicator and performed procedures keep
every source row as JSON arrays. `Cau_truc` gives their field order; source Excel
row number is always the first array element. Long values have adjacent
`::__phan_N` columns: concatenate in numerical order before parsing JSON.
No results are averaged, truncated, deduplicated or substituted.

Read the raw workbook directly into this run's own `structured/source.sqlite`.
That snapshot stores all source values/types and order-link identities. Link
procedures only through a unique `YeuCauChiTiet_Id` in orders/results. Unresolved
and out-of-cohort rows remain in `Ngoai_le`, with reason and candidate visits;
they are never assigned to a visit by name, age or presumed meaning of `ma_lk`.
Demographic display columns contain only unique source-supported values; gender
codes from orders and gender labels from medicines stay separate. All conflicting
values also remain in the complete source records.

New files use Excel defaults, with only practical column widths, header wrapping,
filters, date formats and frozen identifiers. Clinical data never leaves Vaipe.
The artifact-tool desktop runtime is unavailable on the lab host; openpyxl is
used there for streaming export and independent saved-file verification.

```sh
PY=/mnt/disk1/khangdp/conda_envs/scr_env/bin/python
RUN=/mnt/disk4/similar_cases_retrieval/data/ehr/visit_workbook/RUN_ID
CUDA_VISIBLE_DEVICES="" "$PY" export.py prepare --output "$RUN"
# Review preflight.json before authoring. The explicit limit is an output budget.
CUDA_VISIBLE_DEVICES="" "$PY" export.py export --output "$RUN" --max-bytes 150000000
CUDA_VISIBLE_DEVICES="" "$PY" -m unittest discover -s . -p 'test_export.py'
```

The manifest records raw path/SHA-256, normalized snapshot/schema hashes,
source and output counts, exact row membership/content verification, output
size/hash, host, script hash and the command. No clinical values appear in logs.
Do not use the old partial measurements CSV as input to this exporter.
