"""Build a HypeMed-style three-domain hypergraph dataset from the raw EHR workbook.

The pipeline starts from the canonical workbook and writes all normalized tables
inside its own output directory. It intentionally does not fabricate ATC codes or
a drug-drug interaction graph: medicine and procedure concepts remain explicit
local vocabularies until reviewed mappings are available.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import platform
import re
import socket
import unicodedata
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd


SHEETS = {
    "visits": "thông tin bệnh án",
    "procedures": "chỉ định DVKT",
    "medicines": "Thuốc",
}
EMPTY_TEXT = {"", "nan", "nat", "none", "null"}
DIAGNOSIS_SPLIT_RE = re.compile(r"[;,|]+")


def clean(value: Any) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()
    return "" if text.casefold() in EMPTY_TEXT else text


def clean_key(value: Any) -> str:
    text = clean(value)
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def normalized_label(value: Any) -> str:
    return clean(value).casefold()


def canonical_icd(value: Any) -> str:
    return re.sub(r"[.\s]+", "", clean(value).upper())


def local_token(prefix: str, normalized_value: str) -> str:
    digest = hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def parse_time(series: pd.Series) -> pd.Series:
    def one(value: Any) -> pd.Timestamp:
        if value is None or value is pd.NA or value is pd.NaT:
            return pd.NaT
        if isinstance(value, pd.Timestamp):
            return value
        raw = clean(value)
        compact = re.sub(r"\.0+$", "", raw)
        if re.fullmatch(r"\d{12}", compact):
            return pd.to_datetime(compact, format="%Y%m%d%H%M", errors="coerce")
        if re.fullmatch(r"\d{8}", compact):
            return pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
        if isinstance(value, (int, float)) and 20_000 <= float(value) <= 60_000:
            return pd.to_datetime(float(value), unit="D", origin="1899-12-30", errors="coerce")
        return pd.to_datetime(value, errors="coerce")

    return series.map(one)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_source_frames(workbook: Path) -> dict[str, pd.DataFrame]:
    excel = pd.ExcelFile(workbook, engine="openpyxl")
    missing = set(SHEETS.values()) - set(excel.sheet_names)
    if missing:
        raise ValueError(f"Missing required sheets: {sorted(missing)}")
    return {
        "visits": pd.read_excel(
            excel,
            sheet_name=SHEETS["visits"],
            usecols=["SoBenhAn", "SoVaoVien", "NgayVaoVien", "NgayRaVien", "MaICD", "ICD_phu"],
            dtype=object,
        ),
        "procedures": pd.read_excel(
            excel,
            sheet_name=SHEETS["procedures"],
            usecols=["SoBenhAn", "YeuCauChiTiet_Id", "TenDichVu", "NgayYeuCau"],
            dtype=object,
        ),
        "medicines": pd.read_excel(
            excel,
            sheet_name=SHEETS["medicines"],
            usecols=["sobenhan", "TenHoatChat", "TenDuoc", "NgayKham", "LyDoTraThuoc"],
            dtype=object,
        ),
    }


def build_visits(raw: pd.DataFrame) -> pd.DataFrame:
    visits = pd.DataFrame(
        {
            "patient_id": raw["SoVaoVien"].map(clean_key),
            "visit_id": raw["SoBenhAn"].map(clean_key),
            "admission_time": parse_time(raw["NgayVaoVien"]),
            "discharge_time": parse_time(raw["NgayRaVien"]),
        }
    )
    if visits["patient_id"].eq("").any() or visits["visit_id"].eq("").any():
        raise ValueError("SoVaoVien and SoBenhAn must be non-empty")
    if visits["visit_id"].duplicated().any():
        duplicates = visits.loc[visits["visit_id"].duplicated(), "visit_id"].head(5).tolist()
        raise ValueError(f"SoBenhAn must be unique; examples: {duplicates}")
    if visits.groupby("visit_id")["patient_id"].nunique().max() != 1:
        raise ValueError("A visit_id maps to multiple patient_id values")
    invalid_time = (
        visits["admission_time"].notna()
        & visits["discharge_time"].notna()
        & visits["discharge_time"].lt(visits["admission_time"])
    )
    if invalid_time.any():
        raise ValueError(f"Found {int(invalid_time.sum())} visits with discharge before admission")
    return visits


def build_diagnoses(raw: pd.DataFrame, visits: pd.DataFrame) -> pd.DataFrame:
    visit_to_patient = dict(zip(visits["visit_id"], visits["patient_id"]))
    rows: list[dict[str, Any]] = []
    for item in raw.itertuples(index=False):
        visit_id = clean_key(item.SoBenhAn)
        patient_id = visit_to_patient.get(visit_id, "")
        if not patient_id:
            continue
        codes: list[tuple[str, str]] = []
        primary = canonical_icd(item.MaICD)
        if primary:
            codes.append((primary, "primary"))
        for value in DIAGNOSIS_SPLIT_RE.split(clean(item.ICD_phu)):
            code = canonical_icd(value)
            if code:
                codes.append((code, "secondary"))
        for code, diagnosis_type in codes:
            rows.append(
                {
                    "patient_id": patient_id,
                    "visit_id": visit_id,
                    "model_token": code,
                    "concept_label": code,
                    "source_vocabulary": "ICD_VERSION_UNVERIFIED",
                    "diagnosis_type": diagnosis_type,
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("No diagnosis codes were produced")
    type_rank = frame["diagnosis_type"].map({"primary": 0, "secondary": 1}).fillna(9)
    frame = frame.assign(_type_rank=type_rank).sort_values(
        ["patient_id", "visit_id", "model_token", "_type_rank"], kind="stable"
    )
    return frame.drop_duplicates(["visit_id", "model_token"]).drop(columns="_type_rank").reset_index(drop=True)


def build_procedures(raw: pd.DataFrame, visits: pd.DataFrame) -> pd.DataFrame:
    visit_to_patient = dict(zip(visits["visit_id"], visits["patient_id"]))
    frame = pd.DataFrame(
        {
            "visit_id": raw["SoBenhAn"].map(clean_key),
            "source_event_id": raw["YeuCauChiTiet_Id"].map(clean_key),
            "concept_label": raw["TenDichVu"].map(clean),
            "event_time": parse_time(raw["NgayYeuCau"]),
        }
    )
    frame["patient_id"] = frame["visit_id"].map(visit_to_patient).fillna("")
    frame["normalized_concept"] = frame["concept_label"].map(normalized_label)
    frame = frame[(frame["patient_id"] != "") & (frame["normalized_concept"] != "")].copy()
    frame["model_token"] = frame["normalized_concept"].map(lambda value: local_token("LOCAL_PROC", value))
    grouped = (
        frame.sort_values(["patient_id", "visit_id", "model_token", "event_time"], kind="stable")
        .groupby(["patient_id", "visit_id", "model_token"], as_index=False, sort=False)
        .agg(
            concept_label=("concept_label", "first"),
            event_time=("event_time", "min"),
            source_event_count=("source_event_id", "nunique"),
        )
    )
    grouped["source_vocabulary"] = "LOCAL_SERVICE_NAME"
    return grouped


def build_medicines(raw: pd.DataFrame, visits: pd.DataFrame, include_returned: bool) -> tuple[pd.DataFrame, int]:
    visit_to_patient = dict(zip(visits["visit_id"], visits["patient_id"]))
    ingredient = raw["TenHoatChat"].map(clean)
    drug_name = raw["TenDuoc"].map(clean)
    frame = pd.DataFrame(
        {
            "visit_id": raw["sobenhan"].map(clean_key),
            "active_ingredient": ingredient,
            "drug_name": drug_name,
            "concept_label": ingredient.where(ingredient.ne(""), drug_name),
            "event_time": parse_time(raw["NgayKham"]),
            "returned": raw["LyDoTraThuoc"].map(clean).ne(""),
        }
    )
    returned_rows = int(frame["returned"].sum())
    if not include_returned:
        frame = frame[~frame["returned"]].copy()
    frame["patient_id"] = frame["visit_id"].map(visit_to_patient).fillna("")
    frame["normalized_concept"] = frame["concept_label"].map(normalized_label)
    frame = frame[(frame["patient_id"] != "") & (frame["normalized_concept"] != "")].copy()
    frame["model_token"] = frame["normalized_concept"].map(lambda value: local_token("LOCAL_MED", value))
    grouped = (
        frame.sort_values(["patient_id", "visit_id", "model_token", "event_time"], kind="stable")
        .groupby(["patient_id", "visit_id", "model_token"], as_index=False, sort=False)
        .agg(
            concept_label=("concept_label", "first"),
            active_ingredient=("active_ingredient", "first"),
            drug_name=("drug_name", "first"),
            event_time=("event_time", "min"),
            source_row_count=("model_token", "size"),
        )
    )
    grouped["source_vocabulary"] = "LOCAL_ACTIVE_INGREDIENT_OR_DRUG_NAME"
    return grouped, returned_rows


def top_tokens(frame: pd.DataFrame, limit: int) -> set[str]:
    frequencies = (
        frame.groupby("model_token")["visit_id"]
        .nunique()
        .rename("visit_frequency")
        .reset_index()
        .sort_values(["visit_frequency", "model_token"], ascending=[False, True], kind="stable")
    )
    if limit > 0:
        frequencies = frequencies.head(limit)
    return set(frequencies["model_token"])


def patient_order_key(patient_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}\0{patient_id}".encode("utf-8")).hexdigest()


def select_cohort(
    visits: pd.DataFrame,
    diagnoses: pd.DataFrame,
    procedures: pd.DataFrame,
    medicines: pd.DataFrame,
    min_visits: int,
    top_diagnoses: int,
    top_procedures: int,
    top_medicines: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    selected = {
        "diag": diagnoses[diagnoses["model_token"].isin(top_tokens(diagnoses, top_diagnoses))].copy(),
        "proc": procedures[procedures["model_token"].isin(top_tokens(procedures, top_procedures))].copy(),
        "med": medicines[medicines["model_token"].isin(top_tokens(medicines, top_medicines))].copy(),
    }
    eligible = set(selected["diag"]["visit_id"])
    eligible &= set(selected["proc"]["visit_id"])
    eligible &= set(selected["med"]["visit_id"])
    eligible_visits = visits[visits["visit_id"].isin(eligible)].copy()
    counts = eligible_visits.groupby("patient_id")["visit_id"].nunique()
    kept_patients = set(counts[counts >= min_visits].index)
    cohort = eligible_visits[eligible_visits["patient_id"].isin(kept_patients)].copy()
    cohort["_patient_order"] = cohort["patient_id"].map(lambda value: patient_order_key(value, seed))
    cohort["_missing_time"] = cohort["admission_time"].isna().astype(int)
    cohort = cohort.sort_values(
        ["_patient_order", "patient_id", "_missing_time", "admission_time", "visit_id"], kind="stable"
    ).reset_index(drop=True)
    patient_index = {patient_id: index for index, patient_id in enumerate(cohort["patient_id"].drop_duplicates())}
    cohort["patient_index"] = cohort["patient_id"].map(patient_index).astype(int)
    cohort["visit_index_within_patient"] = cohort.groupby("patient_id", sort=False).cumcount().astype(int)
    cohort["hyperedge_index"] = np.arange(len(cohort), dtype=np.int64)
    n_patients = len(patient_index)
    train_end = int(n_patients * 2 / 3)
    remaining = n_patients - train_end
    test_end = train_end + int(remaining / 2)
    cohort["split"] = np.select(
        [cohort["patient_index"] < train_end, cohort["patient_index"] < test_end],
        ["train", "test"],
        default="validation",
    )
    cohort = cohort.drop(columns=["_patient_order", "_missing_time"])
    kept_visits = set(cohort["visit_id"])
    for domain in selected:
        selected[domain] = selected[domain][selected[domain]["visit_id"].isin(kept_visits)].copy()
    audit = {
        "eligible_visits_before_min_visits": int(len(eligible_visits)),
        "eligible_patients_before_min_visits": int(eligible_visits["patient_id"].nunique()),
        "patients_removed_for_fewer_than_min_eligible_visits": int((counts < min_visits).sum()),
        "cohort_patients": int(cohort["patient_id"].nunique()),
        "cohort_visits": int(len(cohort)),
    }
    return cohort, selected, audit


def make_vocabulary(frame: pd.DataFrame) -> tuple[pd.DataFrame, SimpleNamespace]:
    frequency = (
        frame.groupby("model_token")["visit_id"]
        .nunique()
        .rename("visit_frequency")
        .reset_index()
    )
    labels = frame.sort_values(["model_token", "concept_label"], kind="stable").drop_duplicates("model_token")
    vocabulary = labels[["model_token", "concept_label", "source_vocabulary"]].merge(
        frequency, on="model_token", how="left"
    )
    vocabulary = vocabulary.sort_values(
        ["visit_frequency", "model_token"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)
    vocabulary.insert(0, "concept_index", np.arange(len(vocabulary), dtype=np.int64))
    word2idx = dict(zip(vocabulary["model_token"], vocabulary["concept_index"].astype(int)))
    idx2word = {index: word for word, index in word2idx.items()}
    return vocabulary, SimpleNamespace(word2idx=word2idx, idx2word=idx2word)


def attach_indices(frame: pd.DataFrame, cohort: pd.DataFrame, vocabulary: pd.DataFrame) -> pd.DataFrame:
    result = frame.merge(
        cohort[["patient_id", "visit_id", "patient_index", "visit_index_within_patient", "hyperedge_index", "split"]],
        on=["patient_id", "visit_id"],
        how="inner",
        validate="many_to_one",
    ).merge(
        vocabulary[["model_token", "concept_index"]], on="model_token", how="inner", validate="many_to_one"
    )
    return result.sort_values(["hyperedge_index", "concept_index"], kind="stable").reset_index(drop=True)


def build_records(
    cohort: pd.DataFrame,
    indexed: dict[str, pd.DataFrame],
) -> list[list[list[list[int]]]]:
    domain_maps: dict[str, dict[int, list[int]]] = {}
    for domain, frame in indexed.items():
        grouped = frame.groupby("hyperedge_index", sort=False)["concept_index"].apply(
            lambda values: sorted(set(int(value) for value in values))
        )
        domain_maps[domain] = grouped.to_dict()
    records: list[list[list[list[int]]]] = []
    for _, patient_visits in cohort.groupby("patient_index", sort=True):
        patient: list[list[list[int]]] = []
        for edge_index in patient_visits.sort_values("visit_index_within_patient")["hyperedge_index"]:
            edge = int(edge_index)
            admission = [
                domain_maps["diag"][edge],
                domain_maps["proc"][edge],
                domain_maps["med"][edge],
            ]
            if any(not values for values in admission):
                raise ValueError(f"Empty domain in hyperedge {edge}")
            patient.append(admission)
        records.append(patient)
    return records


def write_incidence(path: Path, frame: pd.DataFrame, n_nodes: int, n_edges: int) -> None:
    rows = frame["concept_index"].to_numpy(dtype=np.int64)
    cols = frame["hyperedge_index"].to_numpy(dtype=np.int64)
    if len(rows) != len(set(zip(rows.tolist(), cols.tolist()))):
        raise ValueError(f"Duplicate node-hyperedge memberships for {path.name}")
    np.savez_compressed(
        path,
        row_indices=rows,
        col_indices=cols,
        values=np.ones(len(rows), dtype=np.uint8),
        shape=np.asarray([n_nodes, n_edges], dtype=np.int64),
    )


def medication_cooccurrence(records: list[list[list[list[int]]]], medication_count: int) -> np.ndarray:
    adjacency = np.zeros((medication_count, medication_count), dtype=np.uint8)
    for patient in records:
        for visit in patient:
            for left, right in combinations(sorted(set(visit[2])), 2):
                adjacency[left, right] = 1
                adjacency[right, left] = 1
    return adjacency


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_outputs(
    output: Path,
    workbook: Path,
    frames: dict[str, pd.DataFrame],
    config: dict[str, Any],
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}")
    structured_dir = output / "structured"
    cohort_dir = output / "cohort"
    vocab_dir = output / "vocabularies"
    hypergraph_dir = output / "hypergraphs"
    hypemed_dir = output / "hypemed"
    audit_dir = output / "audit"
    for directory in [structured_dir, cohort_dir, vocab_dir, hypergraph_dir, hypemed_dir, audit_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    visits = build_visits(frames["visits"])
    diagnoses = build_diagnoses(frames["visits"], visits)
    procedures = build_procedures(frames["procedures"], visits)
    medicines, returned_rows = build_medicines(
        frames["medicines"], visits, include_returned=config["include_returned_medicines"]
    )
    visits.to_parquet(structured_dir / "visits.parquet", index=False)
    diagnoses.to_parquet(structured_dir / "diagnoses.parquet", index=False)
    procedures.to_parquet(structured_dir / "procedures.parquet", index=False)
    medicines.to_parquet(structured_dir / "medicines.parquet", index=False)

    cohort, selected, cohort_audit = select_cohort(
        visits=visits,
        diagnoses=diagnoses,
        procedures=procedures,
        medicines=medicines,
        min_visits=config["min_visits"],
        top_diagnoses=config["top_diagnoses"],
        top_procedures=config["top_procedures"],
        top_medicines=config["top_medicines"],
        seed=config["seed"],
    )
    cohort.to_parquet(cohort_dir / "visits.parquet", index=False)
    patient_index = (
        cohort[["patient_id", "patient_index", "split"]]
        .drop_duplicates()
        .sort_values("patient_index")
        .reset_index(drop=True)
    )
    patient_index.to_parquet(cohort_dir / "patients.parquet", index=False)

    indexed: dict[str, pd.DataFrame] = {}
    vocab_objects: dict[str, SimpleNamespace] = {}
    voc_names = {"diag": "diag_voc", "proc": "pro_voc", "med": "med_voc"}
    for domain in ["diag", "proc", "med"]:
        vocabulary, voc_object = make_vocabulary(selected[domain])
        indexed[domain] = attach_indices(selected[domain], cohort, vocabulary)
        vocab_objects[voc_names[domain]] = voc_object
        vocabulary.to_parquet(vocab_dir / f"{domain}_vocabulary.parquet", index=False)
        indexed[domain].to_parquet(cohort_dir / f"{domain}_memberships.parquet", index=False)
        write_incidence(
            hypergraph_dir / f"{domain}_incidence.npz",
            indexed[domain],
            n_nodes=len(vocabulary),
            n_edges=len(cohort),
        )

    records = build_records(cohort, indexed)
    with (hypemed_dir / "records_final.pkl").open("wb") as stream:
        pickle.dump(records, stream, protocol=pickle.HIGHEST_PROTOCOL)
    with (hypemed_dir / "voc_final.pkl").open("wb") as stream:
        pickle.dump(vocab_objects, stream, protocol=pickle.HIGHEST_PROTOCOL)
    ehr_adj = medication_cooccurrence(records, len(vocab_objects["med_voc"].word2idx))
    with (hypemed_dir / "ehr_adj_final.pkl").open("wb") as stream:
        pickle.dump(ehr_adj, stream, protocol=pickle.HIGHEST_PROTOCOL)
    write_json(
        hypemed_dir / "compatibility.json",
        {
            "records_layout": "records[patient][visit] == [diagnosis_ids, procedure_ids, medication_ids]",
            "structurally_compatible_with_hypemed": True,
            "direct_training_compatible": False,
            "blocking_reasons": [
                "Medication concepts are local active-ingredient/drug-name tokens, not reviewed ATC mappings.",
                "A drug-drug interaction adjacency matrix is not available and is intentionally not fabricated.",
                "Procedure concepts are local service-name tokens without a standard hierarchy.",
                "HypeMed model configuration must derive vocabulary sizes instead of assuming med_sz=131.",
            ],
            "ddi_matrix_present": False,
        },
    )

    raw_counts = {
        "patients": int(visits["patient_id"].nunique()),
        "visits": int(visits["visit_id"].nunique()),
        "diagnosis_visit_concepts": int(len(diagnoses)),
        "diagnosis_concepts": int(diagnoses["model_token"].nunique()),
        "procedure_visit_concepts": int(len(procedures)),
        "procedure_concepts": int(procedures["model_token"].nunique()),
        "medicine_visit_concepts": int(len(medicines)),
        "medicine_concepts": int(medicines["model_token"].nunique()),
        "source_returned_medicine_rows": returned_rows,
    }
    final_counts = {
        "patients": int(cohort["patient_id"].nunique()),
        "visits": int(len(cohort)),
        "diagnosis_concepts": len(vocab_objects["diag_voc"].word2idx),
        "procedure_concepts": len(vocab_objects["pro_voc"].word2idx),
        "medicine_concepts": len(vocab_objects["med_voc"].word2idx),
        "diagnosis_memberships": int(len(indexed["diag"])),
        "procedure_memberships": int(len(indexed["proc"])),
        "medicine_memberships": int(len(indexed["med"])),
        "medication_cooccurrence_undirected_edges": int(np.triu(ehr_adj, k=1).sum()),
        "split_patients": {
            key: int(value)
            for key, value in patient_index.groupby("split")["patient_id"].nunique().sort_index().items()
        },
        "split_visits": {
            key: int(value)
            for key, value in cohort.groupby("split")["visit_id"].nunique().sort_index().items()
        },
    }
    audit = {
        "raw_counts": raw_counts,
        "cohort_selection": cohort_audit,
        "final_counts": final_counts,
        "checks": {
            "one_patient_per_visit": bool(cohort.groupby("visit_id")["patient_id"].nunique().max() == 1),
            "all_patients_meet_min_visits": bool(
                cohort.groupby("patient_id")["visit_id"].nunique().min() >= config["min_visits"]
            ),
            "all_visits_have_all_domains": bool(
                all(set(cohort["visit_id"]) == set(frame["visit_id"]) for frame in indexed.values())
            ),
            "contiguous_hyperedge_indices": bool(
                cohort["hyperedge_index"].tolist() == list(range(len(cohort)))
            ),
            "ddi_matrix_intentionally_absent": True,
        },
    }
    write_json(audit_dir / "audit_summary.json", audit)

    artifacts = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts.append(
                {
                    "path": str(path.relative_to(output)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    manifest = {
        "pipeline": "HyperGraph HypeMed-style data preparation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "raw_input": {
            "path": str(workbook),
            "sha256": sha256_file(workbook),
            "size_bytes": workbook.stat().st_size,
        },
        "code": {
            "entrypoint": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "configuration": config,
        "schema": {
            "patient_id": "SoVaoVien",
            "visit_id": "SoBenhAn",
            "service_event_id": "YeuCauChiTiet_Id",
            "domains": ["diagnosis", "procedure", "medication"],
            "visit_representation": "one hyperedge per visit in each separate domain hypergraph",
        },
        "semantic_limitations": {
            "diagnosis_vocabulary": "ICD strings retained, ICD version not independently verified",
            "procedure_vocabulary": "hashed local DVKT service-request names; not curated billed procedure codes",
            "medication_vocabulary": "hashed local active ingredient, fallback local drug name",
            "ddi_graph": "not available; no zero/fabricated DDI matrix was emitted",
        },
        "versions": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "counts": {"raw": raw_counts, "final": final_counts},
        "artifacts": artifacts,
    }
    write_json(output / "manifest.json", manifest)
    return {"audit": audit, "manifest": manifest}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-visits", type=int, default=2)
    parser.add_argument("--top-diagnoses", type=int, default=2000, help="0 keeps all diagnosis concepts")
    parser.add_argument("--top-procedures", type=int, default=0, help="0 keeps all procedure concepts")
    parser.add_argument("--top-medicines", type=int, default=300, help="0 keeps all medicine concepts")
    parser.add_argument("--include-returned-medicines", action="store_true")
    parser.add_argument("--seed", type=int, default=424724)
    args = parser.parse_args()
    if args.min_visits < 1:
        parser.error("--min-visits must be >= 1")
    for name in ["top_diagnoses", "top_procedures", "top_medicines"]:
        if getattr(args, name) < 0:
            parser.error(f"--{name.replace('_', '-')} must be >= 0")
    return args


def main() -> None:
    args = parse_args()
    workbook = args.workbook.resolve()
    output = args.output.resolve()
    if not workbook.is_file():
        raise FileNotFoundError(workbook)
    config = {
        "min_visits": args.min_visits,
        "top_diagnoses": args.top_diagnoses,
        "top_procedures": args.top_procedures,
        "top_medicines": args.top_medicines,
        "include_returned_medicines": bool(args.include_returned_medicines),
        "seed": args.seed,
        "patient_order": "sha256(seed + NUL + patient_id)",
        "visit_order": "admission_time then visit_id within patient",
        "cohort_rule": "all three domains present after entity filtering, then patient has min_visits",
    }
    frames = read_source_frames(workbook)
    result = write_outputs(output, workbook, frames, config)
    print(json.dumps(result["audit"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
