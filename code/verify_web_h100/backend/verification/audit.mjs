import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { listPatients, getPatient, RAW_ROOT } from '../src/data/rawPatients.js';
import { listComparisonQueries, getComparisonSession, getComparisonCandidate } from '../src/data/comparison.js';
import { buildSlicePreview, encodePng } from '../src/routes/imaging.js';
import { db, DATA_DIR } from '../src/data/database.js';

const summary = { patients: 0, records: 0, ehr_fields: 0, canonical_ehr_fields: 0, diagnoses: 0, medicines: 0, source_medicine_rows: 0, procedures: 0, labs: 0, studies: {}, series: {}, slices: {}, image_errors: [], missing_queries: 0, missing_candidates: 0 };
const stringify = value => typeof value === 'object' ? JSON.stringify(value) : String(value);
for (const row of listPatients()) {
  const patient = getPatient(row.id);
  assert(patient); summary.patients++;
  for (const record of patient.records) {
    summary.records++;
    const dir = path.join(RAW_ROOT, row.id, record.id);
    const ehr = JSON.parse(fs.readFileSync(path.join(dir, 'EHR/text.json'), 'utf8'));
    assert.equal(String(ehr.SoVaoVien), row.id, 'EHR patient ID mismatch');
    assert.equal(String(ehr.SoBenhAn), record.id, 'EHR admission ID mismatch');
    assert.deepEqual(record.ehr.source_fields, ehr);
    for (const value of Object.values(ehr).filter(v => v != null && v !== '')) {
      assert(record.ehr.details.some(([, shown]) => shown === stringify(value)), 'EHR value omitted from visible details');
    }
    summary.ehr_fields += Object.keys(ehr).length;
    if (process.env.STRUCTURED_ROOT) {
      assert(record.structured_available, 'Structured patient record is missing');
      const packet = JSON.parse(fs.readFileSync(path.join(process.env.STRUCTURED_ROOT, row.id, `${record.id}.json`), 'utf8'));
      assert.deepEqual(record.canonical_ehr, packet.canonical_ehr);
      assert.deepEqual(record.demographics, packet.demographics);
      if (packet.source_medicines) {
        assert.deepEqual(record.source_medicines,packet.source_medicines);
        summary.source_medicine_rows += packet.source_medicines.length;
        for (const event of packet.source_medicines) { assert.equal(event.patient_id,row.id); assert.equal(event.visit_id,record.id); }
      }
      summary.canonical_ehr_fields += Object.keys(packet.canonical_ehr).length;
      for (const value of Object.values(packet.canonical_ehr).filter(v => v != null && v !== '')) assert(record.ehr.details.some(([, shown]) => shown === stringify(value)), 'Canonical EHR value omitted');
      for (const name of ['diagnoses','medicines','procedures']) {
        assert.deepEqual(record[name], packet[name]); summary[name] += record[name].length;
        for (const event of record[name]) { assert.equal(event.patient_id, row.id); assert.equal(event.visit_id, record.id); }
      }
    }
    const labSource = JSON.parse(fs.readFileSync(path.join(dir, 'lab_result/lab.json'), 'utf8'));
    assert.equal(String(labSource.SoVaoVien), row.id, 'Lab patient ID mismatch');
    assert.equal(String(labSource.SoBenhAn), record.id, 'Lab admission ID mismatch');
    const labs = labSource.results || [];
    assert.deepEqual(record.labs.map(lab => lab.source_fields), labs); summary.labs += labs.length;
    for (const modality of ['CT', 'MRI', 'XQ']) {
      summary.studies[modality] = (summary.studies[modality] || 0) + record.studies[modality].length;
      for (const study of record.studies[modality]) {
        for (const series of study.series) {
          summary.series[modality] = (summary.series[modality] || 0) + 1;
          summary.slices[modality] = (summary.slices[modality] || 0) + series.sliceCount;
          const seriesDir = path.join(dir, modality, study.id, series.id);
          try {
            const npyPath = path.join(seriesDir, 'raw.npy');
            const meta = JSON.parse(fs.readFileSync(path.join(seriesDir, 'meta.json'), 'utf8'));
            const preview = buildSlicePreview({ npyPath, meta }, Math.floor(series.sliceCount / 2));
            assert.equal(preview.sliceCount, series.sliceCount);
            assert.equal(Buffer.from(preview.pixels, 'base64').length, preview.width * preview.height);
            assert.deepEqual(series.shape, meta.shape);
            assert(encodePng(preview).length > 32);
          } catch (error) { summary.image_errors.push({ patient: row.id, record: record.id, modality, series: series.id, error: error.message }); }
        }
      }
    }
  }
  if (summary.patients % 25 === 0) console.log(JSON.stringify({ progress_patients: summary.patients }));
}
const queries = listComparisonQueries(); summary.queries = queries.queries.length; summary.candidate_pairs = 0;
for (const q of queries.queries) {
  let session;
  try { session = getComparisonSession(q.patient_id); } catch { summary.missing_queries++; continue; }
  for (const candidate of session.candidates) {
    summary.candidate_pairs++;
    if (!getComparisonCandidate(q.patient_id, candidate.patient_id)) summary.missing_candidates++;
  }
}
summary.sqlite_integrity = db.prepare('PRAGMA integrity_check').get().integrity_check;
summary.database_rows = db.prepare('SELECT namespace, count(*) AS count FROM documents GROUP BY namespace').all();
summary.review_history_rows = db.prepare('SELECT count(*) AS count FROM review_history').get().count;
summary.verified_at = new Date().toISOString();
fs.writeFileSync(path.join(DATA_DIR, 'dataset_audit.json'), JSON.stringify(summary, null, 2));
console.log(JSON.stringify({ ...summary, image_errors: summary.image_errors.length }));
assert.equal(summary.patients, 171); assert.equal(summary.records, 184);
assert.deepEqual(summary.series, { CT: 433, MRI: 646, XQ: 143 });
assert.equal(summary.queries, 10); assert.equal(summary.candidate_pairs, 200);
assert.equal(summary.missing_queries, 0); assert.equal(summary.missing_candidates, 0);
assert.equal(summary.image_errors.length, 0); assert.equal(summary.sqlite_integrity, 'ok');
if (process.env.STRUCTURED_ROOT) { assert.equal(summary.diagnoses,2163); assert.equal(summary.medicines,11233); assert.equal(summary.procedures,6862); }
