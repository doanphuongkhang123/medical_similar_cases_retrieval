import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "verify-web-test-"));
const topkPath = path.join(temporary, "top20.csv");
const selectedQueryIds = ["q1", "q2"];
process.env.RETRIEVAL_CONFIG = path.join(temporary, "retrieval.json");
fs.writeFileSync(process.env.RETRIEVAL_CONFIG, JSON.stringify({query_patient_ids: selectedQueryIds}));
const topkRows = selectedQueryIds.flatMap((queryId, queryIndex) => [
  `${queryId},test,1,c${queryIndex + 1}a,train,0.91,True,I63`,
  `${queryId},test,2,c${queryIndex + 1}b,validation,0.88,False,`,
]);
fs.writeFileSync(topkPath, [
  "query_patient_id,query_split,rank,related_patient_id,related_split,cosine_similarity,shares_primary_icd_group,shared_primary_icd_groups",
  ...topkRows,
].join("\n"));
process.env.TOPK_FILE = topkPath;
process.env.QUERY_PATIENT_ID = selectedQueryIds[0];
process.env.DATA_DIR = path.join(temporary, "decisions");

const {
  buildComparisonExportRow,
  buildSimilarityEvidence,
  listComparisonQueries,
} = await import("../src/data/comparison.js");

test("loads query catalogue from the Top-K CSV", () => {
  const catalogue = listComparisonQueries();
  assert.equal(catalogue.default_query_patient_id, selectedQueryIds[0]);
  assert.deepEqual(catalogue.queries, selectedQueryIds.map((patientId) => ({
    patient_id: patientId,
    split: "test",
    candidate_count: 2,
  })));
});

test("builds auditable overlap evidence", () => {
  const patient = ({ id, ehr, labs, modalities }) => ({
    id,
    records: [{
      ehr: { details: [["Chẩn đoán", ehr]] },
      labs,
      studies: {
        XQ: modalities.includes("XQ") ? [{ id: "x" }] : [],
        CT: modalities.includes("CT") ? [{ id: "c" }] : [],
        MRI: [],
      },
    }],
  });
  const query = patient({
    id: "q1", ehr: "Viêm phổi thùy dưới", modalities: ["XQ", "CT"],
    labs: [{ name: "CRP", flagged: true }, { name: "Glucose", flagged: false }],
  });
  const candidate = patient({
    id: "c1", ehr: "Theo dõi viêm phổi", modalities: ["XQ"],
    labs: [{ name: "CRP", flagged: true }],
  });
  const evidence = buildSimilarityEvidence(query, candidate, {
    shared_primary_icd_groups: ["J18"],
  });
  assert.deepEqual(evidence.shared_primary_icd_groups, ["J18"]);
  assert.ok(evidence.ehr_keywords.includes("viêm"));
  assert.ok(evidence.ehr_keywords.includes("phổi"));
  assert.deepEqual(evidence.shared_labs, ["CRP"]);
  assert.deepEqual(evidence.shared_abnormal_labs, ["CRP"]);
  assert.deepEqual(evidence.shared_modalities, ["XQ"]);
});

test("exports nine criterion scores, overall score, and legacy review separately", () => {
  const candidate = {
    patient_id: "c1",
    rank: 1,
    similarity_score: 0.91,
    shared_primary_icd_groups: ["I63"],
  };
  const criteriaScores = {
    symptoms: 5,
    diagnosis: 4,
    medications: 3,
    ct: 2,
    xq: 1,
    mri: 2,
    clinical_course: 3,
    severity: 4,
    lab_results: 5,
  };
  const row = buildComparisonExportRow("q1", candidate, {
    criteria_scores: criteriaScores,
    overall_similarity: 4,
    note: "Đã kiểm tra",
    reviewer: "doctor01",
    at: "2026-09-21T00:00:00.000Z",
  });
  assert.equal(row.symptoms_score, 5);
  assert.equal(row.lab_results_score, 5);
  assert.equal(row.overall_similarity, 4);
  assert.equal(row.legacy_review_level, "");

  const legacy = buildComparisonExportRow("q1", candidate, { status: "similar" });
  assert.equal(legacy.overall_similarity, null);
  assert.equal(legacy.legacy_review_level, "similar");
});
