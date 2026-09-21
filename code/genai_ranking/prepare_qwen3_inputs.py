#!/usr/bin/env python3
"""Build and verify the local patient-text bundle used by Qwen3 embeddings.

The builder starts from the canonical raw workbook, creates its own normalized
source tables, and writes one pseudonymous patient-level text row. It never
reads an API key, calls a hosted inference endpoint, or sends clinical data.
Qwen token lengths are measured later with the pinned model tokenizer during
the mandatory representative CUDA smoke.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import socket
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from common import read_json, read_jsonl, sha256, write_json, write_jsonl
from profiles import load_profiles, prepare as prepare_profiles


OUTPUT_FILE = "embedding_inputs.jsonl"
FIELD_LABELS = {
    "TomTatBenhAn": "Tóm tắt bệnh án",
    "ChanDoanRaVien": "Chẩn đoán ra viện",
}


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def serialize_profile(profile: dict) -> tuple[str, Counter]:
    """Return encoder text plus counts; never include IDs, dates, or rows."""
    visits = profile.get("visits")
    if not isinstance(visits, list) or not 1 <= len(visits) <= 3:
        raise ValueError("Each patient must contain one to three visits")
    blocks, counts = [], Counter()
    for index, visit in enumerate(visits, 1):
        if visit.get("recency") != index:
            raise ValueError("Visits must be ordered newest first with sequential recency")
        heading = f"LẦN KHÁM {index}" + (" (GẦN NHẤT)" if index == 1 else "")
        lines = [heading]
        for key, label in (("icd_primary", "ICD chính"), ("icd_secondary", "ICD phụ")):
            value = str(visit.get(key, "")).strip()
            if value:
                lines.append(f"{label}: {value}")
                counts[key] += 1
        evidence = visit.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("Visit evidence must be a list")
        for item in evidence:
            field = item.get("field")
            if field not in FIELD_LABELS:
                raise ValueError(f"Unexpected encoder field {field}")
            value = str(item.get("text", "")).strip()
            if value:
                lines.append(f"{FIELD_LABELS[field]}: {value}")
                counts[field] += 1
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    if not blocks:
        raise ValueError(f"Patient {profile.get('patient_id', '<unknown>')} has no encoder content")
    return "\n\n".join(blocks), counts


def _summarize(values: list[int]) -> dict[str, int]:
    if not values:
        raise ValueError("Cannot summarize an empty input bundle")
    ordered = sorted(values)

    def percentile(value: int) -> int:
        index = max(0, (len(ordered) * value + 99) // 100 - 1)
        return ordered[index]

    return {
        "min": ordered[0],
        "p50": percentile(50),
        "p95": percentile(95),
        "max": ordered[-1],
        "total": sum(ordered),
    }


def prepare(workbook: Path, output: Path) -> dict:
    workbook, output = Path(workbook).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_root = output / "source_profiles"
    source_manifest = prepare_profiles(workbook, source_root, max_visits=3)
    profiles, _ = load_profiles(source_root)

    rows, character_counts = [], []
    field_counts = Counter()
    for patient_id in sorted(profiles):
        if not re.fullmatch(r"P\d{5}", patient_id):
            raise ValueError(f"Unexpected pseudonymous patient ID {patient_id}")
        text, counts = serialize_profile(profiles[patient_id])
        rows.append({
            "patient_id": patient_id,
            "visit_count": len(profiles[patient_id]["visits"]),
            "embedding_text": text,
            "input_sha256": text_sha256(text),
        })
        character_counts.append(len(text))
        field_counts.update(counts)

    destination = output / OUTPUT_FILE
    write_jsonl(destination, rows)
    manifest = {
        "schema_version": 2,
        "input_contract": "qwen3_patient_icd_summary_discharge_v1",
        "status": "prepared_for_local_qwen3_embedding",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "raw_input": str(workbook),
        "raw_sha256": source_manifest["raw_sha256"],
        "unit": "patient",
        "patient_id": "pseudonymous Pxxxxx linkage key; excluded from embedding_text",
        "visit_order": "newest_to_oldest",
        "max_visits": 3,
        "embedding_fields": ["MaICD", "ICD_phu", "TomTatBenhAn", "ChanDoanRaVien"],
        "excluded_from_embedding_text": ["patient_id", "raw patient/visit IDs", "dates", "source rows"],
        "patients": len(rows),
        "visits_retained": sum(row["visit_count"] for row in rows),
        "field_occurrences": dict(sorted(field_counts.items())),
        "input_characters": _summarize(character_counts),
        "output_file": OUTPUT_FILE,
        "output_sha256": sha256(destination),
        "source_profiles_manifest": "source_profiles/manifest.json",
        "source_profiles_manifest_sha256": sha256(source_root / "manifest.json"),
        "qwen_token_audit_stage": "representative_smoke",
        "clinical_data_sent": False,
        "api_calls": 0,
        "external_data_transfer": False,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def verify(output: Path) -> dict:
    """Verify both the current bundle and the already-completed v1 artifact."""
    output = Path(output).resolve()
    manifest = read_json(output / "manifest.json")
    if manifest.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported Qwen3 input schema")
    destination = output / manifest["output_file"]
    if sha256(destination) != manifest["output_sha256"]:
        raise ValueError("Qwen3 input hash mismatch")
    source_manifest_path = output / manifest["source_profiles_manifest"]
    if sha256(source_manifest_path) != manifest["source_profiles_manifest_sha256"]:
        raise ValueError("Source profile manifest hash mismatch")
    source_manifest = read_json(source_manifest_path)
    if source_manifest["raw_sha256"] != manifest["raw_sha256"]:
        raise ValueError("Raw workbook lineage mismatch")

    rows = read_jsonl(destination)
    ids = [row.get("patient_id") for row in rows]
    if len(rows) != manifest["patients"] or ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError("Patient count, order, or uniqueness mismatch")
    character_counts = []
    for row in rows:
        if set(row) != {"patient_id", "visit_count", "embedding_text", "input_sha256"}:
            raise ValueError("Unexpected Qwen3 input columns")
        if not re.fullmatch(r"P\d{5}", row["patient_id"]):
            raise ValueError("Invalid pseudonymous patient ID")
        if type(row["visit_count"]) is not int or not 1 <= row["visit_count"] <= 3:
            raise ValueError("Invalid visit count")
        text = row["embedding_text"]
        if not isinstance(text, str) or not text or text_sha256(text) != row["input_sha256"]:
            raise ValueError("Empty or modified Qwen3 input text")
        character_counts.append(len(text))
    if "input_characters" in manifest and _summarize(character_counts) != manifest["input_characters"]:
        raise ValueError("Character statistics mismatch")
    return {
        "status": "verified",
        "patients": len(rows),
        "visits_retained": sum(row["visit_count"] for row in rows),
        "raw_sha256": manifest["raw_sha256"],
        "clinical_data_sent": False,
        "api_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("--workbook", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.workbook, args.output) if args.command == "prepare" else verify(args.output)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
