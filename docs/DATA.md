# Data contract — GT-BEHRT-Visit

**Dataset path (server only):** `/mnt/disk4/similar_cases_retrieval/data/thông tin bệnh án.xlsx`
**Graph unit:** one `SoBenhAn` = one visit graph.
**Baseline snapshot:** `full_visit` (retrospective retrieval only).

## Verified workbook links

| Source sheet | Visit key | Event key / link |
|---|---|---|
| `thông tin bệnh án` | `SoBenhAn` | one main visit row |
| `chỉ định DVKT` | `SoBenhAn` | `YeuCauChiTiet_Id` defines `ORDER` |
| `Thuốc` | `sobenhan` | `SoThuTuToa` defines `PRESCRIPTION` |
| `KQCLS` | `SoBenhAn` | `YeuCauChiTiet_Id` → `ORDER` |
| `Phẫu thuật thủ thuật` | inherited through `YeuCauChiTiet_Id` | `YeuCauChiTiet_Id` → `ORDER` → visit |

`SoVaoVien` is not used as the graph key. Join IDs are retained only for
lineage and graph edge construction; they are not model features.

## Feature and privacy policy

The initial structured baseline permits approved admission text-section names,
vitals, services, drugs/active ingredients, lab test/value/unit/time, and
procedure service/time. Raw text is normalized then hashed before the canonical
tables are written, and does not enter graph tensors in this version.

Direct identifiers and administrative fields are excluded, including names,
addresses, insurance numbers, clinicians, contacts, and administrative IDs.
Discharge diagnosis, outcome, post-treatment fields, and `MaICD`/`ICD_phu` are
also excluded from features pending confirmation that they are available at the
chosen observation snapshot.

## Split and leakage limitations

The current deterministic split is visit-disjoint (seed `20260812`, 70/15/15).
It is **not patient-disjoint**, because no approved pseudonymized patient ID has
been supplied. Vocabulary and numeric robust statistics are fitted on the train
visits only. A patient-disjoint split must replace this provisional split when
such an ID is available.

`first_24h` is supported by the code but should not be used until timestamp
precision has been audited. Query and candidate embeddings must always use the
same snapshot policy.
