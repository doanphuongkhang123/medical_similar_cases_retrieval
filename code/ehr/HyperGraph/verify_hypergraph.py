"""Reopen and independently verify a generated HyperGraph artifact directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def resolve_raw_input(root: Path, manifest: dict[str, Any]) -> Path:
    recorded = Path(manifest["raw_input"]["path"])
    if recorded.is_file():
        return recorded

    layout_manifest_path = root.parent / "layout_manifest.json"
    if layout_manifest_path.is_file():
        layout = json.loads(layout_manifest_path.read_text(encoding="utf-8"))
        relocated = layout.get("path_relocations", {}).get(str(recorded))
        if relocated:
            candidate = Path(relocated)
            if candidate.is_file():
                return candidate

    canonical = root.parent / "raw" / recorded.name
    if canonical.is_file():
        return canonical
    return recorded


def verify_output(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((root / "audit" / "audit_summary.json").read_text(encoding="utf-8"))
    config = manifest["configuration"]

    raw_path = resolve_raw_input(root, manifest)
    require(raw_path.is_file(), f"Raw input is missing: {raw_path}")
    require(sha256_file(raw_path) == manifest["raw_input"]["sha256"], "Raw input SHA-256 mismatch")
    for artifact in manifest["artifacts"]:
        path = root / artifact["path"]
        require(path.is_file(), f"Artifact is missing: {artifact['path']}")
        require(path.stat().st_size == artifact["size_bytes"], f"Artifact size mismatch: {artifact['path']}")
        require(sha256_file(path) == artifact["sha256"], f"Artifact SHA-256 mismatch: {artifact['path']}")

    visits = pd.read_parquet(root / "cohort" / "visits.parquet")
    patients = pd.read_parquet(root / "cohort" / "patients.parquet")
    require(visits["visit_id"].is_unique, "visit_id is not unique")
    require(patients["patient_id"].is_unique, "patient_id is not unique")
    require(visits["hyperedge_index"].tolist() == list(range(len(visits))), "Hyperedge indices are not contiguous")
    require(set(visits["patient_id"]) == set(patients["patient_id"]), "Patient index does not cover cohort")
    require(
        visits.groupby("patient_id")["visit_id"].nunique().min() >= config["min_visits"],
        "A patient violates min_visits",
    )
    split_sets = {
        split: set(frame["patient_id"])
        for split, frame in visits.groupby("split", sort=False)
    }
    for left, left_ids in split_sets.items():
        for right, right_ids in split_sets.items():
            if left < right:
                require(not (left_ids & right_ids), f"Patient leakage between {left} and {right}")

    domain_names = {"diag": "diag_voc", "proc": "pro_voc", "med": "med_voc"}
    indexed: dict[str, pd.DataFrame] = {}
    vocabularies: dict[str, pd.DataFrame] = {}
    for domain in domain_names:
        vocabulary = pd.read_parquet(root / "vocabularies" / f"{domain}_vocabulary.parquet")
        memberships = pd.read_parquet(root / "cohort" / f"{domain}_memberships.parquet")
        incidence = np.load(root / "hypergraphs" / f"{domain}_incidence.npz")
        require(
            vocabulary["concept_index"].tolist() == list(range(len(vocabulary))),
            f"{domain} concept indices are not contiguous",
        )
        require(set(memberships["visit_id"]) == set(visits["visit_id"]), f"{domain} does not cover every visit")
        require(
            memberships[["concept_index", "hyperedge_index"]].duplicated().sum() == 0,
            f"{domain} has duplicate memberships",
        )
        require(incidence["shape"].tolist() == [len(vocabulary), len(visits)], f"{domain} incidence shape mismatch")
        npz_pairs = set(zip(incidence["row_indices"].tolist(), incidence["col_indices"].tolist()))
        table_pairs = set(zip(memberships["concept_index"].tolist(), memberships["hyperedge_index"].tolist()))
        require(npz_pairs == table_pairs, f"{domain} incidence and membership table disagree")
        require(np.isfinite(incidence["values"]).all(), f"{domain} incidence contains non-finite values")
        require(np.all(incidence["values"] == 1), f"{domain} incidence is not binary")
        indexed[domain] = memberships
        vocabularies[domain] = vocabulary

    with (root / "hypemed" / "records_final.pkl").open("rb") as stream:
        records = pickle.load(stream)
    with (root / "hypemed" / "voc_final.pkl").open("rb") as stream:
        voc = pickle.load(stream)
    with (root / "hypemed" / "ehr_adj_final.pkl").open("rb") as stream:
        ehr_adj = np.asarray(pickle.load(stream))
    require(len(records) == len(patients), "records patient count mismatch")
    require(sum(len(patient) for patient in records) == len(visits), "records visit count mismatch")
    for domain, voc_name in domain_names.items():
        require(len(voc[voc_name].word2idx) == len(vocabularies[domain]), f"{domain} voc size mismatch")
        require(
            set(voc[voc_name].word2idx.values()) == set(range(len(vocabularies[domain]))),
            f"{domain} pickle vocabulary indices are invalid",
        )
    for patient in records:
        require(len(patient) >= config["min_visits"], "records contains a short patient history")
        for visit in patient:
            require(len(visit) == 3 and all(visit), "records contains an empty or malformed visit")
            for domain_index, domain in enumerate(["diag", "proc", "med"]):
                require(
                    all(0 <= value < len(vocabularies[domain]) for value in visit[domain_index]),
                    f"records contains an out-of-range {domain} index",
                )
    expected_by_domain = {
        domain: frame.groupby("hyperedge_index")["concept_index"].apply(
            lambda values: sorted(set(int(value) for value in values))
        ).to_dict()
        for domain, frame in indexed.items()
    }
    for patient_index, patient_visits in visits.groupby("patient_index", sort=True):
        ordered = patient_visits.sort_values("visit_index_within_patient")
        require(int(patient_index) < len(records), "patient_index is outside records")
        record = records[int(patient_index)]
        require(len(record) == len(ordered), "Patient visit count differs between records and cohort table")
        for visit_record, edge_index in zip(record, ordered["hyperedge_index"]):
            edge = int(edge_index)
            for domain_index, domain in enumerate(["diag", "proc", "med"]):
                require(
                    visit_record[domain_index] == expected_by_domain[domain][edge],
                    f"records and {domain} memberships disagree at hyperedge {edge}",
                )
    require(ehr_adj.shape == (len(vocabularies["med"]), len(vocabularies["med"])), "EHR adjacency shape mismatch")
    require(np.array_equal(ehr_adj, ehr_adj.T), "EHR adjacency is not symmetric")
    require(np.all(np.diag(ehr_adj) == 0), "EHR adjacency diagonal is not zero")
    require(np.isfinite(ehr_adj).all(), "EHR adjacency contains non-finite values")
    require(np.all((ehr_adj == 0) | (ehr_adj == 1)), "EHR adjacency is not binary")
    require(not (root / "hypemed" / "ddi_A_final.pkl").exists(), "A DDI matrix was unexpectedly emitted")

    final = manifest["counts"]["final"]
    require(final == audit["final_counts"], "Manifest and audit final counts disagree")
    require(final["patients"] == len(patients), "Manifest patient count mismatch")
    require(final["visits"] == len(visits), "Manifest visit count mismatch")
    report = {
        "status": "passed",
        "root": str(root),
        "raw_input_path": str(raw_path),
        "raw_input_sha256": manifest["raw_input"]["sha256"],
        "artifact_count": len(manifest["artifacts"]),
        "patients": len(patients),
        "visits": len(visits),
        "vocabulary_sizes": {domain: len(frame) for domain, frame in vocabularies.items()},
        "membership_counts": {domain: len(frame) for domain, frame in indexed.items()},
        "ddi_matrix_present": False,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_output(args.root), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
