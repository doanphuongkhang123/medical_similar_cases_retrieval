import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'modality-review-'));
process.env.DATA_DIR = path.join(temporary, 'database');
process.env.MODALITY_ROOT = temporary;
const methods = ['text', 'biochemistry', 'ct'].map(id => {
  const data = { id, items: [
    { id: 'q', patient_id: 'p1', label: 'Query abc', metadata: { series_uid: 'series-q' }, fields: [['Mô tả', 'query']], measurements: [0, null], neighbors: [[1, '0.75', 3, .5, .4]], archives: ['CT/example.zip'], report_ids: [] },
    { id: 'c', patient_id: 'p2', label: 'Candidate', metadata: {}, fields: [['Mô tả', 'candidate']], measurements: [0, 2], neighbors: [[0, '0.75', 3, .5, .4]], report_ids: [] },
    { id: 'insufficient', patient_id: 'p3', label: 'No results', metadata: {}, neighbors: [] },
  ], reports: {}, features: [{ name: 'value' }, { name: 'missing' }] };
  const file = id + '.json'; const buffer = Buffer.from(JSON.stringify(data)); fs.writeFileSync(path.join(temporary, file), buffer);
  return { id, file, model: `model-${id}`, unit: id === 'text' ? 'patient' : 'visit', metric: id === 'biochemistry' ? 'cosine_distance' : 'cosine_similarity', items: 3, queries: 2, pairs: 2, sha256: crypto.createHash('sha256').update(buffer).digest('hex') };
});
fs.writeFileSync(path.join(temporary, 'manifest.json'), JSON.stringify({ schema_version: 1, verification: { passed: true }, methods }));
const api = await import('../src/data/modalityRetrieval.js');
const database = await import('../src/data/database.js');
after(() => { database.db.close(); fs.rmSync(temporary, { recursive: true, force: true }); });

test('query catalogue filters insufficient rows, supports search and bounded pagination', () => {
  assert.equal(api.listModalityMethods().length, 3);
  assert.equal(api.listModalityQueries('text').total, 2);
  assert.equal(api.listModalityQueries('text', { search: 'ABC series-q', limit: 999 }).queries[0].id, 'q');
  assert.equal(api.listModalityQueries('text', { offset: 1, limit: 1 }).queries[0].id, 'c');
  assert.throws(() => api.getModalitySession('text', 'insufficient'), /đủ điều kiện/);
});
test('preserves source score, zero/missing values and hides archive paths from API details', () => {
  const session = api.getModalitySession('biochemistry', 'q');
  assert.equal(session.candidates[0].source_score, '0.75');
  assert.equal(session.candidates[0].rank, 1);
  assert.deepEqual(session.query.measurements, [0, null]);
  assert.equal(session.candidates[0].query_coverage, .5);
  assert.equal('archives' in session.query, false);
  assert.equal(api.getModalityCandidate('text', 'q', 'c').fields[0][1], 'candidate');
  assert.throws(() => api.getModalityCandidate('text', 'q', 'q'), /Top-20/);
  assert.throws(() => api.getModalityCandidate('text', 'q', 'insufficient'), /Top-20/);
  assert.throws(() => api.assertImageItem('text', 'q'), /không có ảnh/);
  assert.equal(api.assertImageItem('ct', 'q').id, 'q');
});
test('reviews isolate methods and original fusion reviews, keep rescore history and source IDs', () => {
  database.saveDocument('reviews', 'q:c', { note: 'original fusion' });
  api.saveModalityReview('text', 'q', 'c', { similarity: 4, note: 'first', reviewer: 'r1' });
  api.saveModalityReview('text', 'q', 'c', { similarity: 5, note: 'second', reviewer: 'r2' });
  assert.equal(api.getModalityCandidate('text', 'q', 'c').verification.similarity, 5);
  assert.equal(api.getModalityCandidate('biochemistry', 'q', 'c').verification, null);
  assert.equal(database.readDocument('reviews', 'q:c').note, 'original fusion');
  assert.equal(database.db.prepare("SELECT count(*) n FROM review_history WHERE namespace='modality_reviews'").get().n, 2);
  assert.equal(api.getModalityExport('text', 'q')[0].reviewer, 'r2');
  assert.equal(api.getModalityExport('text', 'q')[0].score, '0.75');
  assert.throws(() => api.saveModalityReview('text', 'q', 'q', { similarity: 3 }), /Top-20/);
  assert.throws(() => api.saveModalityReview('text', 'q', 'c', { similarity: 3.5 }), /số nguyên/);
  assert.throws(() => api.saveModalityReview('text', 'q', 'c', { similarity: 3, note: 'x'.repeat(5001) }), /5.000/);
});
test('refuses source checksum changes and unknown methods', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(temporary, 'manifest.json')));
  manifest.methods[0].sha256 = 'invalid';
  fs.writeFileSync(path.join(temporary, 'manifest.json'), JSON.stringify(manifest));
  assert.throws(() => api.getModalitySession('text', 'q'), /Checksum/);
  assert.throws(() => api.listModalityQueries('../text'), /Không có nhánh/);
});
