import { Router } from 'express';
import { requireAdmin } from '../middleware/auth.js';
import { assertQueryPatient, getPatientRetrievalItem, getPatientRetrievalOptions, listRetrievalPatients, assertImageItem, getModalityCandidate, getModalityExport, getModalitySession, listModalityMethods, listModalityQueries, saveModalityReview } from '../data/modalityRetrieval.js';

const router = Router();
router.get('/patients', (req, res, next) => { try { res.json(listRetrievalPatients(req.query)); } catch (error) { next(error); } });
router.get('/patient-options', (req, res, next) => { try { res.json(getPatientRetrievalOptions(req.query.patient)); } catch (error) { next(error); } });
router.get('/patient-item', (req, res, next) => { try { res.json(getPatientRetrievalItem(req.query.method, req.query.patient, req.query.item)); } catch (error) { next(error); } });
router.get('/methods', (req, res, next) => { try { res.json(listModalityMethods()); } catch (error) { next(error); } });
for (const kind of ['series', 'png']) router.get(`/imaging/${kind}`, async (req, res, next) => {
  try {
    assertImageItem(req.query.method, req.query.item);
    const params = new URLSearchParams();
    for (const key of ['method', 'item', 'slice', 'resolution', 'windowCenter', 'windowWidth']) if (typeof req.query[key] === 'string') params.set(key, req.query[key]);
    const controller = new AbortController();
    req.on('aborted', () => controller.abort());
    const timer = setTimeout(() => controller.abort(), 55000);
    try {
      const upstream = await fetch(`${process.env.DICOM_WORKER_URL || 'http://imaging:4002'}/${kind}?${params}`, { signal: controller.signal });
      res.status(upstream.status).type(upstream.headers.get('Content-Type') || 'application/json').send(Buffer.from(await upstream.arrayBuffer()));
    } finally { clearTimeout(timer); }
  } catch (error) { if (error.name === 'AbortError') error.status = 504; next(error); }
});
router.get('/:method/queries', (req, res, next) => { try { res.json(listModalityQueries(req.params.method, req.query)); } catch (error) { next(error); } });
router.get('/:method/session', (req, res, next) => { try { assertQueryPatient(req.params.method, req.query.query, req.query.patient); res.json(getModalitySession(req.params.method, req.query.query)); } catch (error) { next(error); } });
router.get('/:method/candidate', (req, res, next) => { try { assertQueryPatient(req.params.method, req.query.query, req.query.patient); res.json(getModalityCandidate(req.params.method, req.query.query, req.query.candidate)); } catch (error) { next(error); } });
router.post('/:method/review', (req, res, next) => { try { assertQueryPatient(req.params.method, req.body?.query, req.body?.patient); res.json(saveModalityReview(req.params.method, req.body?.query, req.body?.candidate, { ...req.body, reviewer: req.user.username })); } catch (error) { next(error); } });
router.get('/:method/export', requireAdmin, (req, res, next) => {
  try {
    const rows = getModalityExport(req.params.method, req.query.query);
    if (req.query.format !== 'csv') return res.attachment('modality-reviews.json').json(rows);
    const cell = value => { let text = String(value ?? ''); if (/^\s*[=+\-@]/.test(text)) text = `'${text}`; return `"${text.replaceAll('"', '""')}"`; };
    const columns = Object.keys(rows[0]);
    const csv = [columns.join(','), ...rows.map(row => columns.map(key => cell(row[key])).join(','))].join('\n');
    res.attachment('modality-reviews.csv').type('text/csv; charset=utf-8').send('\uFEFF' + csv);
  } catch (error) { next(error); }
});
export default router;
