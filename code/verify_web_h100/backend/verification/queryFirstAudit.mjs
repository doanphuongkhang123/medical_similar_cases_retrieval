// Run on a data host with MODALITY_ROOT, TOPK_FILE and an isolated DATA_DIR.
// This writes only aggregate counts; it never recomputes embeddings or rankings.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import { listRetrievalPatients, getPatientRetrievalOptions, getModalitySession } from '../src/data/modalityRetrieval.js';
import { db } from '../src/data/database.js';
const all = [];
for (let offset = 0; ; offset += 100) {
  const page = listRetrievalPatients({ offset, limit: 100 });
  all.push(...page.queries);
  if (all.length >= page.total) break;
}
assert.equal(all.length, 3099); assert.equal(new Set(all.map(item => item.id)).size, all.length);
const counts = Object.fromEntries(['biochemistry', 'text', 'ct', 'mri', 'xray', 'fusion'].map(id => [id, { available_patients: 0, eligible_queries: 0, unavailable_patients: 0 }]));
let imageOnly = 0, multiVisit = 0;
for (const patient of all) {
  const options = getPatientRetrievalOptions(patient.id);
  assert.equal(options.methods.length, 6);
  if (!options.methods.find(method => method.id === 'text').available) imageOnly++;
  if (options.methods.find(method => method.id === 'biochemistry').queries.length > 1) multiVisit++;
  for (const method of options.methods) {
    counts[method.id][method.available ? 'available_patients' : 'unavailable_patients']++;
    counts[method.id].eligible_queries += method.queries.length;
    for (const item of method.queries) assert.equal(item.patient_id, patient.id);
    assert.equal(method.available, Boolean(method.queries.length));
    if (!method.available) assert.ok(method.reason);
    if (method.id === 'fusion' && method.available) {
      const session = getModalitySession('fusion', patient.id);
      assert.equal(session.candidates.length, 20);
      assert.equal(session.query.patient_id, patient.id);
      for (const [i, hit] of session.candidates.entries()) {
        assert.equal(hit.rank, i + 1); assert.ok(Number.isFinite(hit.score)); assert.notEqual(hit.patient_id, patient.id);
      }
    }
  }
}
assert.equal(imageOnly, 4); assert.ok(multiVisit > 0);
assert.equal(counts.text.eligible_queries, 3095); assert.equal(counts.fusion.eligible_queries, 3095);
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const report = { passed: true, at: new Date().toISOString(), host: process.env.AUDIT_HOST, patient_count: all.length, image_only_patients: imageOnly, multi_visit_patients: multiVisit, counts,
  sources: { modality_manifest: { path: process.env.MODALITY_ROOT + '/manifest.json', sha256: hash(process.env.MODALITY_ROOT + '/manifest.json') }, fusion_csv: { path: process.env.TOPK_FILE, sha256: hash(process.env.TOPK_FILE) } } };
console.log(JSON.stringify(report, null, 2)); db.close();
