"""Safety and clinical-text boundary cases for lexical overlap marks."""
from html import unescape
import re
import unittest

from moe_case_highlight import marked_html, matched_spans


def visible_text(marked: str) -> str:
    return unescape(re.sub(r"</?mark[^>]*>", "", marked))


class MoeCaseHighlightTests(unittest.TestCase):
    def test_exact_icd_and_phrase_overlap_on_both_sides(self):
        query = (
            "LẦN KHÁM 1\nICD chính: J18.9\n"
            "Chẩn đoán ra viện: Viêm phổi cộng đồng\n"
            "Tóm tắt bệnh án: Ho kéo dài, sốt cao liên tục."
        )
        candidate = (
            "LẦN KHÁM 1\nICD phụ: J18.9; E11\n"
            "Chẩn đoán ra viện: Viêm phổi cộng đồng nặng\n"
            "Tóm tắt bệnh án: Đau ngực và sốt cao liên tục."
        )
        query_spans, candidate_spans = matched_spans(query, candidate)
        self.assertEqual({kind for _, _, kind in query_spans}, {"icd", "diagnosis", "summary"})
        self.assertEqual({kind for _, _, kind in candidate_spans}, {"icd", "diagnosis", "summary"})
        self.assertIn('<mark class="match-icd"', marked_html(query, query_spans))
        self.assertEqual(visible_text(marked_html(query, query_spans)), query)
        self.assertEqual(visible_text(marked_html(candidate, candidate_spans)), candidate)

    def test_related_icd_code_is_not_exact_overlap(self):
        query = "ICD chính: J18.9"
        candidate = "ICD chính: J18.8"
        self.assertEqual(matched_spans(query, candidate), ([], []))

    def test_negation_prevents_positive_summary_highlight(self):
        query = "Tóm tắt bệnh án: Sốt cao liên tục."
        candidate = "Tóm tắt bệnh án: Không sốt cao liên tục."
        self.assertEqual(matched_spans(query, candidate), ([], []))

    def test_dau_dau_matches_with_or_without_bi(self):
        query = "Tóm tắt bệnh án: Bệnh nhân bị đau đầu."
        candidate = "Tóm tắt bệnh án: Bệnh nhân đau đầu."
        query_spans, candidate_spans = matched_spans(query, candidate)
        self.assertIn("đau đầu", [query[left:right].casefold() for left, right, kind in query_spans if kind == "summary"])
        self.assertIn("đau đầu", [candidate[left:right].casefold() for left, right, kind in candidate_spans if kind == "summary"])
        self.assertEqual(visible_text(marked_html(query, query_spans)), query)
        self.assertEqual(visible_text(marked_html(candidate, candidate_spans)), candidate)

    def test_dau_dau_negation_prevents_positive_highlight(self):
        query = "Tóm tắt bệnh án: Bệnh nhân đau đầu."
        candidate = "Tóm tắt bệnh án: Bệnh nhân không đau đầu."
        self.assertEqual(matched_spans(query, candidate), ([], []))

    def test_generic_phrase_is_ignored_and_html_is_escaped(self):
        query = "Tóm tắt bệnh án: Bệnh nhân vào viện <script>alert(1)</script>"
        candidate = "Tóm tắt bệnh án: Bệnh nhân vào viện"
        query_spans, candidate_spans = matched_spans(query, candidate)
        self.assertEqual(query_spans, [])
        self.assertEqual(candidate_spans, [])
        marked = marked_html(query, query_spans)
        self.assertNotIn("<script>", marked)
        self.assertEqual(visible_text(marked), query)


if __name__ == "__main__":
    unittest.main()
