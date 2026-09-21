"""Independent raw-workbook reader; no retrieval model or derived EHR imports."""
import socket
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from common import code_hashes, read_json, read_jsonl, sha256, write_json, write_jsonl

MAIN = "thông tin bệnh án"
# Agreed clinical narrative input; diagnosis codes remain separate per visit.
TEXT_FIELDS = ["TomTatBenhAn", "ChanDoanRaVien"]
MISSING = {"", "null", "none", "nan", "nat", "richeditcontrol1"}


def clean(value):
    value = " ".join(str(value).split()) if value is not None else ""
    return "" if value.casefold() in MISSING else value


def parse_date(value):
    if isinstance(value, datetime):
        return value.isoformat()
    value = clean(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            pass
    raise ValueError("Missing or unsupported visit date; inspect source on server")


def rows(sheet, required):
    iterator = sheet.iter_rows(values_only=True)
    header = list(next(iterator))
    for name in required:
        if header.count(name) != 1:
            raise ValueError(f"{sheet.title}: missing/ambiguous required column {name}")
    for rownum, values in enumerate(iterator, 2):
        if any(v is not None for v in values):
            yield rownum, dict(zip(header, values))


def prepare(workbook, output, max_visits=3, max_field_chars=None, max_text_chars=None):
    import openpyxl

    if not 1 <= max_visits <= 3:
        raise ValueError("Select one to three recent visits")
    if any(limit is not None and limit <= 0 for limit in (max_field_chars, max_text_chars)):
        raise ValueError("Explicit text limits must be positive")
    workbook, output = Path(workbook).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    normalized = output / "normalized"
    normalized.mkdir()
    source_hash = sha256(workbook)
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    visits, patients, field_counts = {}, defaultdict(list), Counter()
    counts = Counter()
    try:
        for rownum, row in rows(book[MAIN], ["SoBenhAn", "SoVaoVien", "NgayVaoVien", "NgayRaVien", "MaICD", "ICD_phu"] + TEXT_FIELDS):
            vid, pid = clean(row["SoBenhAn"]), clean(row["SoVaoVien"])
            if not vid or not pid or vid in visits:
                raise ValueError("Missing identity or duplicate visit in main sheet")
            sections = [{"sheet": MAIN, "row": rownum, "field": f, "text": clean(row[f])}
                        for f in TEXT_FIELDS if clean(row[f])]
            field_counts.update(x["field"] for x in sections)
            visit = {"visit_id": vid, "patient_id": pid, "source_row": rownum,
                     "admission": parse_date(row["NgayVaoVien"]), "discharge": parse_date(row["NgayRaVien"]),
                     "primary_icd": clean(row["MaICD"]), "secondary_icd": clean(row["ICD_phu"]),
                     "sections": sections, "reports": [], "procedures": []}
            if visit["discharge"] < visit["admission"]:
                raise ValueError("Discharge precedes admission")
            visits[vid] = visit
            patients[pid].append(visit)
        # Preserve full normalized text on this pipeline's own server path.
        write_jsonl(normalized / "visits.jsonl", visits.values())
    finally:
        book.close()

    profiles, mapping, audit = [], [], []
    for number, (pid, history) in enumerate(sorted(patients.items()), 1):
        profile_id = f"P{number:05d}"
        selected = sorted(history, key=lambda v: (v["admission"], v["visit_id"]), reverse=True)[:max_visits]
        profile, local_audit = make_profile(profile_id, selected, max_field_chars, max_text_chars)
        profiles.append(profile)
        mapping.append({"profile_id": profile_id, "patient_id": pid,
                        "visits": [{"visit_id": v["visit_id"], "source_row": v["source_row"], "admission": v["admission"]} for v in selected]})
        audit.append({"profile_id": profile_id, **local_audit})
    write_jsonl(output / "profiles.jsonl", profiles)
    write_jsonl(output / "identity_map.jsonl", mapping)
    write_jsonl(output / "profile_audit.jsonl", audit)
    if sha256(workbook) != source_hash:
        raise ValueError("Workbook changed during prepare; discard incomplete output")
    manifest = {"schema_version": 2, "profile_contract": "summary_discharge_v1",
                "status": "prepared_for_local_qwen3_embedding", "host": socket.gethostname(),
                "created_at": datetime.now(timezone.utc).isoformat(), "raw_input": str(workbook), "raw_sha256": source_hash,
                "unit": "patient", "scope": "retrospective_full_visit", "max_visits": max_visits,
                "visit_order": "admission_desc_then_visit_id_desc", "max_field_chars": max_field_chars,
                "max_text_chars": max_text_chars, "text_fields": TEXT_FIELDS,
                "report_fields": [], "procedure_fields": [],
                "patients": len(profiles), "visits": len(visits), "field_counts": dict(field_counts),
                "counts": dict(counts), "profiles_with_omission": sum(x["omitted_sections"] > 0 for x in audit),
                "profiles_with_truncation": sum(x["truncated_sections"] > 0 for x in audit),
                "external_data_transfer": False, "code_sha256": code_hashes(),
                "artifacts": {str(p.relative_to(output)): sha256(p) for p in sorted(output.rglob("*.jsonl"))}}
    write_json(output / "manifest.json", manifest)
    return manifest


def make_profile(profile_id, selected, max_field_chars, max_text_chars):
    profile = {"patient_id": profile_id, "visits": []}
    audit = {"source_sections": 0, "kept_sections": 0, "omitted_sections": 0, "truncated_sections": 0, "duplicate_sections": 0}
    # Preserve full text by default. Explicit legacy caps remain auditable.
    per_visit = None if max_text_chars is None else max_text_chars // len(selected)
    if per_visit is not None and per_visit < 1:
        raise ValueError("Text budget cannot represent every retained visit")
    for i, v in enumerate(selected, 1):
        incomplete_before = audit["omitted_sections"] + audit["truncated_sections"]
        visit = {"recency": i, "icd_primary": v["primary_icd"], "icd_secondary": v["secondary_icd"], "evidence": []}
        # Keep the evidence layout compatible with older profile bundles.
        groups = [v["sections"], v["reports"], v["procedures"]]
        ordered = [group[n] for n in range(max(map(len, groups), default=0)) for group in groups if n < len(group)]
        seen, used = set(), 0
        for j, item in enumerate(ordered, 1):
            audit["source_sections"] += 1
            identity = (item["field"], item["text"], item.get("label", ""))
            if identity in seen:
                audit["duplicate_sections"] += 1
                continue
            seen.add(identity)
            limits = [len(item["text"])]
            if max_field_chars is not None:
                limits.append(max_field_chars)
            if per_visit is not None:
                limits.append(per_visit - used)
            take = min(limits)
            if take <= 0:
                audit["omitted_sections"] += 1
                continue
            text = item["text"][:take]
            truncated = take < len(item["text"])
            # Evidence IDs encode visit and source position, but no raw patient/visit IDs.
            visit["evidence"].append({"id": f"v{i}e{j}", "field": item["field"], "text": text,
                                      "source": {k: item[k] for k in ("sheet", "row")},
                                      "label": item.get("label", ""), "truncated": truncated})
            used += take
            audit["kept_sections"] += 1
            audit["truncated_sections"] += int(truncated)
        visit["text_incomplete"] = audit["omitted_sections"] + audit["truncated_sections"] > incomplete_before
        profile["visits"].append(visit)
    return profile, audit


def load_profiles(root):
    root = Path(root)
    manifest = read_json(root / "manifest.json")
    expected = manifest["artifacts"]["profiles.jsonl"]
    if sha256(root / "profiles.jsonl") != expected:
        raise ValueError("Profiles hash mismatch; rebuild or re-manifest reviewed data")
    values = read_jsonl(root / "profiles.jsonl")
    profiles = {x["patient_id"]: x for x in values}
    if len(profiles) != len(values) or len(values) != manifest["patients"]:
        raise ValueError("Duplicate/missing profile identity")
    return profiles, manifest
