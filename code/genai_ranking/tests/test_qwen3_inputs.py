import tempfile
import unittest
from pathlib import Path

import openpyxl

from common import read_json, read_jsonl
from prepare_qwen3_inputs import prepare, serialize_profile, verify


def make_workbook(path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "thông tin bệnh án"
    sheet.append([
        "SoBenhAn", "SoVaoVien", "NgayVaoVien", "NgayRaVien", "MaICD",
        "ICD_phu", "TomTatBenhAn", "ChanDoanRaVien",
    ])
    for number in range(1, 5):
        sheet.append([
            f"RAW-VISIT-{number}", "RAW-PATIENT-A", f"2026-01-0{number}",
            f"2026-01-0{number}", f"J0{number}", "E11",
            f"Tóm tắt lần {number}", f"Chẩn đoán lần {number}",
        ])
    sheet.append([
        "RAW-VISIT-5", "RAW-PATIENT-B", "2026-02-01", "2026-02-01",
        "I10", "", "Tăng huyết áp", "",
    ])
    book.save(path)


class Qwen3InputTests(unittest.TestCase):
    def test_serializer_contains_only_agreed_encoder_fields(self):
        profile = {"patient_id": "P00001", "visits": [{
            "recency": 1,
            "icd_primary": "J18.9",
            "icd_secondary": "E11",
            "evidence": [
                {"field": "TomTatBenhAn", "text": "Ho và sốt", "source": {"row": 2}},
                {"field": "ChanDoanRaVien", "text": "Viêm phổi", "source": {"row": 2}},
            ],
        }]}
        text, _ = serialize_profile(profile)
        self.assertIn("ICD chính: J18.9", text)
        self.assertIn("ICD phụ: E11", text)
        self.assertIn("Tóm tắt bệnh án: Ho và sốt", text)
        self.assertIn("Chẩn đoán ra viện: Viêm phổi", text)
        self.assertNotIn("P00001", text)
        self.assertNotIn("source", text)

    def test_prepare_and_verify_one_row_per_patient_newest_three_visits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook, output = root / "raw.xlsx", root / "output"
            make_workbook(workbook)
            manifest = prepare(workbook, output)
            checked = verify(output)
            rows = read_jsonl(output / "embedding_inputs.jsonl")
            self.assertEqual(manifest["patients"], 2)
            self.assertEqual(checked["patients"], 2)
            self.assertEqual(rows[0]["visit_count"], 3)
            self.assertIn("Tóm tắt lần 4", rows[0]["embedding_text"])
            self.assertIn("Tóm tắt lần 2", rows[0]["embedding_text"])
            self.assertNotIn("Tóm tắt lần 1", rows[0]["embedding_text"])
            self.assertNotIn("RAW-PATIENT", rows[0]["embedding_text"])
            self.assertNotIn("2026-", rows[0]["embedding_text"])
            saved = read_json(output / "manifest.json")
            self.assertEqual(saved["status"], "prepared_for_local_qwen3_embedding")
            self.assertFalse(saved["external_data_transfer"])
            self.assertEqual(saved["api_calls"], 0)

    def test_unexpected_evidence_field_is_rejected(self):
        profile = {"patient_id": "P00001", "visits": [{
            "recency": 1,
            "icd_primary": "",
            "icd_secondary": "",
            "evidence": [{"field": "HoTen", "text": "Không được phép"}],
        }]}
        with self.assertRaisesRegex(ValueError, "Unexpected encoder field"):
            serialize_profile(profile)


if __name__ == "__main__":
    unittest.main()
