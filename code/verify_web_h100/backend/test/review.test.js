import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { REVIEW_CRITERIA, validateComparisonReview } from "../src/data/reviewSchema.js";

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "verify-review-test-"));
process.env.DATA_DIR = temporary;
const { getVerification, setComparisonVerification } = await import("../src/data/store.js");
after(() => fs.rmSync(temporary, { recursive: true, force: true }));

const scores = Object.fromEntries(REVIEW_CRITERIA.map(([key], index) => [key, index % 5 + 1]));

test("requires all nine criteria and overall similarity as integer 1–5", () => {
  assert.equal(validateComparisonReview({ criteria_scores: scores, overall_similarity: 5, note: "Đã đối chiếu" }), null);
  assert.match(validateComparisonReview({ criteria_scores: { ...scores, ct: 0 }, overall_similarity: 5 }), /Ảnh CT/);
  assert.match(validateComparisonReview({ criteria_scores: { ...scores, mri: 6 }, overall_similarity: 5 }), /Ảnh MRI/);
  assert.match(validateComparisonReview({ criteria_scores: { ...scores, symptoms: "3" }, overall_similarity: 5 }), /Triệu chứng/);
  assert.match(validateComparisonReview({ criteria_scores: { ...scores, medications: undefined }, overall_similarity: 5 }), /Thuốc/);
  assert.match(validateComparisonReview({ criteria_scores: scores, overall_similarity: null }), /Mức độ tương tự chung/);
  assert.match(validateComparisonReview({ criteria_scores: scores, overall_similarity: 2.5 }), /Mức độ tương tự chung/);
  assert.match(validateComparisonReview({ criteria_scores: scores, overall_similarity: 3, note: "x".repeat(5001) }), /Ghi chú/);
});

test("stores all ratings and reviewer under the selected pair", () => {
  const saved = setComparisonVerification("q1:c1", {
    criteria_scores: scores,
    overall_similarity: 4,
    note: "Kiểm tra đủ hồ sơ",
    reviewer: "doctor01",
  });
  assert.deepEqual(saved.criteria_scores, scores);
  assert.equal(saved.overall_similarity, 4);
  assert.equal(saved.reviewer, "doctor01");
  assert.deepEqual(getVerification("q1:c1"), saved);
  assert.equal(getVerification("q1:c2"), null);
});

test("preserves a legacy categorical review when the pair is rescored", async () => {
  const file = path.join(temporary, "verifications.json");
  const { saveDocument } = await import("../src/data/database.js");
  saveDocument("reviews", "q1:legacy", { status: "similar", note: "Bản cũ", reviewer: "doctor00" });
  const saved = setComparisonVerification("q1:legacy", {
    criteria_scores: scores,
    overall_similarity: 3,
    note: "Đã chấm lại",
    reviewer: "doctor01",
  });
  assert.equal(saved.legacy_status, "similar");
  assert.equal(saved.overall_similarity, 3);
});
