import { readDocuments, readDocument, saveDocument } from './database.js';
export function getVerifications() { return readDocuments('reviews'); }
export function getVerification(key) { return readDocument('reviews', key); }
export function setVerification(key, { status, note, reviewer }) {
  return saveDocument('reviews', key, { status, note: note || '', reviewer: reviewer || 'unknown', at: new Date().toISOString() }, true);
}
export function setComparisonVerification(key, { criteria_scores, overall_similarity, note, reviewer }) {
  const previous = getVerification(key) || {};
  return saveDocument('reviews', key, {
    criteria_scores, overall_similarity,
    ...(previous.legacy_status || previous.status ? { legacy_status: previous.legacy_status || previous.status } : {}),
    note: note || '', reviewer: reviewer || 'unknown', at: new Date().toISOString(),
  }, true);
}
