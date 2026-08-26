from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from clean_raw_workbook_to_csv import clean_frame, clean_workbook


class RawWorkbookCleanerTest(unittest.TestCase):
    def test_clean_frame_preserves_partial_rows_and_removes_only_empty_data(self) -> None:
        source = pd.DataFrame(
            [["  A  ", " null ", None], [None, None, None], ["B", "  text\nvalue ", None]],
            columns=[" Tên  cột ", "Tên cột", "   "],
        )

        cleaned, report = clean_frame(source)

        self.assertEqual(cleaned.columns.tolist(), ["Tên cột", "Tên cột__2"])
        self.assertEqual(cleaned.shape, (2, 2))
        self.assertEqual(cleaned.iloc[0, 0], "A")
        self.assertTrue(pd.isna(cleaned.iloc[0, 1]))
        self.assertEqual(cleaned.iloc[1, 1], "text value")
        self.assertEqual(report["dropped_all_null_rows"], 1)
        self.assertEqual(report["dropped_all_null_columns"], ["unnamed_column_3"])

    def test_clean_workbook_keeps_source_sheet_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "source.xlsx"
            with pd.ExcelWriter(workbook) as writer:
                pd.DataFrame({" Name ": ["  Alice ", None], "Empty": [None, None]}).to_excel(writer, sheet_name="Thông tin", index=False)
                pd.DataFrame({"Code": [" A "]}).to_excel(writer, sheet_name="KQCLS", index=False)

            output = root / "cleaned"
            manifest = clean_workbook(workbook, output)

            self.assertEqual(set(manifest["sheets"]), {"Thông tin", "KQCLS"})
            self.assertTrue((output / "thong_tin.csv").is_file())
            self.assertTrue((output / "kqcls.csv").is_file())
            result = pd.read_csv(output / "thong_tin.csv")
            self.assertEqual(result.columns.tolist(), ["Name"])
            self.assertEqual(result.iloc[0, 0], "Alice")
            self.assertTrue((output / "cleaning_manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
