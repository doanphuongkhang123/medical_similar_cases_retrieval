import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'patient-complete-test-'));
after(()=>fs.rmSync(dir,{recursive:true,force:true}));
process.env.RAW_ROOT=path.join(dir,'raw');process.env.STRUCTURED_ROOT=path.join(dir,'structured');
const ehr=path.join(process.env.RAW_ROOT,'p1','v1','EHR');fs.mkdirSync(ehr,{recursive:true});
fs.writeFileSync(path.join(ehr,'text.json'),JSON.stringify({SoVaoVien:'p1',SoBenhAn:'v1',Mach:0,ChanDoanRaVien:'source review text'}));
const supplement=path.join(process.env.STRUCTURED_ROOT,'p1');fs.mkdirSync(supplement,{recursive:true});
const payload={patient_id:'p1',visit_id:'v1',canonical_ehr:{ChanDoanRaVien:'canonical text',ChieuCao:0},demographics:{age_at_visit:60},diagnoses:[{diagnosis_id:'d1'}],medicines:[{medicine_id:'m1',dose_noon:'0'}],source_medicines:[{source_row:2,HamLuong:'500 mg',SoNgay:'0.5'},{source_row:3,HamLuong:'250 mg',SoNgay:'0'}],procedures:[{procedure_id:'s1'}]};
fs.writeFileSync(path.join(supplement,'v1.json'),JSON.stringify(payload));
const {getPatient,resolveRawNpy}=await import('../src/data/rawPatients.js');
test('preserves all raw fields, zero values and complete events for the exact selected admission',()=>{
 const patient=getPatient('p1');const record=patient.records[0];
 assert.equal(record.structured_available,true);assert.deepEqual(record.medicines,payload.medicines);
 assert.deepEqual(record.procedures,payload.procedures);assert.deepEqual(record.diagnoses,payload.diagnoses);
 assert.deepEqual(record.source_medicines,payload.source_medicines);
 assert.equal(record.demographics.age_at_visit,60);
 assert(record.ehr.details.some(([title,value])=>title==='Mach'&&value==='0'));
 assert(record.ehr.details.some(([,value])=>value==='source review text'));
 assert(record.ehr.details.some(([,value])=>value==='canonical text'));
 assert(record.ehr.details.some(([title,value])=>title==='ChieuCao (bệnh án gốc)'&&value==='0'));
});
test('rejects a supplementary record belonging to another patient',()=>{
 fs.writeFileSync(path.join(supplement,'v1.json'),JSON.stringify({...payload,patient_id:'p2'}));
 assert.throws(()=>getPatient('p1'),/không khớp/);
});
test('rejects parent directory segments in patient and image lookups',()=>{
 assert.equal(getPatient('..'),null);
 assert.equal(resolveRawNpy({patientId:'..',recordId:'v1',modality:'CT',studyId:'s',seriesId:'r'}),null);
});
