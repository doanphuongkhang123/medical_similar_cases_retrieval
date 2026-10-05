import fs from "node:fs";
import path from "node:path";
import { readDocuments, saveDocument } from "./database.js";

const ACCURACY_VALUES = new Set(["accurate", "partial", "inaccurate", "uncertain"]);
const MAX_CALL_FILES = 5000;
const MAX_SCAN_DEPTH = 6;

function configuredRoot() {
  return String(process.env.LLM_RETRIEVAL_ROOT || "").trim();
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function stripJsonFence(value) {
  const text = String(value || "").trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/, "");
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  return start >= 0 && end >= start ? text.slice(start, end + 1) : text;
}

export function parseLlmCallPayload(payload) {
  const parts = (payload?.response?.candidates || [])
    .flatMap((candidate) => candidate?.content?.parts || [])
    .map((part) => part?.text)
    .filter(Boolean);
  if (!parts.length) throw new Error("Call JSON không có phần text trong response của model.");

  let output;
  let lastError;
  for (const text of parts) {
    try {
      output = JSON.parse(stripJsonFence(text));
      break;
    } catch (error) {
      lastError = error;
    }
  }
  if (!output) throw new Error(`Không parse được JSON output của model: ${lastError?.message || "không rõ lỗi"}`);
  if (!output.query_icd_assessment || !Array.isArray(output.ranking)) {
    throw new Error("Output của model thiếu query_icd_assessment hoặc ranking.");
  }
  return {
    request_id: String(payload.request_id || payload.response?.responseId || "").trim(),
    model_version: String(payload.response?.modelVersion || ""),
    usage_metadata: payload.response?.usageMetadata || {},
    query_icd_assessment: output.query_icd_assessment,
    ranking: output.ranking,
  };
}

export function parsePatientContexts(requestPayload) {
  const prompt = (requestPayload?.contents || [])
    .flatMap((content) => content?.parts || [])
    .map((part) => part?.text)
    .filter(Boolean)
    .join("\n");
  const dataStart = prompt.lastIndexOf("\nDATA\n");
  const data = dataStart >= 0 ? prompt.slice(dataStart + 6) : prompt;
  const contexts = {};
  const pattern = /(?:^|\n)BỆNH NHÂN\s+([A-Z]\d+)\s*\n([\s\S]*?)(?=\nBỆNH NHÂN\s+[A-Z]\d+\s*\n|$)/g;
  for (const match of data.matchAll(pattern)) {
    contexts[match[1]] = match[2].trim();
  }
  return contexts;
}

function findCallFiles(rootPath) {
  const stat = fs.statSync(rootPath, { throwIfNoEntry: false });
  if (!stat) return [];
  if (stat.isFile()) return rootPath.endsWith(".json") ? [rootPath] : [];
  const found = [];
  const walk = (directory, depth) => {
    if (depth > MAX_SCAN_DEPTH || found.length >= MAX_CALL_FILES) return;
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) continue;
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(entryPath, depth + 1);
      } else if (
        entry.isFile()
        && entry.name.endsWith(".json")
        && path.basename(directory) === "calls"
        && entry.name !== "attempts.json"
      ) {
        found.push(entryPath);
      }
      if (found.length >= MAX_CALL_FILES) break;
    }
  };
  walk(rootPath, 0);
  return found.sort((left, right) => left.localeCompare(right));
}

function loadContexts(callFile) {
  const requestFile = path.join(path.dirname(path.dirname(callFile)), "request_body.json");
  if (!fs.statSync(requestFile, { throwIfNoEntry: false })?.isFile()) return {};
  try {
    return parsePatientContexts(readJson(requestFile));
  } catch {
    return {};
  }
}

function readReviews() { return readDocuments("llm_reviews"); }

function reviewKey(requestId, patientId) {
  return `${requestId}:${patientId}`;
}

function callIndex() {
  const root = configuredRoot();
  if (!root) return { root: "", calls: new Map(), errors: [] };
  const calls = new Map();
  const errors = [];
  for (const filePath of findCallFiles(root)) {
    try {
      const parsed = parseLlmCallPayload(readJson(filePath));
      if (!parsed.request_id) throw new Error("Thiếu request_id.");
      calls.set(parsed.request_id, { filePath, parsed });
    } catch (error) {
      errors.push({ file: path.basename(filePath), error: error.message });
    }
  }
  return { root, calls, errors };
}

function getIndexedCall(requestId) {
  const index = callIndex();
  const found = index.calls.get(String(requestId));
  if (!found) {
    const error = new Error(`Không tìm thấy LLM call ${requestId}.`);
    error.status = 404;
    throw error;
  }
  return found;
}

export function listLlmRetrievalCalls() {
  const index = callIndex();
  const reviews = readReviews();
  const calls = [...index.calls.values()].map(({ parsed }) => {
    const reviewedCount = parsed.ranking.filter((candidate) => (
      reviews[reviewKey(parsed.request_id, candidate.patient_id)]
    )).length;
    return {
      request_id: parsed.request_id,
      model_version: parsed.model_version,
      query_patient_id: parsed.query_icd_assessment.patient_id,
      query_icd: parsed.query_icd_assessment.icd,
      candidate_count: parsed.ranking.length,
      reviewed_count: reviewedCount,
    };
  }).sort((left, right) => left.query_patient_id.localeCompare(right.query_patient_id));
  return {
    configured: Boolean(index.root),
    calls,
    invalid_file_count: index.errors.length,
  };
}

export function getLlmRetrievalCall(requestId) {
  const { filePath, parsed } = getIndexedCall(requestId);
  const contexts = loadContexts(filePath);
  const reviews = readReviews();
  const queryId = parsed.query_icd_assessment.patient_id;
  return {
    ...parsed,
    query_context: contexts[queryId] || "",
    ranking: [...parsed.ranking]
      .sort((left, right) => Number(left.rank) - Number(right.rank))
      .map((candidate) => ({
        ...candidate,
        patient_context: contexts[candidate.patient_id] || "",
        verification: reviews[reviewKey(parsed.request_id, candidate.patient_id)] || null,
      })),
  };
}

export function validateLlmRetrievalReview(review = {}) {
  if (!Number.isInteger(review.retrieval_relevance) || review.retrieval_relevance < 1 || review.retrieval_relevance > 5) {
    return "Mức phù hợp retrieval phải là số nguyên từ 1 đến 5.";
  }
  for (const [key, label] of [
    ["similarities_accuracy", "Nhận xét điểm giống"],
    ["differences_accuracy", "Nhận xét điểm khác"],
    ["icd_accuracy", "Đánh giá ICD"],
  ]) {
    if (!ACCURACY_VALUES.has(review[key])) return `${label} chưa được đánh giá hợp lệ.`;
  }
  if (review.note != null && (typeof review.note !== "string" || review.note.length > 5000)) {
    return "Ghi chú phải là chuỗi tối đa 5.000 ký tự.";
  }
  return null;
}

export function saveLlmRetrievalReview(requestId, patientId, review) {
  const { parsed } = getIndexedCall(requestId);
  const candidate = parsed.ranking.find((item) => item.patient_id === patientId);
  if (!candidate) {
    const error = new Error("Bệnh nhân không có trong ranking của LLM call này.");
    error.status = 404;
    throw error;
  }
  const reviews = readReviews();
  const saved = {
    retrieval_relevance: review.retrieval_relevance,
    similarities_accuracy: review.similarities_accuracy,
    differences_accuracy: review.differences_accuracy,
    icd_accuracy: review.icd_accuracy,
    note: review.note || "",
    reviewer: review.reviewer,
    at: new Date().toISOString(),
  };
  reviews[reviewKey(parsed.request_id, patientId)] = saved;
  saveDocument("llm_reviews", reviewKey(requestId, patientId), saved, true);
  return saved;
}

export function getLlmRetrievalExport() {
  const index = callIndex();
  const reviews = readReviews();
  return [...index.calls.values()].flatMap(({ parsed }) => parsed.ranking.map((candidate) => {
    const review = reviews[reviewKey(parsed.request_id, candidate.patient_id)] || {};
    return {
      request_id: parsed.request_id,
      model_version: parsed.model_version,
      query_patient_id: parsed.query_icd_assessment.patient_id,
      similar_patient_id: candidate.patient_id,
      rank: candidate.rank,
      llm_similarities: candidate.similarities,
      llm_differences: candidate.differences,
      llm_limitations: candidate.limitations,
      retrieval_relevance: review.retrieval_relevance ?? null,
      similarities_accuracy: review.similarities_accuracy || "",
      differences_accuracy: review.differences_accuracy || "",
      icd_accuracy: review.icd_accuracy || "",
      note: review.note || "",
      reviewer: review.reviewer || "",
      reviewed_at: review.at || "",
    };
  }));
}
