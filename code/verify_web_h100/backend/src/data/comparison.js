import fs from "fs";
import { fileURLToPath } from "url";
import { getPatient } from "./rawPatients.js";
import { getVerification, setComparisonVerification } from "./store.js";
import { REVIEW_CRITERIA } from "./reviewSchema.js";

const RETRIEVAL_FILE = process.env.RETRIEVAL_CONFIG || fileURLToPath(new URL("./retrieval.json", import.meta.url));
const TOPK_FILE = process.env.TOPK_FILE || "";
const DEFAULT_QUERY_PATIENT_ID = process.env.QUERY_PATIENT_ID || "";
const STOP_WORDS = new Set([
  "bệnh", "nhân", "điều", "trị", "chẩn", "đoán", "không", "có", "của",
  "cho", "và", "với", "trong", "ngoài", "được", "theo", "sau", "trước",
  "tại", "này", "đến", "vào", "ra", "viện", "khoa", "ngày", "tháng",
  "năm", "một", "các", "những", "hiện", "tiền", "sử", "tình", "trạng",
  "the", "patient", "normal", "âm", "tính", "dương", "ghi", "nhận",
  "bình", "thường", "cấp", "cứu", "khám", "kết", "quả", "lần",
]);
const EHR_METADATA_LABELS = new Set([
  "số bệnh án", "số vào viện", "mã bệnh án", "ngày vào viện", "ngày ra viện",
  "khoa điều trị", "kết quả điều trị",
]);
const EHR_BOILERPLATE_LABELS = new Set([
  "khám tổn thương", "diễn biến lâm sàng", "hướng điều trị", "phương pháp điều trị",
]);

let topkCache = null;

function readQuerySelection() {
  try {
    const config = JSON.parse(fs.readFileSync(RETRIEVAL_FILE, "utf8"));
    if (!Array.isArray(config?.query_patient_ids)) return [];
    return [...new Set(config.query_patient_ids.map((id) => String(id).trim()).filter(Boolean))];
  } catch {
    return [];
  }
}

function parseCsvLine(line) {
  const cells = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      cells.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  cells.push(value);
  return cells;
}

function readTopkIndex() {
  if (!TOPK_FILE || !fs.statSync(TOPK_FILE, { throwIfNoEntry: false })?.isFile()) return null;
  const stat = fs.statSync(TOPK_FILE);
  if (topkCache?.mtimeMs === stat.mtimeMs && topkCache?.size === stat.size) return topkCache.value;
  const lines = fs.readFileSync(TOPK_FILE, "utf8").replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  if (lines.length < 2) throw new Error(`Top-K CSV không có dữ liệu: ${TOPK_FILE}`);
  const header = parseCsvLine(lines[0]);
  const required = [
    "query_patient_id", "query_split", "rank", "related_patient_id",
    "related_split", "cosine_similarity", "shares_primary_icd_group",
    "shared_primary_icd_groups",
  ];
  const positions = Object.fromEntries(required.map((name) => [name, header.indexOf(name)]));
  const missing = required.filter((name) => positions[name] < 0);
  if (missing.length) throw new Error(`Top-K CSV thiếu cột: ${missing.join(", ")}`);

  const byQuery = new Map();
  for (const line of lines.slice(1)) {
    if (!line.trim()) continue;
    const cells = parseCsvLine(line);
    const queryId = String(cells[positions.query_patient_id] || "").trim();
    const patientId = String(cells[positions.related_patient_id] || "").trim();
    const rank = Number(cells[positions.rank]);
    const similarityScore = Number(cells[positions.cosine_similarity]);
    if (!queryId || !patientId || !Number.isInteger(rank) || !Number.isFinite(similarityScore)) continue;
    const candidate = {
      rank,
      patient_id: patientId,
      similarity_score: similarityScore,
      query_split: String(cells[positions.query_split] || ""),
      related_split: String(cells[positions.related_split] || ""),
      shares_primary_icd_group: String(cells[positions.shares_primary_icd_group]).toLowerCase() === "true",
      shared_primary_icd_groups: String(cells[positions.shared_primary_icd_groups] || "").split("|").filter(Boolean),
    };
    if (!byQuery.has(queryId)) byQuery.set(queryId, []);
    byQuery.get(queryId).push(candidate);
  }
  for (const candidates of byQuery.values()) candidates.sort((left, right) => left.rank - right.rank);
  const selectedIds = readQuerySelection();
  if (selectedIds.length) {
    const missing = selectedIds.filter((id) => !byQuery.has(id));
    if (missing.length) throw new Error(`Các query không có trong Top-K CSV: ${missing.join(", ")}`);
    for (const patientId of [...byQuery.keys()]) {
      if (!selectedIds.includes(patientId)) byQuery.delete(patientId);
    }
  }
  const queryOrder = selectedIds.length ? selectedIds : [...byQuery.keys()].sort((left, right) => left.localeCompare(right));
  const queries = queryOrder.map((patientId) => {
    const candidates = byQuery.get(patientId);
    return {
      patient_id: patientId,
      split: candidates[0]?.query_split || "",
      candidate_count: candidates.length,
    };
  });
  const value = { byQuery, queries, source: TOPK_FILE };
  topkCache = { mtimeMs: stat.mtimeMs, size: stat.size, value };
  return value;
}

function readStaticRetrieval() {
  let retrieval;
  try {
    retrieval = JSON.parse(fs.readFileSync(RETRIEVAL_FILE, "utf8"));
  } catch (error) {
    throw new Error(`Không đọc được retrieval.json: ${error.message}`);
  }
  if (!retrieval?.patient_id || !Array.isArray(retrieval.similar_patients)) {
    throw new Error("retrieval.json phải có patient_id và mảng similar_patients.");
  }
  return {
    patientId: String(retrieval.patient_id),
    candidates: retrieval.similar_patients.map((item, index) => ({
      rank: Number.isInteger(item.rank) ? item.rank : index + 1,
      patient_id: String(item.patient_id || ""),
      similarity_score: Number(item.similarity_score),
      shares_primary_icd_group: false,
      shared_primary_icd_groups: [],
    })).filter((item) => item.patient_id && Number.isFinite(item.similarity_score)),
    source: RETRIEVAL_FILE,
  };
}

function resolveContext(queryPatientId) {
  const topk = readTopkIndex();
  if (topk) {
    const requested = String(queryPatientId || DEFAULT_QUERY_PATIENT_ID || topk.queries[0]?.patient_id || "");
    const candidates = topk.byQuery.get(requested);
    if (!candidates) {
      const error = new Error(`Không có Top-20 cho bệnh nhân query ${requested}.`);
      error.status = 404;
      throw error;
    }
    return { patientId: requested, candidates, source: topk.source };
  }
  const fallback = readStaticRetrieval();
  if (queryPatientId && String(queryPatientId) !== fallback.patientId) {
    const error = new Error(`Demo tĩnh chỉ có query ${fallback.patientId}.`);
    error.status = 404;
    throw error;
  }
  return fallback;
}

function loadContext(queryPatientId) {
  const context = resolveContext(queryPatientId);
  const query = getPatient(context.patientId);
  if (!query) throw new Error(`Không đọc được query ${context.patientId} trong data/raw.`);
  return { query, candidates: context.candidates, source: context.source };
}

function withVerification(queryId, candidate) {
  return { ...candidate, verification: getVerification(`${queryId}:${candidate.patient_id}`) };
}

function normalize(value) {
  return String(value || "").normalize("NFC").toLocaleLowerCase("vi").trim();
}

function clinicalTokens(value) {
  return (normalize(value).match(/[\p{L}\p{N}]+/gu) || [])
    .filter((token) => token.length >= 2 && !STOP_WORDS.has(token));
}

function clinicalFields(patient) {
  const fields = [];
  for (const record of patient.records || []) {
    for (const [title, value] of record.ehr?.details || []) {
      const normalizedTitle = normalize(title);
      if (EHR_METADATA_LABELS.has(normalizedTitle) || EHR_BOILERPLATE_LABELS.has(normalizedTitle)) continue;
      const tokens = clinicalTokens(value);
      if (tokens.length) fields.push({ title, value: String(value), tokens });
    }
  }
  return fields;
}

function phraseSet(tokens) {
  const phrases = new Set();
  for (const width of [3, 2]) {
    for (let index = 0; index <= tokens.length - width; index += 1) {
      phrases.add(tokens.slice(index, index + width).join(" "));
    }
  }
  return phrases;
}

function fieldOverlap(queryField, candidateField) {
  if (normalize(queryField.title) !== normalize(candidateField.title)) return null;
  const queryTerms = new Set(queryField.tokens);
  const candidateTerms = new Set(candidateField.tokens);
  const terms = [...queryTerms].filter((term) => candidateTerms.has(term))
    .sort((left, right) => right.length - left.length || left.localeCompare(right));
  const candidatePhrases = phraseSet(candidateField.tokens);
  const phrases = [...phraseSet(queryField.tokens)].filter((phrase) => candidatePhrases.has(phrase))
    .sort((left, right) => right.length - left.length || left.localeCompare(right));
  if (!phrases.length && terms.length < 2) return null;
  return {
    query_title: queryField.title,
    candidate_title: candidateField.title,
    query_value: queryField.value,
    candidate_value: candidateField.value,
    terms: terms.slice(0, 8),
    phrases: phrases.slice(0, 4),
    score: 3 + terms.length + phrases.reduce((total, phrase) => total + phrase.split(" ").length * 3, 0),
  };
}

function ehrMatches(query, candidate) {
  const matches = [];
  for (const queryField of clinicalFields(query)) {
    for (const candidateField of clinicalFields(candidate)) {
      const overlap = fieldOverlap(queryField, candidateField);
      if (overlap) matches.push(overlap);
    }
  }
  const bestByPair = new Map();
  for (const match of matches) {
    const key = `${normalize(match.query_title)}:${normalize(match.candidate_title)}`;
    if (!bestByPair.has(key) || bestByPair.get(key).score < match.score) bestByPair.set(key, match);
  }
  return [...bestByPair.values()]
    .sort((left, right) => right.score - left.score || left.query_title.localeCompare(right.query_title, "vi"))
    .slice(0, 12);
}

function patientLabs(patient) {
  const labs = new Map();
  for (const record of patient.records || []) {
    for (const lab of record.labs || []) {
      const key = normalize(lab.name);
      if (!key) continue;
      const current = labs.get(key) || { label: lab.name, abnormal: false, results: [] };
      current.abnormal ||= Boolean(lab.flagged);
      current.results.push({
        date: lab.date || "Không rõ ngày",
        value: lab.value ?? "—",
        unit: lab.unit || "",
        range: lab.range || "—",
        flagged: Boolean(lab.flagged),
      });
      labs.set(key, current);
    }
  }
  return labs;
}

function patientModalities(patient) {
  const modalities = new Set();
  for (const record of patient.records || []) {
    for (const modality of ["XQ", "CT", "MRI"]) {
      if ((record.studies?.[modality] || []).length) modalities.add(modality);
    }
  }
  return modalities;
}

export function buildSimilarityEvidence(query, candidate, retrievalCandidate) {
  const matchedEhr = ehrMatches(query, candidate);
  const ehrKeywords = [...new Set(matchedEhr.flatMap((match) => match.terms))].slice(0, 16);
  const ehrPhrases = [...new Set(matchedEhr.flatMap((match) => match.phrases))].slice(0, 12);
  const queryLabs = patientLabs(query);
  const candidateLabs = patientLabs(candidate);
  const sharedLabKeys = [...queryLabs.keys()].filter((name) => candidateLabs.has(name));
  const sharedLabs = sharedLabKeys.map((name) => queryLabs.get(name).label)
    .sort((left, right) => left.localeCompare(right, "vi")).slice(0, 16);
  const sharedLabResults = sharedLabKeys.map((name) => ({
    name: queryLabs.get(name).label,
    query_results: [...queryLabs.get(name).results]
      .sort((left, right) => String(right.date).localeCompare(String(left.date))).slice(0, 3),
    candidate_results: [...candidateLabs.get(name).results]
      .sort((left, right) => String(right.date).localeCompare(String(left.date))).slice(0, 3),
  })).sort((left, right) => left.name.localeCompare(right.name, "vi")).slice(0, 16);
  const sharedAbnormalLabs = sharedLabKeys
    .filter((name) => queryLabs.get(name).abnormal && candidateLabs.get(name).abnormal)
    .map((name) => queryLabs.get(name).label)
    .sort((left, right) => left.localeCompare(right, "vi")).slice(0, 16);
  const queryModalities = patientModalities(query);
  const candidateModalities = patientModalities(candidate);
  return {
    kind: "observable_overlap",
    disclaimer: "Các mục này là bằng chứng trùng quan sát được, không phải giải thích nhân quả cho điểm model.",
    shared_primary_icd_groups: retrievalCandidate.shared_primary_icd_groups || [],
    ehr_keywords: ehrKeywords,
    ehr_phrases: ehrPhrases,
    ehr_matches: matchedEhr,
    shared_labs: sharedLabs,
    shared_lab_results: sharedLabResults,
    shared_abnormal_labs: sharedAbnormalLabs,
    shared_modalities: [...queryModalities].filter((name) => candidateModalities.has(name)),
  };
}

export function listComparisonQueries() {
  const topk = readTopkIndex();
  if (topk) {
    const defaultId = topk.byQuery.has(DEFAULT_QUERY_PATIENT_ID)
      ? DEFAULT_QUERY_PATIENT_ID : topk.queries[0]?.patient_id;
    return { default_query_patient_id: defaultId, source: topk.source, queries: topk.queries };
  }
  const fallback = readStaticRetrieval();
  return {
    default_query_patient_id: fallback.patientId,
    source: fallback.source,
    queries: [{ patient_id: fallback.patientId, split: "", candidate_count: fallback.candidates.length }],
  };
}

export function getComparisonSession(queryPatientId) {
  const { query, candidates, source } = loadContext(queryPatientId);
  return {
    query,
    retrieval_source: source,
    candidates: candidates.map((candidate) => withVerification(query.id, candidate)),
  };
}

export function getComparisonCandidate(queryPatientId, similarPatientId) {
  const { query, candidates } = loadContext(queryPatientId);
  const retrievalCandidate = candidates.find((item) => item.patient_id === similarPatientId);
  if (!retrievalCandidate) return null;
  const patient = getPatient(similarPatientId);
  return patient ? {
    ...withVerification(query.id, retrievalCandidate),
    patient,
    similarity_evidence: buildSimilarityEvidence(query, patient, retrievalCandidate),
  } : null;
}

export function saveComparisonDecision(queryPatientId, similarPatientId, payload) {
  const { query, candidates } = loadContext(queryPatientId);
  const candidate = candidates.find((item) => item.patient_id === similarPatientId);
  if (!candidate) return null;
  const saved = setComparisonVerification(`${query.id}:${similarPatientId}`, payload);
  return {
    queryPatientId: query.id,
    similarPatientId,
    rank: candidate.rank,
    similarityScore: candidate.similarity_score,
    ...saved,
  };
}

export function getComparisonExport(queryPatientId) {
  const { query, candidates } = loadContext(queryPatientId);
  return candidates.map((candidate) => buildComparisonExportRow(
    query.id,
    candidate,
    getVerification(`${query.id}:${candidate.patient_id}`) || {},
  ));
}

export function buildComparisonExportRow(queryId, candidate, review = {}) {
  return {
    query_patient_id: queryId,
    similar_patient_id: candidate.patient_id,
    rank: candidate.rank,
    similarity_score: candidate.similarity_score,
    shared_primary_icd_groups: (candidate.shared_primary_icd_groups || []).join("|"),
    ...Object.fromEntries(REVIEW_CRITERIA.map(([key]) => [
      `${key}_score`, review.criteria_scores?.[key] ?? null,
    ])),
    overall_similarity: review.overall_similarity ?? null,
    legacy_review_level: review.legacy_status || review.status || "",
    note: review.note || "",
    reviewer: review.reviewer || "",
    reviewed_at: review.at || "",
  };
}
