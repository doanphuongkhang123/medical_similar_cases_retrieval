import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "verify-llm-retrieval-"));
const runDirectory = path.join(temporary, "run-P00001");
const callsDirectory = path.join(runDirectory, "calls");
fs.mkdirSync(callsDirectory, { recursive: true });

const modelOutput = {
  query_icd_assessment: {
    patient_id: "P00001", visit: 1, icd: "A01", status: "supported",
    reason: "Text hỗ trợ mã.", evidence: ["v1e1"],
  },
  ranking: [{
    rank: 1,
    patient_id: "P00002",
    similarities: "Cùng biểu hiện chính.",
    differences: "Khác mức độ.",
    limitations: "",
    query_evidence: ["v1e1"],
    candidate_evidence: ["v1e1"],
    icd_assessment: {
      patient_id: "P00002", visit: 1, icd: "A02", status: "supported",
      reason: "Text candidate hỗ trợ mã.", evidence: ["v1e1"],
    },
  }],
};

fs.writeFileSync(path.join(callsDirectory, "request-1.json"), JSON.stringify({
  request_id: "request-1",
  response: {
    modelVersion: "gemini-test",
    usageMetadata: { totalTokenCount: 100 },
    candidates: [{ content: { parts: [{ text: JSON.stringify(modelOutput) }] } }],
  },
}));

fs.writeFileSync(path.join(runDirectory, "request_body.json"), JSON.stringify({
  contents: [{ parts: [{ text: [
    "Hướng dẫn",
    "DATA",
    "TOP_K: 1",
    "BỆNH NHÂN P00001",
    "VISIT 1",
    "ICD chính: \"A01\"",
    "[v1e1] ChanDoanRaVien: \"Query text\"",
    "BỆNH NHÂN P00002",
    "VISIT 1",
    "ICD chính: \"A02\"",
    "[v1e1] ChanDoanRaVien: \"Candidate text\"",
  ].join("\n") }] }],
}));

process.env.LLM_RETRIEVAL_ROOT = temporary;
process.env.DATA_DIR = path.join(temporary, "data");

const {
  getLlmRetrievalCall,
  getLlmRetrievalExport,
  listLlmRetrievalCalls,
  saveLlmRetrievalReview,
  validateLlmRetrievalReview,
} = await import("../src/data/llmRetrieval.js");

after(() => fs.rmSync(temporary, { recursive: true, force: true }));

test("discovers a Gemini call and exposes only the relevant patient contexts", () => {
  const catalogue = listLlmRetrievalCalls();
  assert.equal(catalogue.configured, true);
  assert.equal(catalogue.calls.length, 1);
  assert.equal(catalogue.calls[0].query_patient_id, "P00001");

  const detail = getLlmRetrievalCall("request-1");
  assert.match(detail.query_context, /Query text/);
  assert.match(detail.ranking[0].patient_context, /Candidate text/);
  assert.equal(detail.ranking[0].similarities, "Cùng biểu hiện chính.");
});

test("validates and stores an LLM retrieval review", () => {
  const review = {
    retrieval_relevance: 4,
    similarities_accuracy: "accurate",
    differences_accuracy: "partial",
    icd_accuracy: "uncertain",
    note: "Cần kiểm tra thêm.",
  };
  assert.equal(validateLlmRetrievalReview(review), null);
  assert.match(validateLlmRetrievalReview({ ...review, retrieval_relevance: 0 }), /1 đến 5/);
  assert.match(validateLlmRetrievalReview({ ...review, icd_accuracy: "yes" }), /ICD/);

  const saved = saveLlmRetrievalReview("request-1", "P00002", { ...review, reviewer: "doctor01" });
  assert.equal(saved.reviewer, "doctor01");
  assert.equal(getLlmRetrievalCall("request-1").ranking[0].verification.retrieval_relevance, 4);
  assert.equal(getLlmRetrievalExport()[0].differences_accuracy, "partial");
});
