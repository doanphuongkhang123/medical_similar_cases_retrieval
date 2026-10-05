import React, { useEffect, useRef, useState } from 'react';
import { Home, Search } from 'lucide-react';
import { apiFetch } from '../api.js';
import { C, FONTS } from '../theme.js';
import ScanViewport from './ScanViewport.jsx';

const queryColor = '#EDF6FF', candidateColor = '#FFF8ED';
const button = { padding: '8px 12px', border: `1px solid ${C.border}`, borderRadius: 7, background: 'white', color: C.ink, cursor: 'pointer' };
const input = { ...button, width: '100%', boxSizing: 'border-box', minWidth: 0 };
const muted = { color: C.inkFaint };
const shortModelNames = { biochemistry: 'Autoencoder', text: 'Qwen', ct: 'CT-CLIP', mri: '3DINO', xray: 'MedSigLIP', fusion: 'Attention Pool' };
async function request(path, signal, options = {}) {
  const response = await apiFetch(`/api/modality/${path}`, { ...options, signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Không tải được retrieval');
  return data;
}
const params = values => new URLSearchParams(values).toString();
function PairRow({ label, values, id }) {
  return <tr data-modality-row={id || label} style={{ verticalAlign: 'top', borderTop: `1px solid ${C.border}` }}>
    <th scope="row" style={{ padding: 12, textAlign: 'left', fontSize: 12 }}>{label}</th>
    {values.map((value, i) => <td key={i} data-modality-side={i === 0 ? 'query' : 'candidate'} style={{ padding: 12, background: i === 0 ? queryColor : candidateColor, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.6 }}>{value ?? <span style={muted}>Không có dữ liệu</span>}</td>)}
  </tr>;
}

function SourceImage({ method, item }) {
  const [series, setSeries] = useState(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    setSeries(null); setError('');
    const controller = new AbortController();
    if (!item.image_locator_available) { setError('Chưa xác định được ảnh nguồn của bộ này.'); return () => controller.abort(); }
    request(`imaging/series?${params({ method: method.id, item: item.id })}`, controller.signal)
      .then(data => { if (!controller.signal.aborted) setSeries({ ...data, sliceUrl: `/api/modality/imaging/png?${params({ method: method.id, item: item.id })}` }); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [method.id, item.id, reload]);
  if (error) return <div style={muted}>{error}<div><button style={button} onClick={() => setReload(value => value + 1)}>Tải lại ảnh</button></div></div>;
  if (!series) return <div role="status">Đang đọc danh mục lát ảnh nguồn…</div>;
  return <div data-modality-image={method.id}>
    <div style={{ fontSize: 11, ...muted, marginBottom: 8 }}>{series.sliceCount} lát/frame nguồn · PNG thang xám · khác tensor đã tiền xử lý cho encoder</div>
    <ScanViewport key={`${method.id}-${item.id}`} series={series} modality={{ ct: 'CT', mri: 'MRI', xray: 'XQ' }[method.id]} patient={{ id: item.patient_id }} />
  </div>;
}

const reportStatus = {
  exact_order_reports: 'Report đã nối theo order chính xác',
  no_confirmed_report: 'Chưa có report được xác nhận',
  no_exact_series_patient_outcome: 'Chưa có liên kết series/bệnh nhân chính xác',
  ambiguous_series_report_outcomes: 'Liên kết report còn mơ hồ',
  matched: 'Đã nối bệnh án trong nguồn',
  source_directory_label_only_not_validated_visit: 'Tên thư mục nguồn; chưa xác nhận bệnh án',
  unique_date_report_candidates: 'Có report ứng viên theo ngày; chưa xác nhận',
  multiple_date_order_candidates: 'Nhiều chỉ định cùng ngày; chưa xác nhận report',
  unresolved_multiple_outcomes: 'Các liên kết chưa thống nhất',
  exact_order_no_reports: 'Đã nối chỉ định; chưa có report',
};
function ImageReports({ items }) {
  const rows = [];
  const labels = [['study_uid', 'Study UID'], ['series_uid', 'Series UID'], ['series_description', 'Mô tả series'], ['sequence', 'Chuỗi MRI'], ['body_part_group', 'Vùng giải phẫu'], ['accession_number', 'Mã lần chụp'], ['source_ehr_join_status', 'Trạng thái nối bệnh án'], ['report_link_status', 'Trạng thái report'], ['auxiliary_xray_overlay', 'Ảnh overlay phụ trợ']];
  for (const [key, label] of labels) if (items.some(item => item.metadata[key])) rows.push(<PairRow key={key} label={label} values={items.map(item => key === 'auxiliary_xray_overlay' ? String(item.metadata[key]).toLowerCase() === 'true' ? 'Có' : 'Không' : reportStatus[item.metadata[key]] || item.metadata[key] || null)} />);
  for (const [key, label] of [['MO_TA', 'Mô tả trong report'], ['KET_LUAN', 'Kết luận trong report'], ['GIA_TRI', 'Giá trị trong report'], ['report_note', 'Report đầy đủ đã xác nhận']]) {
    rows.push(<PairRow key={key} label={label} values={items.map(item => item.reports.length ? item.reports.map(report => <div key={report.report_id} style={{ marginBottom: 12 }}><strong style={{ fontSize: 11 }}>Report {report.report_id} · Bệnh án {report.visit_id}</strong><div>{report[key] || <span style={muted}>Không có trường này trong report</span>}</div></div>) : <span style={muted}>Chưa có report nối chắc chắn; vẫn giữ kết quả retrieval ảnh.</span>)} />);
  }
  rows.push(<PairRow key="uncertain" label="Report còn cần xác nhận" values={items.map(item => item.candidate_report_ids.length ? `${item.candidate_report_ids.length} ID report ứng viên; chưa gán nội dung cho series này.` : 'Không có report ứng viên')} />);
  return rows;
}
function Comparison({ session, candidate }) {
  const items = [session.query, candidate];
  const row = (label, values) => <PairRow key={label} label={label} values={values} />;
  const isImage = ['ct', 'mri', 'xray'].includes(session.method.id);
  return <section aria-label="So sánh theo modality" style={{ overflowX: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, background: 'white' }}>
    <table style={{ width: '100%', minWidth: 680, tableLayout: 'fixed', borderCollapse: 'collapse', fontSize: 12 }}>
      <colgroup><col style={{ width: '20%' }} /><col style={{ width: '40%' }} /><col style={{ width: '40%' }} /></colgroup>
      <thead><tr>{['Trường thông tin', `Query · ${session.query.id}`, `Candidate #${candidate.rank} · ${candidate.id}`].map((label, i) => <th key={i} style={{ textAlign: 'left', padding: 12, background: i === 1 ? '#DCEEFF' : i === 2 ? '#FCEACD' : 'white', overflowWrap: 'anywhere' }}>{label}</th>)}</tr></thead>
      <tbody>
        {row('Mã bệnh nhân nguồn', items.map(item => item.patient_id))}
        {row('Đơn vị retrieval', items.map(() => session.method.unit))}
        {session.method.id === 'text' && <>
          {row('Số lần nhập viện', items.map(item => item.metadata.visit_count))}
          {row('Các bệnh án được dùng', items.map(item => (item.metadata.visits || []).join(', ')))}
          {row('Mô tả bệnh', items.map(item => item.fields.find(([label]) => label === 'Mô tả bệnh đưa vào model')?.[1]))}
        </>}
        {session.method.id === 'biochemistry' && <>
          {row('Ngày nhập viện', items.map(item => item.metadata.admission))}
          {row('Ngày ra viện', items.map(item => item.metadata.discharge))}
          {row('Số chỉ số có dữ liệu', items.map(item => item.metadata.observed_tests))}
          {candidate.shared_tests != null && row('Overlap của cặp', [null, `${candidate.shared_tests} chỉ số chung · phủ ${(candidate.query_coverage * 100).toFixed(1)}% query`])}
          {session.features.map((feature, index) => <PairRow key={feature.feature_id} id={feature.feature_id} label={<>{feature.name}<div style={{ fontWeight: 400, fontSize: 11, ...muted }}>{feature.unit}{feature.unit_status === 'inferred_unverified' ? ' · đơn vị suy luận chưa xác nhận' : ''}</div></>} values={items.map(item => item.measurements?.[index] == null ? null : `${item.measurements?.[index]} ${feature.unit}`)} />)}
        </>}
        {isImage && <>
          <PairRow label="Ảnh nguồn của series" values={items.map(item => <SourceImage method={session.method} item={item} />)} />
          <ImageReports items={items} />
        </>}
      </tbody>
    </table>
  </section>;
}

function FusionBranch({ branch, candidateBranch, patientIds, rank }) {
  const empty = { id: 'Không có dữ liệu', patient_id: '', metadata: {}, fields: [], reports: [], candidate_report_ids: [] };
  const [ids, setIds] = useState([branch.queries[0]?.id || '', candidateBranch?.queries[0]?.id || '']);
  const [data, setData] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError('');
    Promise.all(ids.map((id, side) => id ? request(`patient-item?${params({ method: branch.id, patient: patientIds[side], item: id })}`, controller.signal) : Promise.resolve(null)))
      .then(values => { if (!controller.signal.aborted) setData(values); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [branch.id, ids, patientIds]);
  if (error) return <p role="alert">{error}</p>;
  const method = data?.find(Boolean)?.method;
  return <div>
    <div style={{ display: 'grid', gridTemplateColumns: '20% 40% 40%', margin: '10px 0' }}><span>Bộ dữ liệu hiển thị</span>
      {[branch, candidateBranch].map((info, side) => <label key={side} style={{ padding: '0 12px' }}>{side === 0 ? 'Query' : 'Candidate'}<select aria-label={`Fusion ${branch.id} ${side === 0 ? 'query' : 'candidate'}`} style={input} value={ids[side]} disabled={!info?.queries.length} onChange={event => setIds(values => values.map((id, i) => i === side ? event.target.value : id))}>
        {!info?.queries.length && <option value="">Không có dữ liệu</option>}{info?.queries.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>)}
    </div>
    {method ? <Comparison session={{ method, features: data.find(Boolean).features, query: data[0]?.item || { ...empty, patient_id: patientIds[0] } }} candidate={{ ...(data[1]?.item || { ...empty, patient_id: patientIds[1] }), rank }} /> : <p>Đang tải dữ liệu đối chiếu…</p>}
  </div>;
}
function FusionComparison({ session, candidate }) {
  const [opened, setOpened] = useState({ text: true });
  const patientIds = React.useMemo(() => [session.query.patient_id, candidate.patient_id], [session.query.patient_id, candidate.patient_id]);
  return <section aria-label="So sánh fusion">
    <div style={{ marginBottom: 10 }}>Query · {patientIds[0]} ↔ Candidate #{candidate.rank} · {patientIds[1]}</div>
    {session.query.branches.map(branch => {
      const other = candidate.branches.find(item => item.id === branch.id);
      return <details key={branch.id} open={Boolean(opened[branch.id])} onToggle={event => { const value = event.currentTarget.open; setOpened(previous => previous[branch.id] === value ? previous : { ...previous, [branch.id]: value }); }} style={{ background: 'white', padding: 12, border: `1px solid ${C.border}`, borderRadius: 8, marginBottom: 10 }}>
        <summary style={{ cursor: 'pointer' }}>{branch.label} · Query: {branch.queries.length} · Candidate: {other?.queries.length || 0}</summary>
        {opened[branch.id] && (branch.queries.length || other?.queries.length ? <FusionBranch key={`${patientIds.join(':')}:${branch.id}`} branch={branch} candidateBranch={other} patientIds={patientIds} rank={candidate.rank} /> : <p style={muted}>Hai phía không có dữ liệu trong nhánh này.</p>)}
      </details>;
    })}
  </section>;
}

export default function ModalityReview({ user, onBackHome }) {
  const [methodId, setMethodId] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [catalogue, setCatalogue] = useState({ queries: [], total: 0 });
  const [patientId, setPatientId] = useState('');
  const [options, setOptions] = useState(null);
  const [queryId, setQueryId] = useState('');
  const [session, setSession] = useState(null);
  const [selectedId, setSelectedId] = useState('');
  const [candidate, setCandidate] = useState(null);
  const [score, setScore] = useState('');
  const [criteria, setCriteria] = useState({});
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const activePair = useRef('');
  activePair.current = JSON.stringify([patientId, methodId, queryId, selectedId]);
  useEffect(() => {
    const controller = new AbortController(); setError('');
    const timer = setTimeout(() => request(`patients?${params({ search, offset, limit: 50 })}`, controller.signal).then(data => {
      if (!controller.signal.aborted) { setCatalogue(data); setPatientId(previous => previous || data.queries[0]?.id || ''); }
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); }), 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [search, offset]);
  useEffect(() => {
    setOptions(null); setQueryId(''); setSession(null); setCandidate(null); setNotice(''); setError('');
    if (!patientId) return;
    const controller = new AbortController();
    request(`patient-options?${params({ patient: patientId })}`, controller.signal).then(data => {
      if (!controller.signal.aborted) { setOptions(data); setMethodId(previous => data.methods.some(method => method.id === previous && method.available) ? previous : data.methods.find(method => method.id === 'fusion' && method.available)?.id || data.methods.find(method => method.available)?.id || ''); }
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [patientId]);
  useEffect(() => {
    setSession(null); setCandidate(null); setNotice('');
    const selected = options?.methods.find(method => method.id === methodId && method.available);
    setQueryId(selected?.queries[0]?.id || '');
  }, [options, methodId]);
  useEffect(() => {
    setSession(null); setCandidate(null); setError(''); setNotice('');
    if (!queryId || options?.patient_id !== patientId || !options.methods.find(method => method.id === methodId)?.queries.some(item => item.id === queryId)) return;
    const controller = new AbortController();
    request(`${methodId}/session?${params({ query: queryId, patient: patientId })}`, controller.signal).then(data => { if (!controller.signal.aborted) { setSession(data); setSelectedId(data.candidates[0]?.id || ''); } }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [methodId, queryId, patientId, options]);
  useEffect(() => {
    if (!session || !selectedId) return;
    const controller = new AbortController(); setCandidate(null); setError(''); setNotice('');
    request(`${session.method.id}/candidate?${params({ query: session.query.id, candidate: selectedId, patient: session.query.patient_id })}`, controller.signal).then(data => { if (!controller.signal.aborted) { setCandidate({ ...data, loadedFor: JSON.stringify([session.method.id, session.query.id]) }); setScore((session.method.id === 'fusion' ? data.verification?.overall_similarity : data.verification?.similarity) || ''); setCriteria(data.verification?.criteria_scores || {}); setNote(data.verification?.note || ''); } }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [session, selectedId]);
  const methods = options?.patient_id === patientId ? options.methods : [];
  const selectedMethod = methods.find(method => method.id === methodId);
  const isFusion = methodId === 'fusion';
  // Never render or save an old pair while the user changes patient, method or subquery.
  const currentSession = session?.query.patient_id === patientId && session.method.id === methodId && session.query.id === queryId ? session : null;
  const currentCandidate = currentSession && candidate?.id === selectedId && candidate.loadedFor === JSON.stringify([methodId, queryId]) ? candidate : null;
  async function save() {
    if (!currentCandidate) return;
    const pair = activePair.current;
    setSaving(true); setError(''); setNotice('');
    try {
      const review = await request(`${methodId}/review`, undefined, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ patient: patientId, query: currentSession.query.id, candidate: currentCandidate.id,
        ...(isFusion ? { criteria_scores: Object.fromEntries(currentSession.review_criteria.map(([key]) => [key, Number(criteria[key])])), overall_similarity: Number(score) } : { similarity: Number(score) }), note }) });
      if (pair !== activePair.current) return;
      setCandidate(value => ({ ...value, verification: review })); setNotice('Đã lưu đánh giá.');
    } catch (error) { if (pair === activePair.current) setError(error.message); } finally { setSaving(false); }
  }
  async function download(format) {
    try {
      const response = await apiFetch(`/api/modality/${methodId}/export?${params({ query: currentSession.query.id, format })}`);
      if (!response.ok) throw new Error('Không xuất được kết quả.');
      const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `retrieval-${methodId}.${format}`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setError(error.message); }
  }
  return <main style={{ minHeight: '100vh', background: C.bg, color: C.ink, fontFamily: 'Inter, sans-serif', padding: 20 }}>
    <style>{FONTS}</style>
    <button onClick={onBackHome} style={button}><Home size={14} /> Trang chính</button>
    <h1 style={{ fontSize: 23 }}>Retrieval theo query</h1>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 14, marginBottom: 15 }}>
      <label><Search size={13} /> Tìm bệnh nhân query<input aria-label="Tìm bệnh nhân query" style={input} placeholder="Mã bệnh nhân hoặc mã hồ sơ" value={search} onChange={event => { setSearch(event.target.value); setOffset(0); }} /></label>
      <label>1. Chọn query<select aria-label="Bệnh nhân query" style={input} value={patientId} onChange={event => setPatientId(event.target.value)}>
        {patientId && !catalogue.queries.some(item => item.id === patientId) && <option value={patientId}>Bệnh nhân {patientId} · đang chọn</option>}
        {catalogue.queries.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
    </div>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 15, fontSize: 12 }}>
      <span>{catalogue.total.toLocaleString('vi-VN')} bệnh nhân khớp · Trang {Math.floor(offset / 50) + 1}</span>
      <button style={button} disabled={!offset} onClick={() => setOffset(value => value - 50)}>Trang query trước</button>
      <button style={button} disabled={offset + 50 >= catalogue.total} onClick={() => setOffset(value => value + 50)}>Trang query sau</button>
    </div>
    {patientId && <h2 style={{ fontSize: 16 }}>2. Chọn retrieval cho bệnh nhân {patientId}</h2>}
    <div role="group" aria-label="Lựa chọn retrieval" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(175px,1fr))', gap: 10, marginBottom: 15 }}>
      {methods.map(method => <button key={method.id} data-retrieval-method={method.id} disabled={!method.available} aria-pressed={methodId === method.id && method.available} onClick={() => setMethodId(method.id)} style={{ ...button, textAlign: 'left', background: methodId === method.id && method.available ? '#DDF3EF' : 'white', opacity: method.available ? 1 : .65, cursor: method.available ? 'pointer' : 'default' }}>
        <strong>{method.label}</strong><div style={{ fontSize: 12, marginTop: 5 }}>{method.available ? `${method.queries.length} lựa chọn query` : 'Không khả dụng'}</div>
        {!method.available && <div style={{ fontSize: 11, marginTop: 4 }}>{method.reason}</div>}
      </button>)}
    </div>
    {selectedMethod?.available && <div style={{ background: 'white', padding: 12, border: `1px solid ${C.border}`, borderRadius: 7, marginBottom: 15 }}>
      <strong>{shortModelNames[selectedMethod.id] || selectedMethod.label}</strong> · Đơn vị: {selectedMethod.unit}
      <label style={{ display: 'block', marginTop: 10 }}>Query dùng cho {selectedMethod.label}<select aria-label="Dữ liệu query" style={input} value={queryId} onChange={event => setQueryId(event.target.value)}>{selectedMethod.queries.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
    </div>}
    {error && <div role="alert" style={{ color: C.red, marginBottom: 15 }}>{error}</div>}
    {patientId && !options && !error && <p>Đang kiểm tra dữ liệu của query…</p>}
    {options && !methods.some(method => method.available) && <p>Query này chưa có lựa chọn retrieval khả dụng.</p>}
    {currentSession && <div style={{ display: 'flex', gap: 15, alignItems: 'start', flexWrap: 'wrap' }}>
      <aside aria-label="Top-20 theo modality" style={{ flex: '1 1 240px', maxWidth: 300, background: 'white', border: `1px solid ${C.border}`, borderRadius: 8, padding: 10 }}>
        <strong>Top-{currentSession.candidates.length} · {currentSession.method.metric === 'cosine_distance' ? 'Distance' : 'Cosine'}</strong>
        {currentSession.candidates.map(item => <button key={item.id} onClick={() => setSelectedId(item.id)} aria-pressed={item.id === selectedId} style={{ ...button, display: 'block', width: '100%', marginTop: 7, textAlign: 'left', background: item.id === selectedId ? '#DDF3EF' : 'white', overflowWrap: 'anywhere' }}>
          <strong>#{item.rank} · {item.score.toFixed(6)}</strong><div style={{ fontSize: 11 }}>{item.label}</div>
          {item.shared_tests != null && <div style={{ fontSize: 10 }}>{item.shared_tests} xét nghiệm chung · phủ {(item.query_coverage * 100).toFixed(1)}%</div>}
        </button>)}
      </aside>
      <div style={{ flex: '4 1 600px', minWidth: 0 }}>
        {currentCandidate ? <>
          <div style={{ marginBottom: 10, fontSize: 12 }}>Candidate #{currentCandidate.rank} · Score nguồn: <strong>{currentCandidate.source_score}</strong></div>
          {isFusion ? <FusionComparison key={`${queryId}:${selectedId}`} session={currentSession} candidate={currentCandidate} /> : <Comparison session={currentSession} candidate={currentCandidate} />}
          <section aria-label="Đánh giá theo modality" style={{ marginTop: 15, padding: 15, background: 'white', border: `1px solid ${C.border}`, borderRadius: 8 }}>
            <strong>Đánh giá mức phù hợp theo {currentSession.method.label.toLocaleLowerCase('vi')}</strong>
            {isFusion && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginTop: 10 }}>{currentSession.review_criteria.map(([key, label]) => <label key={key}>{label}<select aria-label={`Điểm fusion ${label}`} value={criteria[key] || ''} onChange={event => setCriteria(value => ({ ...value, [key]: event.target.value }))} style={input}><option value="">Chọn 1–5</option>{[1,2,3,4,5].map(value => <option key={value} value={value}>{value}</option>)}</select></label>)}</div>}
            <div style={{ display: 'flex', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
              <label>{isFusion ? 'Điểm chung' : 'Điểm'}<select aria-label="Điểm phù hợp theo modality" value={score} onChange={event => setScore(event.target.value)} style={button}><option value="">Chọn 1–5</option>{[1,2,3,4,5].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
              <input aria-label="Ghi chú theo modality" value={note} maxLength={5000} onChange={event => setNote(event.target.value)} placeholder="Ghi chú" style={{ ...input, flex: '1 1 240px' }} />
              <button style={button} disabled={!score || saving || (isFusion && currentSession.review_criteria.some(([key]) => !criteria[key]))} onClick={save}>{saving ? 'Đang lưu…' : 'Lưu đánh giá'}</button>
            </div>
            <div style={{ fontSize: 11, marginTop: 8, ...muted }}>1 = ít phù hợp, 5 = rất phù hợp.</div>
            {currentCandidate.verification && <div style={{ fontSize: 11, marginTop: 8 }}>Lần lưu gần nhất: {currentCandidate.verification.reviewer} · {new Date(currentCandidate.verification.at).toLocaleString('vi-VN')}</div>}
            {notice && <div role="status" style={{ color: C.teal, marginTop: 8 }}>{notice}</div>}
            {user.role === 'admin' && <div style={{ display: 'flex', gap: 8, marginTop: 10 }}><button style={button} onClick={() => download('csv')}>Xuất CSV query này</button><button style={button} onClick={() => download('json')}>Xuất JSON query này</button></div>}
          </section>
        </> : <p>Đang tải candidate…</p>}
      </div>
    </div>}
  </main>;
}
