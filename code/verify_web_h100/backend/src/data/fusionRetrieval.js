import fs from 'node:fs';
import crypto from 'node:crypto';

// This is the existing patient-fusion run, not a fusion of the new single-modality models.
export const FUSION_SOURCE_SHA256 = 'b32e3d9fa968085740cdf8f50eb839744535da56507e00c1671ce4e3c1c32b54';
let cached;
const failure = message => Object.assign(new Error(message), { status: 503 });
function cells(line) {
  const values = []; let value = '', quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') { if (quoted && line[i + 1] === '"') { value += '"'; i++; } else quoted = !quoted; }
    else if (c === ',' && !quoted) { values.push(value); value = ''; } else value += c;
  }
  if (quoted) throw failure('CSV fusion có ô chưa đóng dấu nháy.');
  return [...values, value];
}
export function loadFusionData(profiles) {
  const file = process.env.TOPK_FILE;
  if (!file) return null;
  const stat = fs.statSync(file);
  const expected = process.env.FUSION_TOPK_SHA256 || FUSION_SOURCE_SHA256;
  const signature = JSON.stringify([file, stat.mtimeMs, stat.size, expected, profiles.info.sha256]);
  if (cached?.signature === signature) return cached.value;
  const buffer = fs.readFileSync(file);
  const sha256 = crypto.createHash('sha256').update(buffer).digest('hex');
  if (sha256 !== expected) throw failure('Checksum fusion không khớp nguồn đã xác nhận.');
  const lines = buffer.toString('utf8').replace(/^\uFEFF/, '').trim().split(/\r?\n/);
  const header = cells(lines.shift());
  const required = ['query_patient_id', 'related_patient_id', 'rank', 'cosine_similarity'];
  const positions = Object.fromEntries(required.map(key => [key, header.indexOf(key)]));
  if (required.some(key => positions[key] < 0)) throw failure('CSV fusion thiếu cột.');
  const items = profiles.data.items.map(profile => ({ id: profile.patient_id, patient_id: profile.patient_id,
    label: `Bệnh nhân ${profile.patient_id}`, metadata: { profile_id: profile.id }, neighbors: [] }));
  const index = new Map(items.map((item, i) => [item.id, i]));
  if (index.size !== items.length) throw failure('Danh mục fusion bị trùng mã bệnh nhân.');
  for (const line of lines) {
    const row = cells(line), query = index.get(row[positions.query_patient_id]), candidate = index.get(row[positions.related_patient_id]);
    const rank = Number(row[positions.rank]), score = row[positions.cosine_similarity];
    if (query == null || candidate == null || query === candidate || !Number.isInteger(rank) || rank < 1 || rank > 20 || !score.trim() || !Number.isFinite(Number(score)) || Math.abs(Number(score)) > 1.000001) throw failure('Top-20 fusion có ID, rank hoặc score không hợp lệ.');
    items[query].neighbors.push([candidate, score, rank]);
  }
  for (const item of items) {
    item.neighbors.sort((a, b) => a[2] - b[2]);
    if (new Set(item.neighbors.map(hit => hit[0])).size !== item.neighbors.length || item.neighbors.some((hit, i) => hit[2] !== i + 1 || (i && Number(hit[1]) > Number(item.neighbors[i - 1][1])))) throw failure('Thứ hạng fusion không hợp lệ.');
  }
  const info = { id: 'fusion', label: 'Fusion', model: 'Attention Pool', unit: 'bệnh nhân', metric: 'cosine_similarity',
    sha256, items: items.length, queries: items.filter(item => item.neighbors.length).length, pairs: items.reduce((sum, item) => sum + item.neighbors.length, 0) };
  const value = { info, data: { id: 'fusion', model: info.model, items, reports: {} }, index,
    byPatient: new Map(items.map(item => [item.patient_id, [item]])) };
  cached = { signature, value };
  return value;
}
