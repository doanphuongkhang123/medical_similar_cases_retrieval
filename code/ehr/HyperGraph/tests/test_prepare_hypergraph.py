from __future__ import annotations

import json
import pickle
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prepare_hypergraph import write_outputs  # noqa: E402
from verify_hypergraph import verify_output  # noqa: E402


def test_pipeline_filters_after_domain_eligibility_and_preserves_visit_order(tmp_path: Path) -> None:
    frames = {
        "visits": pd.DataFrame(
            [
                {"SoBenhAn": "v2", "SoVaoVien": "p1", "NgayVaoVien": "2024-02-01", "NgayRaVien": "2024-02-02", "MaICD": "C20.1", "ICD_phu": "Z01; Z01"},
                {"SoBenhAn": "v1", "SoVaoVien": "p1", "NgayVaoVien": "2024-01-01", "NgayRaVien": "2024-01-02", "MaICD": "C10.0", "ICD_phu": ""},
                {"SoBenhAn": "v3", "SoVaoVien": "p2", "NgayVaoVien": "2024-01-01", "NgayRaVien": "2024-01-02", "MaICD": "C30", "ICD_phu": ""},
                {"SoBenhAn": "v4", "SoVaoVien": "p3", "NgayVaoVien": "2024-01-01", "NgayRaVien": "2024-01-02", "MaICD": "C40", "ICD_phu": ""},
                {"SoBenhAn": "v5", "SoVaoVien": "p3", "NgayVaoVien": "2024-02-01", "NgayRaVien": "2024-02-02", "MaICD": "C50", "ICD_phu": ""},
            ]
        ),
        "procedures": pd.DataFrame(
            [
                {"SoBenhAn": visit, "YeuCauChiTiet_Id": f"e{index}", "TenDichVu": "Xét nghiệm A", "NgayYeuCau": "2024-01-01"}
                for index, visit in enumerate(["v1", "v2", "v3", "v4", "v5"], 1)
            ]
        ),
        "medicines": pd.DataFrame(
            [
                {"sobenhan": "v1", "TenHoatChat": "Drug A", "TenDuoc": "Brand A", "NgayKham": "2024-01-01", "LyDoTraThuoc": ""},
                {"sobenhan": "v2", "TenHoatChat": "Drug B", "TenDuoc": "Brand B", "NgayKham": "2024-02-01", "LyDoTraThuoc": ""},
                {"sobenhan": "v3", "TenHoatChat": "Drug A", "TenDuoc": "Brand A", "NgayKham": "2024-01-01", "LyDoTraThuoc": ""},
                {"sobenhan": "v4", "TenHoatChat": "Drug C", "TenDuoc": "Brand C", "NgayKham": "2024-01-01", "LyDoTraThuoc": ""},
                {"sobenhan": "v5", "TenHoatChat": "Drug D", "TenDuoc": "Brand D", "NgayKham": "2024-02-01", "LyDoTraThuoc": "returned"},
            ]
        ),
    }
    workbook = tmp_path / "source.xlsx"
    workbook.write_bytes(b"synthetic workbook placeholder")
    output = tmp_path / "out"
    config = {
        "min_visits": 2,
        "top_diagnoses": 0,
        "top_procedures": 0,
        "top_medicines": 0,
        "include_returned_medicines": False,
        "seed": 424724,
        "patient_order": "sha256(seed + NUL + patient_id)",
        "visit_order": "admission_time then visit_id within patient",
        "cohort_rule": "all three domains present after entity filtering, then patient has min_visits",
    }

    result = write_outputs(output, workbook, frames, config)

    assert result["audit"]["final_counts"]["patients"] == 1
    assert result["audit"]["final_counts"]["visits"] == 2
    cohort = pd.read_parquet(output / "cohort" / "visits.parquet")
    assert cohort["visit_id"].tolist() == ["v1", "v2"]
    with (output / "hypemed" / "records_final.pkl").open("rb") as stream:
        records = pickle.load(stream)
    assert len(records) == 1 and len(records[0]) == 2
    assert all(len(domain) > 0 for visit in records[0] for domain in visit)
    incidence = np.load(output / "hypergraphs" / "diag_incidence.npz")
    assert incidence["shape"].tolist()[1] == 2
    assert not (output / "hypemed" / "ddi_A_final.pkl").exists()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["raw_input"]["sha256"]
    assert manifest["semantic_limitations"]["ddi_graph"].startswith("not available")
    verification = verify_output(output)
    assert verification["status"] == "passed"

    relocated = tmp_path / "ehr" / "raw" / workbook.name
    relocated.parent.mkdir(parents=True)
    workbook.replace(relocated)
    layout_manifest = {
        "path_relocations": {
            str(workbook): str(relocated),
        }
    }
    (output.parent / "layout_manifest.json").write_text(json.dumps(layout_manifest))
    relocated_verification = verify_output(output)
    assert relocated_verification["raw_input_path"] == str(relocated)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="hypergraph-test-") as directory:
        test_pipeline_filters_after_domain_eligibility_and_preserves_visit_order(Path(directory))
    print("HyperGraph synthetic integration test passed")
