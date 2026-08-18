from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from preprocess_ehr_tables_v2 import _assign_value_proxies, parse_result


class SemanticPreprocessV2Test(unittest.TestCase):
    def test_parse_result_preserves_numeric_semantics(self) -> None:
        exact = parse_result("12,5")
        self.assertEqual(exact["result_type"], "numeric_exact")
        self.assertEqual(exact["result_numeric"], 12.5)
        self.assertEqual(exact["value_proxy"], 12.5)

        censored = parse_result("< 6")
        self.assertEqual(censored["result_type"], "numeric_censored")
        self.assertEqual(censored["result_operator"], "<")
        self.assertEqual(censored["result_upper_bound"], 6.0)
        self.assertEqual(censored["value_proxy"], 3.0)
        self.assertTrue(math.isnan(censored["result_numeric"]))

        interval = parse_result("3–5")
        self.assertEqual(interval["result_type"], "numeric_interval")
        self.assertEqual(interval["result_lower_bound"], 3.0)
        self.assertEqual(interval["result_upper_bound"], 5.0)
        self.assertEqual(interval["value_proxy"], 4.0)

    def test_parse_result_preserves_category_and_free_text(self) -> None:
        category = parse_result("Dương tính")
        self.assertEqual(category["result_type"], "categorical")
        self.assertEqual(category["result_category"], "positive")
        self.assertEqual(category["result_category_group"], "polarity")

        ordinal = parse_result("+++")
        self.assertEqual(ordinal["result_type"], "semi_quantitative")
        self.assertEqual(ordinal["ordinal_level"], 3.0)

        free_text = parse_result("Hình thái tế bào không điển hình")
        self.assertEqual(free_text["result_type"], "free_text")
        self.assertEqual(free_text["result_raw"], "Hình thái tế bào không điển hình")

    def test_right_censored_proxy_uses_same_test_and_unit_tail(self) -> None:
        frame = pd.DataFrame(
            {
                "result_type": ["numeric_exact", "numeric_exact", "numeric_censored"],
                "result_operator": ["", "", ">"],
                "result_numeric": [12.0, 16.0, math.nan],
                "value_proxy": [12.0, 16.0, math.nan],
                "proxy_method": ["exact_value", "exact_value", ""],
                "result_lower_bound": [math.nan, math.nan, 10.0],
                "result_upper_bound": [math.nan, math.nan, math.nan],
                "observation_name": ["Test A", "Test A", "Test A"],
                "unit": ["mg/L", "mg/L", "mg/L"],
            }
        )

        result = _assign_value_proxies(frame)

        self.assertEqual(result.loc[2, "value_proxy"], 14.0)
        self.assertEqual(
            result.loc[2, "proxy_method"], "threshold_plus_group_tail_median"
        )


if __name__ == "__main__":
    unittest.main()
