export const REVIEW_CRITERIA = Object.freeze([
  ["symptoms", "Triệu chứng"],
  ["diagnosis", "Chẩn đoán"],
  ["medications", "Thuốc"],
  ["ct", "Ảnh CT"],
  ["xq", "Ảnh XQ"],
  ["mri", "Ảnh MRI"],
  ["clinical_course", "Diễn biến lâm sàng"],
  ["severity", "Mức độ nghiêm trọng"],
  ["lab_results", "Kết quả xét nghiệm"],
]);

export function isRating(value) {
  return Number.isInteger(value) && value >= 1 && value <= 5;
}

export function validateComparisonReview({ criteria_scores: scores, overall_similarity: overall, note } = {}) {
  if (!scores || typeof scores !== "object" || Array.isArray(scores)) {
    return "Cần chấm đủ 9 tiêu chí từ 1 đến 5.";
  }
  const expected = new Set(REVIEW_CRITERIA.map(([key]) => key));
  if (Object.keys(scores).length !== expected.size || Object.keys(scores).some((key) => !expected.has(key))) {
    return "Bộ tiêu chí đánh giá không hợp lệ.";
  }
  for (const [key, label] of REVIEW_CRITERIA) {
    if (!isRating(scores[key])) return `${label} phải là số nguyên từ 1 đến 5.`;
  }
  if (!isRating(overall)) return "Mức độ tương tự chung phải là số nguyên từ 1 đến 5.";
  if (note != null && (typeof note !== "string" || note.length > 5000)) {
    return "Ghi chú phải là chuỗi tối đa 5.000 ký tự.";
  }
  return null;
}
