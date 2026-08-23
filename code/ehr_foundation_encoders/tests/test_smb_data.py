from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ehr_foundation_encoders.common import build_common_dataset
from ehr_foundation_encoders.smb import (
    SMB_MAX_SEQUENCE_LENGTH,
    audit_smb_serialization,
    build_smb_preflight,
    build_target_meds,
)
from ehr_foundation_encoders.tokenization import audit_smb_token_lengths


class SmbDataPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tables = {
            "visits": pd.DataFrame(
                {
                    "patient_id": ["p1", "p1", "p2"],
                    "visit_id": ["v1", "v2", "v3"],
                    "admission_time": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
                    "discharge_time": pd.to_datetime(["2024-01-03", "2024-02-04", "2024-03-02"]),
                    "birth_year": [1980, 1980, 1990],
                    "gender_code": ["Nam", "Nam", "Nữ"],
                }
            ),
            "diagnoses": pd.DataFrame(
                {
                    "diagnosis_id": ["d1", "d2", "d3"],
                    "patient_id": ["p1", "p1", "p2"],
                    "visit_id": ["v1", "v2", "v3"],
                    "diagnosis_code": ["A01", "", "B02.1"],
                    "diagnosis_text": ["Typhoid", "Local diagnosis", "Other"],
                    "event_time": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
                }
            ),
            "medicines": pd.DataFrame(
                {
                    "medicine_id": ["m1"], "patient_id": ["p1"], "visit_id": ["v2"],
                    "active_ingredient": ["Paracetamol"], "drug_name": ["Brand"],
                    "prescribed_time": pd.to_datetime(["2024-02-02"]), "unit": ["tablet"],
                }
            ),
            "procedures": pd.DataFrame(
                {
                    "procedure_id": ["r1"], "patient_id": ["p2"], "visit_id": ["v3"],
                    "service_code": ["LOCAL1"], "performed_name": ["Procedure A"],
                    "procedure_name": ["Procedure A"], "start_time": pd.to_datetime(["2024-03-01 12:00"]),
                }
            ),
            "observations": pd.DataFrame(
                {
                    "observation_id": ["o1", "o2"], "patient_id": ["p1", "p1"],
                    "visit_id": ["v2", "v2"], "service_code": ["LAB", "LAB"],
                    "observation_name": ["Glucose", "Polarity"],
                    "result_numeric": [12.5, float("nan")],
                    "result_type": ["numeric_exact", "categorical"],
                    "result_raw": ["12.5", "Dương tính"],
                    "result_category": ["", "positive"], "unit": ["mg/L", ""],
                    "observed_time": pd.to_datetime(["2024-02-03", "2024-02-03"]),
                }
            ),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_common_table_is_meds_compatible_and_keeps_one_copy(self) -> None:
        output = self.root / "common"
        manifest = build_common_dataset(self.tables, output)
        events = pd.read_parquet(output / "events.parquet")
        targets = pd.read_parquet(output / "targets.parquet")

        self.assertEqual(manifest["counts"]["target_visits"], 3)
        self.assertEqual(len(targets), 3)
        self.assertTrue({"subject_id", "time", "code", "table", "numeric_value", "text_value", "unit"}.issubset(events.columns))
        self.assertTrue(events["event_id"].is_unique)
        self.assertFalse(events["time"].isna().any())
        self.assertIn("ICD10:A01", set(events["code"]))
        self.assertIn("Paracetamol", set(events["code"]))
        self.assertEqual(events.loc[events["code"].eq("Glucose"), "numeric_value"].iloc[0], 12.5)
        self.assertEqual(events.loc[events["code"].eq("Polarity"), "text_value"].iloc[0], "positive")
        self.assertTrue((output / "concept_mappings.csv").exists())
        self.assertFalse(json.loads((output / "manifest.json").read_text())["encoder_run"])

    def test_visit_target_uses_patient_history_and_excludes_future(self) -> None:
        output = self.root / "common"
        build_common_dataset(self.tables, output)
        events = pd.read_parquet(output / "events.parquet")
        targets = pd.read_parquet(output / "targets.parquet")
        target = targets[targets["visit_id"].eq("v2")].iloc[0]
        selected = build_target_meds(events, target)
        self.assertIn("v1", set(selected["visit_id"]))
        self.assertIn("v2", set(selected["visit_id"]))
        self.assertNotIn("v3", set(selected["visit_id"]))
        self.assertTrue((selected["time"] <= target["cutoff_time"]).all())
        preflight = build_smb_preflight(events, targets)
        row = preflight[preflight["visit_id"].eq("v2")].iloc[0]
        self.assertEqual(row["history_visit_count"], 2)
        self.assertTrue(row["has_current_visit_event"])

    def test_serialization_audit_does_not_persist_text(self) -> None:
        common = self.root / "common"
        build_common_dataset(self.tables, common)
        events = pd.read_parquet(common / "events.parquet")
        targets = pd.read_parquet(common / "targets.parquet")

        def fake_formatter(frame: pd.DataFrame, **_: object) -> str:
            return "\n".join(frame["code"].astype(str))

        output = self.root / "serialization"
        manifest = audit_smb_serialization(events, targets, fake_formatter, output)
        audit = pd.read_parquet(output / "serialization_audit.parquet")
        self.assertEqual(len(audit), 3)
        self.assertTrue(audit["serialization_nonempty"].all())
        self.assertFalse(manifest["serialized_text_persisted"])
        self.assertFalse((output / "serialized_text.jsonl").exists())

    def test_token_audit_measures_full_and_current_without_persisting_ids(self) -> None:
        common = self.root / "common"
        build_common_dataset(self.tables, common)
        events = pd.read_parquet(common / "events.parquet")
        targets = pd.read_parquet(common / "targets.parquet")

        class FakeTokenizer:
            model_max_length = 3300

            def __len__(self) -> int:
                return 100

            def __call__(self, texts: list[str], **_: object) -> dict[str, list[list[int]]]:
                return {"input_ids": [[1] * len(text.split()) for text in texts]}

        def fake_formatter(frame: pd.DataFrame, **_: object) -> str:
            return " ".join(frame["code"].astype(str))

        tokenizer_root = self.root / "tokenizer"
        tokenizer_root.mkdir()
        (tokenizer_root / "tokenizer_config.json").write_text("{}")
        output = self.root / "tokenization"
        manifest = audit_smb_token_lengths(
            events,
            targets,
            FakeTokenizer(),
            fake_formatter,
            output,
            tokenizer_root,
            max_length=4,
            batch_size=2,
        )
        audit = pd.read_parquet(output / "token_length_audit.parquet")
        self.assertEqual(SMB_MAX_SEQUENCE_LENGTH, 3300)
        self.assertEqual(manifest["max_length"], 4)
        self.assertEqual(manifest["tokenizer"]["reported_model_max_length"], 3300)
        self.assertEqual(len(audit), 3)
        self.assertGreaterEqual(manifest["counts"]["full_history_over_limit"], 1)
        self.assertTrue((audit["full_token_count"] >= audit["current_plus_demographics_token_count"]).all())
        self.assertFalse(manifest["policy"]["token_ids_persisted"])
        self.assertFalse((output / "token_ids.parquet").exists())


if __name__ == "__main__":
    unittest.main()
