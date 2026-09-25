"""Voting behavior for three independent Top-20 cosine rankings."""
import unittest

from moe_vote_rank import rank_query


def source(prefix, shared, shared_rank, low, high):
    ids = [f"{prefix}{index:02d}" for index in range(20)]
    ids[shared_rank - 1] = shared
    return [
        {"rank": index + 1, "patient_id": patient_id,
         "cosine_similarity": high - (high - low) * index / 19}
        for index, patient_id in enumerate(ids)
    ]


class MoeVoteRankingTests(unittest.TestCase):
    def test_vote_tiers_mean_rank_and_normalized_one_vote(self):
        fusion = source("F", "TRIPLE", 18, 0.80, 0.99)
        openai = source("O", "TRIPLE", 19, 0.40, 0.60)
        qwen3 = source("Q", "TRIPLE", 20, 0.10, 0.90)
        # A two-vote candidate beats TRIPLE on mean rank but stays below it.
        fusion[1]["patient_id"] = "DOUBLE_A"
        openai[2]["patient_id"] = "DOUBLE_A"
        fusion[3]["patient_id"] = "DOUBLE_B"
        qwen3[4]["patient_id"] = "DOUBLE_B"
        result = rank_query("QUERY", {"fusion": fusion, "openai": openai, "qwen3": qwen3})
        self.assertEqual([item["patient_id"] for item in result["top20"][:3]],
                         ["TRIPLE", "DOUBLE_A", "DOUBLE_B"])
        self.assertEqual([item["vote_count"] for item in result["top20"][:3]], [3, 2, 2])
        self.assertEqual(result["top20"][1]["mean_source_rank"], 2.5)
        # Raw cosine favors F00 (0.99); normalized scores tie at 1 and ID breaks tie.
        self.assertEqual(result["top20"][3]["patient_id"], "F00")
        for item in result["top20"]:
            self.assertEqual(item["vote_count"], len(item["model_scores"]))

    def test_constant_cosine_uses_neutral_normalized_value(self):
        sources = {
            model: [{"rank": index + 1, "patient_id": f"{model}{index:02d}",
                     "cosine_similarity": 0.5} for index in range(20)]
            for model in ("fusion", "openai", "qwen3")
        }
        result = rank_query("QUERY", sources)
        self.assertEqual(result["top20"][0]["model_scores"]["fusion"]["normalized_cosine"], 0.5)

    def test_self_match_rejected(self):
        sources = {model: source(model, "QUERY", 1, 0.1, 0.9)
                   for model in ("fusion", "openai", "qwen3")}
        with self.assertRaisesRegex(ValueError, "self-match"):
            rank_query("QUERY", sources)


if __name__ == "__main__":
    unittest.main()
