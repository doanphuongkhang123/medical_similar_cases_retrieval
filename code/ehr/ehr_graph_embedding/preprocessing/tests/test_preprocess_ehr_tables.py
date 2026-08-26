from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from preprocess_ehr_tables import (
    attach_visit_summary,
    build_clinical_notes,
    build_diagnoses,
    build_medicines,
    build_observations,
    build_procedures,
    build_graph_tables,
    build_visit_ehr_rows,
    build_visits,
    validate,
)


class PreprocessTablesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = {
            "visits": pd.DataFrame({
                "SoBenhAn": ["V1"], "SoVaoVien": ["P1"], "NgayVaoVien": ["2026-01-01"],
                "NgayRaVien": ["2026-01-03"], "TenPhongBan": ["Nội"], "MaICD": ["I10"],
                "ICD_phu": ["E11.9; E78.5"], "ChanDoanRaVien": ["Tăng huyết áp"],
                "ChanDoanTruocPhauThuat": [""], "ChanDoanSauPhauThuat": [""],
                "KhamBenhBenhChinh": ["Tăng huyết áp"], "KhamBenhBenhKemTheo": [""],
                "KhamBenhPhanBiet": [""], "LyDoVaoVien": ["Đau đầu"],
                "QuaTrinhBenhLy": ["Đau đầu hai ngày"], "Mach": [80], "NhipTho": [18],
                "NhietDo": [37], "CanNang": [60], "HuyetApCao": [140], "HuyetApThap": [90],
            }),
            "orders": pd.DataFrame({
                "SoBenhAn": ["V1"], "SoVaoVien": ["P1"], "NamSinh": [1980], "GioiTinh": ["T"],
                "YeuCauChiTiet_Id": ["O1"], "TenDichVu": ["X-quang ngực"],
                "NgayYeuCau": ["2026-01-01 09:00"], "ChanDoan": ["Tăng huyết áp"],
                "TenPhongBan": ["Nội"], "TenPhongBan.1": ["CĐHA"], "GhiChu": ["Kiểm tra"],
                "loaimau": [""], "ViTriMau": [""],
            }),
            "medicines": pd.DataFrame({
                "sobenhan": ["V1"], "mayte": ["P1"], "TenDuoc": ["Amlodipine 5 mg"],
                "TenHoatChat": ["Amlodipine"], "DuongDung": ["Uống"], "strSLSang": ["1"],
                "strSLTrua": [""], "strSLChieu": [""], "strSLToi": [""], "DonViTinh": ["viên"],
                "SoNgay": [5], "SoLuongTong": [5], "LoiDan": ["Sau ăn"], "GhiChu": [""],
                "LyDoTraThuoc": [""], "NgayKham": ["2026-01-01 10:00"],
                "ChanDoanKhoaKham": ["Tăng huyết áp"],
            }),
            "labs": pd.DataFrame({
                "SoBenhAn": ["V1"], "YeuCauChiTiet_Id": ["O1"], "ChanDoan": ["Tăng huyết áp"],
                "MA_DICH_VU": ["XR01"], "TEN_CHI_SO": ["Kết luận"], "GIA_TRI": ["Bình thường"],
                "DON_VI_DO": [""], "khoang_tham_chieu": [""], "LoaiMau": [""],
                "MO_TA": ["Không thấy tổn thương"], "KET_LUAN": ["Bình thường"],
                "NGAY_KQ": ["2026-01-01 11:00"],
            }),
            "procedures": pd.DataFrame({
                "YeuCauChiTiet_Id": ["O1"], "TenDichVu": ["X-quang ngực"],
                "ten_dich_vu": ["X-quang ngực thẳng"], "CanThiepPhauThuat": [""],
                "LoaiPhauThuat": [""], "pp_vocam": [""], "TrinhTuThucHien_Text": ["Chụp ngực"],
                "DanLuu": [""], "KetQua": ["An toàn"], "nhom_chiphi": ["KẾT QUẢ"],
                "noi_thuc_hien": ["CĐHA"], "ThoiGianTiepNhan": ["2026-01-01 09:30"],
                "ThoiGianBatDau": ["2026-01-01 10:00"], "ThoiGianKetThuc": ["2026-01-01 10:10"],
                "ICD_TruocPhauThuat_MoTa": [""], "ICD_SauPhauThuat_MoTa": [""],
            }),
        }
        for _, field in []:
            pass
        # Các trường ghi chú không có trong fixture được thêm rỗng để giống workbook thật.
        from preprocess_ehr_tables import MAIN_NOTE_FIELDS
        for _, field in MAIN_NOTE_FIELDS:
            if field not in self.frames["visits"]:
                self.frames["visits"][field] = ""

    def test_builds_all_tables_with_composite_key(self) -> None:
        visits, mapping = build_visits(self.frames)
        diagnoses = build_diagnoses(self.frames, mapping)
        medicines = build_medicines(self.frames, mapping)
        procedures = build_procedures(self.frames, mapping)
        notes = build_clinical_notes(self.frames, mapping)
        observations = build_observations(self.frames, mapping)
        visits = attach_visit_summary(visits, diagnoses, medicines, procedures, notes, observations)
        visit_ehr = build_visit_ehr_rows(visits, diagnoses, medicines, procedures)
        graph_nodes, graph_edges = build_graph_tables(
            visits, diagnoses, medicines, procedures, notes, observations,
        )
        report = validate(visits, {
            "diagnoses": diagnoses, "medicines": medicines, "procedures": procedures,
            "clinical_notes": notes, "observations": observations,
        })
        self.assertEqual(visits.loc[0, "primary_key"], "P1::V1")
        self.assertIn("Đau đầu", visits.loc[0, "clinical_note"])
        self.assertEqual(visit_ehr.loc[0, "ehr_row_id"], "P1::V1")
        self.assertIn("Amlodipine", visit_ehr.loc[0, "medicine"])
        self.assertEqual(procedures.loc[0, "status"], "performed")
        self.assertEqual(graph_nodes["graph_id"].nunique(), 1)
        self.assertTrue({"VISIT", "DIAGNOSIS", "MEDICINE", "PROCEDURE", "NOTE", "OBSERVATION"}.issubset(set(graph_nodes["node_type"])))
        self.assertGreater(len(graph_edges), 0)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(graph_nodes["event_time"]))
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            pass
        else:
            with tempfile.TemporaryDirectory() as directory:
                graph_nodes.to_parquet(Path(directory) / "nodes.parquet", index=False)
        self.assertTrue(report["visit_primary_key_unique"])
        self.assertGreater(len(diagnoses), 0)
        self.assertGreater(len(observations), 0)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(observations["observed_time"]))

    def test_direct_identifiers_are_not_in_outputs(self) -> None:
        visits, mapping = build_visits(self.frames)
        outputs = [
            visits, build_diagnoses(self.frames, mapping), build_medicines(self.frames, mapping),
            build_procedures(self.frames, mapping), build_clinical_notes(self.frames, mapping),
            build_observations(self.frames, mapping),
        ]
        forbidden = {"TenBenhNhan", "ten_benh_nhan", "DiaChi", "SoBHYT", "BacSi"}
        for frame in outputs:
            self.assertFalse(forbidden.intersection(frame.columns))


if __name__ == "__main__":
    unittest.main()
