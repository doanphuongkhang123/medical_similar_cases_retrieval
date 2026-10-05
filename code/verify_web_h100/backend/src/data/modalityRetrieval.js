import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { readDocument, saveDocument } from './database.js';

const cache = new Map();
const root = () => String(process.env.MODALITY_ROOT || '').trim();
function failure(message, status = 400) { return Object.assign(new Error(message), { status }); }
function manifest() {
  if (!root()) return { methods: [] };
  const value = JSON.parse(fs.readFileSync(path.join(root(), 'manifest.json'), 'utf8'));
  if (value.schema_version !== 1 || !value.verification?.passed) throw failure('Gói retrieval chưa được kiểm chứng.', 503);
  return value;
}
function descriptor(id) {
  const value = manifest().methods.find(method => method.id === id);
  if (!value) throw failure('Không có nhánh retrieval này.', 404);
  return value;
}
function methodData(id) {
  const info = descriptor(id);
  if (cache.get(id)?.hash === info.sha256) return cache.get(id).value;
  if (path.basename(info.file) !== info.file || info.file === '.' || info.file === '..') throw failure('File retrieval không hợp lệ.', 503);
  const payload = fs.readFileSync(path.join(root(), info.file));
  if (crypto.createHash('sha256').update(payload).digest('hex') !== info.sha256) throw failure('Checksum retrieval không khớp.', 503);
  const data = JSON.parse(payload);
  if (data.id !== id || data.items.length !== info.items) throw failure('Danh mục retrieval không khớp.', 503);
  const index = new Map(data.items.map((item, i) => [item.id, i]));
  if (index.size !== data.items.length) throw failure('Query ID bị trùng.', 503);
  for (const [i, item] of data.items.entries()) {
    for (const hit of item.neighbors) {
      if (!Number.isInteger(hit[0]) || !data.items[hit[0]] || hit[0] === i || data.items[hit[0]].patient_id === item.patient_id || !Number.isFinite(Number(hit[1]))) throw failure('Top-20 không hợp lệ.', 503);
    }
  }
  const value = { data, index, info };
  cache.set(id, { hash: info.sha256, value });
  return value;
}
function itemFrom(method, id) {
  const index = method.index.get(id);
  if (index == null) throw failure('Không có query/candidate trong nhánh này.', 404);
  return method.data.items[index];
}
function summary(item) { return { id: item.id, patient_id: item.patient_id, label: item.label, metadata: item.metadata }; }
function details(item, method) {
  return { ...summary(item), fields: item.fields || [], measurements: item.measurements || null,
    reports: (item.report_ids || []).map(id => method.data.reports[id]),
    candidate_report_ids: item.candidate_report_ids || [], image_locator_available: Boolean(item.archives?.length) };
}
const reviewKey = (method, query, candidate) => JSON.stringify([method.info.sha256, method.info.id, query, candidate]);
function hits(method, query) {
  return query.neighbors.map((hit, i) => {
    const candidate = method.data.items[hit[0]];
    return { ...summary(candidate), rank: i + 1, score: Number(hit[1]), source_score: String(hit[1]),
      ...(method.data.id === 'biochemistry' ? { shared_tests: hit[2], query_coverage: hit[3], jaccard: hit[4] } : {}),
      verification: readDocument('modality_reviews', reviewKey(method, query.id, candidate.id)) };
  });
}
export function listModalityMethods() {
  return manifest().methods.map(({ id, label, model, unit, metric, description, queries, items, pairs }) => ({ id, label, model, unit, metric, description, queries, items, pairs }));
}
export function listModalityQueries(id, { search = '', offset = 0, limit = 50 } = {}) {
  const method = methodData(id);
  const tokens = String(search).normalize('NFC').toLocaleLowerCase('vi').trim().split(/\s+/).filter(Boolean).slice(0, 10);
  const all = method.data.items.filter(item => item.neighbors.length && tokens.every(token => `${item.label} ${item.metadata?.study_uid || ''} ${item.metadata?.series_uid || ''}`.normalize('NFC').toLocaleLowerCase('vi').includes(token)));
  const start = Math.max(0, Math.floor(Number(offset) || 0));
  const size = Math.max(1, Math.min(100, Math.floor(Number(limit) || 50)));
  return { total: all.length, offset: start, limit: size, queries: all.slice(start, start + size).map(summary) };
}
export function getModalitySession(id, queryId) {
  const method = methodData(id);
  const query = itemFrom(method, queryId);
  if (!query.neighbors.length) throw failure('Ca này chưa đủ điều kiện retrieval.', 422);
  return { method: listModalityMethods().find(item => item.id === id), features: method.data.features || [], query: details(query, method), candidates: hits(method, query) };
}
export function getModalityCandidate(id, queryId, candidateId) {
  const method = methodData(id);
  const query = itemFrom(method, queryId);
  const candidate = hits(method, query).find(hit => hit.id === candidateId);
  if (!candidate) throw failure('Candidate không thuộc Top-20 của query này.', 404);
  return { ...candidate, ...details(itemFrom(method, candidateId), method) };
}
export function validateModalityReview(value) {
  if (!Number.isInteger(value?.similarity) || value.similarity < 1 || value.similarity > 5) return 'Mức phù hợp phải là số nguyên từ 1 đến 5.';
  if (value.note != null && (typeof value.note !== 'string' || value.note.length > 5000)) return 'Ghi chú tối đa 5.000 ký tự.';
  return null;
}
export function saveModalityReview(id, queryId, candidateId, value) {
  const error = validateModalityReview(value);
  if (error) throw failure(error);
  const candidate = getModalityCandidate(id, queryId, candidateId);
  const method = methodData(id);
  return saveDocument('modality_reviews', reviewKey(method, queryId, candidateId), {
    method: id, model: method.data.model, source_sha256: method.info.sha256, query_id: queryId, candidate_id: candidateId,
    rank: candidate.rank, score: candidate.score, source_score: candidate.source_score,
    similarity: value.similarity, note: value.note || '', reviewer: value.reviewer, at: new Date().toISOString(),
  }, true);
}
export function getModalityExport(id, queryId) {
  const session = getModalitySession(id, queryId);
  return session.candidates.map(candidate => ({ method: id, model: session.method.model, unit: session.method.unit, query_id: queryId,
    query_patient_id: session.query.patient_id, candidate_id: candidate.id, candidate_patient_id: candidate.patient_id,
    rank: candidate.rank, metric: session.method.metric, score: candidate.source_score,
    shared_tests: candidate.shared_tests ?? '', query_coverage: candidate.query_coverage ?? '',
    similarity: candidate.verification?.similarity ?? '', note: candidate.verification?.note || '',
    reviewer: candidate.verification?.reviewer || '', reviewed_at: candidate.verification?.at || '' }));
}
export function assertImageItem(id, itemId) {
  if (!['ct', 'mri', 'xray'].includes(id)) throw failure('Nhánh này không có ảnh.', 404);
  const method = methodData(id);
  const item = itemFrom(method, itemId);
  if (!item.archives?.length) throw failure('Chưa xác định được ZIP ảnh nguồn.', 404);
  return item;
}
