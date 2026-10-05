import React, { useEffect, useMemo, useState } from "react";
import {
  Bot, CheckCircle2, ChevronRight, Download, FileText, FlaskConical,
  Filter, Home, Image, LayoutDashboard, LogOut, ScanLine, Search, ShieldCheck,
  UserPlus, Users, X,
} from "lucide-react";
import {
  createAccount, downloadComparisonExport, downloadLlmRetrievalExport,
  fetchComparison, fetchComparisonCandidate, fetchLlmRetrievalCall, fetchLlmRetrievalCalls,
  fetchComparisonQueries, fetchCurrentUser, fetchUsers, fetchPatientList, fetchPatientDetail, login, logout,
  submitComparisonVerification, submitLlmRetrievalReview,
} from "./api.js";
import { C, FONTS } from "./theme.js";
import { StatusBadge, tdStyle, thStyle } from "./components/ui.jsx";
import ScanViewport from "./components/ScanViewport.jsx";
import ModalityReview from "./components/ModalityReview.jsx";

const tabs = [
  ["ehr", "EHR", FileText], ["labs", "Lab result", FlaskConical],
  ["diagnoses", "Chẩn đoán", FileText], ["medicines", "Thuốc", FileText],
  ["procedures", "Dịch vụ/thủ thuật", FileText],
  ["XQ", "XQ", Image], ["CT", "CT", ScanLine], ["MRI", "MRI", ScanLine],
];

const reviewCriteria = [
  ["symptoms", "Triệu chứng"],
  ["diagnosis", "Chẩn đoán"],
  ["medications", "Thuốc"],
  ["ct", "Ảnh CT"],
  ["xq", "Ảnh XQ"],
  ["mri", "Ảnh MRI"],
  ["clinical_course", "Diễn biến lâm sàng"],
  ["severity", "Mức độ nghiêm trọng"],
  ["lab_results", "Kết quả xét nghiệm"],
];

export default function App() {
  const [user, setUser] = useState(null);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [activeTool, setActiveTool] = useState(null);
  const [showAccounts, setShowAccounts] = useState(false);

  useEffect(() => {
    fetchCurrentUser().then(setUser).catch(() => setUser(null)).finally(() => setCheckingAuth(false));
    const expire = () => {
      setUser(null);
      setActiveTool(null);
      setShowAccounts(false);
    };
    window.addEventListener("auth-expired", expire);
    return () => window.removeEventListener("auth-expired", expire);
  }, []);

  if (checkingAuth) return <Centered>Đang kiểm tra phiên đăng nhập…</Centered>;
  if (!user) return <LoginPage onAuthenticated={setUser} />;
  const signOut = async () => {
    try { await logout(); } finally {
      setUser(null);
      setActiveTool(null);
      setShowAccounts(false);
    }
  };
  if (activeTool === "patient-verification") {
    return <VerifyApp user={user} onLogout={signOut} onBackHome={() => setActiveTool(null)} />;
  }
  if (activeTool === "patient-browser") return <PatientBrowser onBackHome={() => setActiveTool(null)} />;
  if (activeTool === "modality-review") return <ModalityReview user={user} onBackHome={() => setActiveTool(null)} />;
  if (activeTool === "llm-retrieval-verification") {
    return <LlmRetrievalApp user={user} onLogout={signOut} onBackHome={() => setActiveTool(null)} />;
  }
  return <>
    <UtilityHome
      user={user}
      onLogout={signOut}
      onOpenVerification={() => setActiveTool("patient-verification")}
      onOpenLlmVerification={() => setActiveTool("llm-retrieval-verification")}
      onOpenPatients={() => setActiveTool("patient-browser")}
      onOpenModalities={() => setActiveTool("modality-review")}
      onManageAccounts={() => setShowAccounts(true)}
    />
    {showAccounts && <AccountManager onClose={() => setShowAccounts(false)} />}
  </>;
}

function UtilityHome({ user, onLogout, onOpenVerification, onOpenLlmVerification, onOpenPatients, onOpenModalities, onManageAccounts }) {
  const futureUtilities = [
    ["Báo cáo và thống kê", "Theo dõi tiến độ, phân bố điểm và tổng hợp kết quả đánh giá."],
  ];
  return <main style={utilityHomeStyle}>
    <style>{FONTS}</style>
    <header style={utilityHeaderStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <span style={utilityLogoStyle}><ShieldCheck size={23} /></span>
        <span><strong style={{ display: "block", fontSize: 15 }}>Cổng công cụ lâm sàng</strong><span style={{ color: C.inkMuted, fontSize: 11 }}>Chọn chức năng cần sử dụng</span></span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={homeAccountStyle}><strong>{user.username}</strong> · {user.role === "admin" ? "Quản trị viên" : "Người đánh giá"}</span>
        <button type="button" onClick={onLogout} style={homeLogoutStyle}><LogOut size={15} />Đăng xuất</button>
      </div>
    </header>
    <section style={utilityContentStyle}>
      <div style={{ maxWidth: 650 }}>
        <span style={homeEyebrowStyle}>Không gian làm việc</span>
        <h1 style={{ margin: "10px 0 8px", fontSize: "clamp(25px, 4vw, 38px)", lineHeight: 1.15 }}>Bạn muốn thực hiện công việc nào?</h1>
        <p style={{ margin: 0, color: C.inkMuted, lineHeight: 1.6, fontSize: 14 }}>Mỗi tiện ích hoạt động độc lập. Bạn có thể quay lại trang này bất cứ lúc nào mà không cần đăng nhập lại.</p>
      </div>
      <div style={utilityGridStyle}>
        <button type="button" onClick={onOpenModalities} style={primaryUtilityCardStyle}>
          <span style={primaryUtilityIconStyle}><Search size={25} /></span>
          <strong style={{ display: "block", marginTop: 22, color: C.ink, fontSize: 20 }}>Retrieval theo từng modality</strong>
          <span style={{ display: "block", marginTop: 8, color: C.inkMuted, fontSize: 13, lineHeight: 1.55 }}>Top-20 riêng cho sinh hoá, mô tả bệnh Qwen và ảnh CT, MRI, X-quang; đối chiếu và đánh giá từng nhánh.</span>
          <span style={openUtilityStyle}>Mở retrieval <ChevronRight size={16} /></span>
        </button>
        <button type="button" onClick={onOpenPatients} style={primaryUtilityCardStyle}>
          <span style={primaryUtilityIconStyle}><FileText size={25} /></span>
          <strong style={{ display: "block", marginTop: 22, color: C.ink, fontSize: 20 }}>Tra cứu hồ sơ bệnh nhân</strong>
          <span style={{ display: "block", marginTop: 8, color: C.inkMuted, fontSize: 13 }}>Xem tất cả bệnh án, thông tin EHR, xét nghiệm và ảnh CT, MRI, XQ của bệnh nhân.</span>
          <span style={openUtilityStyle}>Mở hồ sơ <ChevronRight size={16} /></span>
        </button>
        <button type="button" onClick={onOpenVerification} style={primaryUtilityCardStyle}>
          <span style={primaryUtilityIconStyle}><ShieldCheck size={25} /></span>
          <span style={{ display: "block", marginTop: 22, color: C.teal, fontSize: 10, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase" }}>Đang hoạt động</span>
          <strong style={{ display: "block", marginTop: 7, color: C.ink, fontSize: 20 }}>Xác minh bệnh nhân</strong>
          <span style={{ display: "block", marginTop: 8, color: C.inkMuted, fontSize: 13, lineHeight: 1.55 }}>Đối chiếu bệnh nhân query với Top-20 bệnh nhân tương tự và chấm điểm theo từng tiêu chí.</span>
          <span style={openUtilityStyle}>Mở tiện ích <ChevronRight size={16} /></span>
        </button>
        <button type="button" onClick={onOpenLlmVerification} style={llmUtilityCardStyle}>
          <span style={llmUtilityIconStyle}><Bot size={25} /></span>
          <span style={{ display: "block", marginTop: 22, color: "#7652A8", fontSize: 10, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase" }}>Đang hoạt động</span>
          <strong style={{ display: "block", marginTop: 7, color: C.ink, fontSize: 20 }}>Xác minh retrieval LLM</strong>
          <span style={{ display: "block", marginTop: 8, color: C.inkMuted, fontSize: 13, lineHeight: 1.55 }}>Kiểm tra ranking, giải thích điểm giống/khác và đánh giá ICD do mô hình ngôn ngữ sinh ra.</span>
          <span style={{ ...openUtilityStyle, color: "#7652A8" }}>Mở tiện ích <ChevronRight size={16} /></span>
        </button>
        {user.role === "admin" && <button type="button" onClick={onManageAccounts} style={adminUtilityCardStyle}>
          <span style={adminUtilityIconStyle}><Users size={25} /></span>
          <span style={{ display: "block", marginTop: 22, color: "#146B60", fontSize: 10, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase" }}>Chỉ quản trị viên</span>
          <strong style={{ display: "block", marginTop: 7, color: C.ink, fontSize: 20 }}>Quản lý tài khoản</strong>
          <span style={{ display: "block", marginTop: 8, color: C.inkMuted, fontSize: 13, lineHeight: 1.55 }}>Tạo tài khoản reviewer hoặc quản trị viên và xem danh sách người dùng.</span>
          <span style={{ ...openUtilityStyle, color: "#146B60" }}>Mở quản lý <ChevronRight size={16} /></span>
        </button>}
        {futureUtilities.map(([title, description], index) => <article key={title} aria-disabled="true" style={futureUtilityCardStyle}>
          <span style={futureUtilityIconStyle}>{index === 0 ? <FileText size={23} /> : <LayoutDashboard size={23} />}</span>
          <span style={{ display: "block", marginTop: 22, color: C.inkFaint, fontSize: 10, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase" }}>Sắp có</span>
          <strong style={{ display: "block", marginTop: 7, color: C.ink, fontSize: 18 }}>{title}</strong>
          <span style={{ display: "block", marginTop: 8, color: C.inkMuted, fontSize: 13, lineHeight: 1.55 }}>{description}</span>
        </article>)}
      </div>
    </section>
  </main>;
}

function VerifyApp({ user, onLogout, onBackHome }) {
  const [session, setSession] = useState(null);
  const [queries, setQueries] = useState([]);
  const [queryPatientId, setQueryPatientId] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [candidate, setCandidate] = useState(null);
  const [tab, setTab] = useState("ehr");
  const [note, setNote] = useState("");
  const [criteriaScores, setCriteriaScores] = useState({});
  const [overallScore, setOverallScore] = useState(null);
  const [candidateSearch, setCandidateSearch] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadingSession, setLoadingSession] = useState(true);
  const [showSimilarOnly, setShowSimilarOnly] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [exporting, setExporting] = useState("");

  async function loadSession(patientId) {
    const cleanId = String(patientId || "").trim();
    if (!cleanId) return;
    setLoadingSession(true);
    setError("");
    setCandidate(null);
    try {
      const data = await fetchComparison(cleanId);
      setSession(data);
      setQueryPatientId(data.query.id);
      setCandidateSearch("");
      setSelectedId(data.candidates[0]?.patient_id || null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoadingSession(false);
    }
  }

  useEffect(() => {
    fetchComparisonQueries().then((data) => {
      setQueries(data.queries || []);
      return loadSession(data.default_query_patient_id);
    }).catch((requestError) => {
      setError(requestError.message);
      setLoadingSession(false);
    });
  }, []);

  useEffect(() => {
    if (!selectedId || !queryPatientId) return undefined;
    const controller = new AbortController();
    setCandidate(null);
    fetchComparisonCandidate(queryPatientId, selectedId).then((data) => {
      if (!controller.signal.aborted) setCandidate(data);
    }).catch((requestError) => !controller.signal.aborted && setError(requestError.message));
    return () => controller.abort();
  }, [selectedId, queryPatientId]);

  useEffect(() => {
    setNote(candidate?.verification?.note || "");
    setCriteriaScores(candidate?.verification?.criteria_scores || {});
    setOverallScore(candidate?.verification?.overall_similarity ?? null);
  }, [candidate]);

  useEffect(() => {
    if (!showSidebar) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setShowSidebar(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showSidebar]);

  const selectedSummary = useMemo(
    () => session?.candidates.find((item) => item.patient_id === selectedId),
    [session, selectedId],
  );
  const filtered = useMemo(
    () => (session?.candidates || []).filter((item) => item.patient_id.includes(candidateSearch.trim())),
    [session, candidateSearch],
  );
  if (error && !session) return <Centered>Lỗi: {error}</Centered>;
  if (!session) return <Centered>Đang tải Top-20 và dữ liệu raw…</Centered>;

  const currentReview = candidate?.verification || selectedSummary?.verification;
  const overallSaved = currentReview?.overall_similarity;
  const legacyStatus = currentReview?.status;
  const similarityFilterActive = showSimilarOnly && (tab === "ehr" || tab === "labs");
  const reviewed = session.candidates.filter(
    (item) => Number.isInteger(item.verification?.overall_similarity),
  ).length;
  const readyToSave = candidate && reviewCriteria.every(([key]) => Number.isInteger(criteriaScores[key]))
    && Number.isInteger(overallScore);

  async function saveReview() {
    if (!readyToSave || saving) return;
    setSaving(true);
    setError("");
    try {
      const saved = await submitComparisonVerification(
        session.query.id,
        candidate.patient_id,
        { criteria_scores: criteriaScores, overall_similarity: overallScore, note },
      );
      const verification = {
        criteria_scores: saved.criteria_scores,
        overall_similarity: saved.overall_similarity,
        note: saved.note,
        reviewer: saved.reviewer,
        at: saved.at,
      };
      setCandidate((old) => ({ ...old, verification }));
      setSession((old) => ({
        ...old,
        candidates: old.candidates.map((item) => (
          item.patient_id === candidate.patient_id ? { ...item, verification } : item
        )),
      }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function exportResults(format) {
    setExporting(format);
    setError("");
    try {
      await downloadComparisonExport(format, session.query.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setExporting("");
    }
  }

  return <main style={{ minHeight: "100vh", display: "flex", background: C.bg, color: C.ink, fontFamily: "'Inter', sans-serif" }}>
    <style>{FONTS}</style>
    {showSidebar && <div role="presentation" onMouseDown={() => setShowSidebar(false)} style={sidebarBackdropStyle}>
    <aside aria-label="Bảng điều khiển" onMouseDown={(event) => event.stopPropagation()} style={sidebarDrawerStyle}>
      <div style={{ padding: "18px 16px 10px" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 700, fontSize: 14 }}>
          <ShieldCheck size={17} color="#8FE0D4" />Đối chiếu bệnh nhân
          <button type="button" onClick={() => setShowSidebar(false)} title="Đóng bảng điều khiển" aria-label="Đóng bảng điều khiển" style={{ ...darkIconButtonStyle, marginLeft: "auto" }}><X size={16} /></button>
        </div>
        <div style={{ color: "#8da0ac", fontSize: 11, marginTop: 7 }}>
          {queries.length.toLocaleString("vi-VN")} query · {reviewed}/{session.candidates.length} kết quả đã xử lý
        </div>
        <div style={accountSummaryStyle}>
          <span style={{ minWidth: 0 }}><strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>{user.username}</strong>{user.role === "admin" ? "Quản trị viên" : "Người đánh giá"}</span>
          <button type="button" onClick={onLogout} title="Đăng xuất" aria-label="Đăng xuất" style={darkIconButtonStyle}><LogOut size={15} /></button>
        </div>
      </div>
      <div style={{ padding: "0 14px 12px" }}>
        <label style={{ fontSize: 10, color: "#8da0ac", fontWeight: 700, textTransform: "uppercase" }}>
          Bệnh nhân query
          <select
            value={queryPatientId}
            onChange={(event) => {
              loadSession(event.target.value);
              setShowSidebar(false);
            }}
            disabled={loadingSession || !queries.length}
            style={querySelectStyle}
          >
            {queries.map((item) => <option key={item.patient_id} value={item.patient_id}>
              {item.patient_id} · {item.split || "—"} · Top {item.candidate_count}
            </option>)}
          </select>
        </label>
        <div style={{ marginTop: 5, color: "#8da0ac", fontSize: 10 }}>Chọn query để đổi sang Top-20 tương ứng.</div>
      </div>
      <div style={searchBox}>
        <Search size={14} color="#8da0ac" />
        <input value={candidateSearch} onChange={(event) => setCandidateSearch(event.target.value)} placeholder="Lọc trong Top-20" style={searchInput} />
      </div>
      <div style={{ padding: "4px 8px", overflowY: "auto", flex: 1 }}>
        {filtered.map((item) => <button key={item.patient_id} onClick={() => { setSelectedId(item.patient_id); setShowSidebar(false); }} style={sidebarItemStyle(selectedId === item.patient_id)}>
          <span style={{ color: "#8FE0D4", fontFamily: "monospace", fontSize: 12, width: 28 }}>#{item.rank}</span>
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block", fontWeight: 600, fontSize: 13 }}>{item.patient_id}</span>
            <span style={{ fontSize: 11, color: "#9aabb5" }}>{(item.similarity_score * 100).toFixed(2)}% tương tự</span>
            {!!item.shared_primary_icd_groups?.length && <span style={sidebarIcdStyle}>ICD {item.shared_primary_icd_groups.join(", ")}</span>}
          </span>
          {Number.isInteger(item.verification?.overall_similarity) && <span title={`Đã chấm ${item.verification.overall_similarity}/5`} style={{ width: 7, height: 7, borderRadius: "50%", background: C.teal }} />}
          <ChevronRight size={14} color="#81939e" />
        </button>)}
      </div>
    </aside>
    </div>}
    <section style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column" }}>
      <header style={{ padding: "16px 22px 0", background: C.surface, borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", fontSize: 13, color: C.inkMuted }}>
          <button type="button" onClick={onBackHome} aria-label="Quay lại trang chính" style={homeNavButtonStyle}><Home size={15} />Trang chính</button>
          <button type="button" onClick={() => setShowSidebar(true)} aria-label="Mở bảng điều khiển" style={dashboardButtonStyle}><LayoutDashboard size={15} />Bảng điều khiển</button>
          Query <strong style={{ color: C.ink }}>{session.query.id}</strong><ChevronRight size={14} />
          Kết quả #{selectedSummary?.rank || "—"} <strong style={{ color: C.ink }}>{selectedId || "—"}</strong>
          {selectedSummary && <span style={{ color: C.teal, fontWeight: 700 }}>{(selectedSummary.similarity_score * 100).toFixed(2)}%</span>}
          <StatusBadge score={overallSaved} legacyStatus={legacyStatus} />
        </div>
        <nav style={{ marginTop: 14, display: "flex", gap: 4, flexWrap: "wrap" }}>
          {tabs.map(([id, label, Icon]) => <button key={id} onClick={() => setTab(id)} style={tabStyle(tab === id)}><Icon size={15} />{label}</button>)}
          <button onClick={() => setShowSimilarOnly((value) => !value)} disabled={!candidate || !["ehr", "labs"].includes(tab)} aria-pressed={similarityFilterActive} style={similarOnlyButtonStyle(similarityFilterActive, !candidate || !["ehr", "labs"].includes(tab))}>
            <Filter size={14} />{similarityFilterActive ? "Đang chỉ phần giống nhau" : "Chỉ phần giống nhau"}
          </button>
        </nav>
      </header>
      <SimilarityEvidence evidence={candidate?.similarity_evidence} />
      {similarityFilterActive && <SimilarityFocus tab={tab} evidence={candidate?.similarity_evidence} />}
      {similarityFilterActive && candidate
        ? <AlignedComparison tab={tab} evidence={candidate.similarity_evidence} queryId={session.query.id} candidateId={candidate.patient.id} />
        : candidate
          ? <FullComparison key={`${session.query.id}-${candidate.patient.id}`} query={session.query} candidate={candidate} tab={tab} />
          : <Centered>Đang tải hồ sơ tương tự…</Centered>}
      <section aria-label="Phiếu chấm mức độ tương tự" style={reviewPanelStyle}>
        <div style={{ marginBottom: 12 }}>
          <strong style={{ fontSize: 14 }}>Đánh giá theo tiêu chí</strong>
          <div style={{ color: C.inkMuted, fontSize: 11, marginTop: 3 }}>1 = ít tương tự, 5 = rất tương tự. Điểm này do người đánh giá chọn, độc lập với cosine similarity của model.</div>
        </div>
        <div style={criteriaGridStyle}>
          {reviewCriteria.map(([key, label]) => <ScoreSelect
            key={key}
            label={label}
            value={criteriaScores[key]}
            disabled={!candidate || saving}
            onChange={(value) => setCriteriaScores((current) => ({ ...current, [key]: value }))}
          />)}
          <div style={overallScoreStyle}>
            <ScoreSelect label="Mức độ tương tự chung" value={overallScore} disabled={!candidate || saving} onChange={setOverallScore} />
          </div>
        </div>
      </section>
      <footer style={{ padding: "12px 22px", display: "flex", flexWrap: "wrap", gap: 9, alignItems: "center", background: C.surface, borderTop: `1px solid ${C.border}` }}>
        <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Ghi chú cho kết quả đối chiếu…" maxLength={5000} style={{ flex: "1 1 240px", minWidth: 170, padding: "9px 11px", borderRadius: 7, border: `1px solid ${C.border}` }} />
        <button type="button" onClick={saveReview} disabled={!readyToSave || saving} style={saveReviewButtonStyle}><CheckCircle2 size={15} />{saving ? "Đang lưu…" : "Lưu đánh giá"}</button>
        {!readyToSave && <span style={{ color: C.inkMuted, fontSize: 11 }}>Chấm đủ 9 tiêu chí và mức chung để lưu.</span>}
        {user.role === "admin" && <>
          <button type="button" onClick={() => exportResults("csv")} disabled={Boolean(exporting)} style={exportLinkStyle}><Download size={14} />{exporting === "csv" ? "Đang tải…" : "CSV"}</button>
          <button type="button" onClick={() => exportResults("json")} disabled={Boolean(exporting)} style={exportLinkStyle}><Download size={14} />{exporting === "json" ? "Đang tải…" : "JSON"}</button>
        </>}
      </footer>
      {error && <div style={{ color: C.red, padding: "0 22px 10px", background: C.surface, fontSize: 12 }}>{error}</div>}
    </section>
  </main>;
}

function PatientBrowser({ onBackHome }) {
  const [patients, setPatients] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [patient, setPatient] = useState(null);
  const [tab, setTab] = useState("ehr");
  const [error, setError] = useState("");
  useEffect(() => { fetchPatientList().then(rows => { setPatients(rows); setSelectedId(rows[0]?.id || ""); }).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!selectedId) return;
    let active = true; setPatient(null); setError("");
    fetchPatientDetail(selectedId).then(value => { if (active) setPatient(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [selectedId]);
  const visible = patients.filter(row => row.id.includes(search.trim()));
  useEffect(() => {
    if (visible.length && !visible.some(row => row.id === selectedId)) setSelectedId(visible[0].id);
  }, [search, patients, selectedId]);
  return <main style={{ fontFamily: "Inter, sans-serif", padding: 20, background: C.bg, minHeight: "100vh" }}>
    <style>{FONTS}</style>
    <button onClick={onBackHome} style={homeLogoutStyle}><Home size={16} />Trang chính</button>
    <h1>Hồ sơ bệnh nhân</h1>
    <div style={{ display: "flex", gap: 15, flexWrap: "wrap", alignItems: "center", marginBottom: 18 }}>
      <label>Tìm mã bệnh nhân <input aria-label="Tìm mã bệnh nhân" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <label>Bệnh nhân <select aria-label="Bệnh nhân" value={selectedId} onChange={e => setSelectedId(e.target.value)}>{visible.map(row => <option key={row.id} value={row.id}>{row.id} · {row.record_count} bệnh án · {row.modalities.join(" / ") || "Không có ảnh"}</option>)}</select></label>
      <span>{patients.length} bệnh nhân có dữ liệu</span>
    </div>
    <nav aria-label="Loại dữ liệu bệnh nhân" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 15 }}>{tabs.map(([key, label]) => <button key={key} onClick={() => setTab(key)} aria-pressed={tab === key} style={{ ...homeLogoutStyle, background: tab === key ? "#DDF3ED" : "white" }}>{label}</button>)}</nav>
    {error && <p role="alert">{error}</p>}
    {patient ? <PatientPanel key={patient.id} title="Hồ sơ đầy đủ" patient={patient} tab={tab} side="query" similarOnly={false} /> : !error && <p>Đang tải hồ sơ…</p>}
  </main>;
}

function ScoreSelect({ label, value, onChange, disabled }) {
  return <label style={scoreLabelStyle}>
    <span>{label}</span>
    <select
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
      disabled={disabled}
      style={scoreSelectStyle}
    >
      <option value="">Chưa chấm</option>
      {[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score}/5</option>)}
    </select>
  </label>;
}

const llmAccuracyOptions = [
  ["accurate", "Chính xác"],
  ["partial", "Đúng một phần"],
  ["inaccurate", "Không chính xác"],
  ["uncertain", "Cần xem lại"],
];

function LlmRetrievalApp({ user, onLogout, onBackHome }) {
  const [catalogue, setCatalogue] = useState(null);
  const [selectedRequestId, setSelectedRequestId] = useState("");
  const [call, setCall] = useState(null);
  const [selectedPatientId, setSelectedPatientId] = useState("");
  const [review, setReview] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchLlmRetrievalCalls().then((data) => {
      if (!active) return;
      setCatalogue(data);
      setSelectedRequestId(data.calls?.[0]?.request_id || "");
    }).catch((requestError) => active && setError(requestError.message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedRequestId) {
      setCall(null);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setError("");
    setCall(null);
    setSelectedPatientId("");
    fetchLlmRetrievalCall(selectedRequestId).then((data) => {
      if (!active) return;
      setCall(data);
      setSelectedPatientId(data.ranking?.[0]?.patient_id || "");
    }).catch((requestError) => active && setError(requestError.message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [selectedRequestId]);

  const candidate = useMemo(
    () => call?.ranking.find((item) => item.patient_id === selectedPatientId),
    [call, selectedPatientId],
  );

  useEffect(() => {
    setReview(candidate?.verification || {});
  }, [candidate]);

  const readyToSave = candidate
    && Number.isInteger(review.retrieval_relevance)
    && ["similarities_accuracy", "differences_accuracy", "icd_accuracy"]
      .every((key) => llmAccuracyOptions.some(([value]) => value === review[key]));

  async function saveReview() {
    if (!readyToSave || saving) return;
    setSaving(true);
    setError("");
    try {
      const saved = await submitLlmRetrievalReview(call.request_id, candidate.patient_id, review);
      setReview(saved);
      setCall((current) => ({
        ...current,
        ranking: current.ranking.map((item) => (
          item.patient_id === candidate.patient_id ? { ...item, verification: saved } : item
        )),
      }));
      setCatalogue((current) => ({
        ...current,
        calls: current.calls.map((item) => item.request_id === call.request_id
          ? {
            ...item,
            reviewed_count: call.ranking.filter((entry) => (
              entry.patient_id === candidate.patient_id || entry.verification
            )).length,
          }
          : item),
      }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function exportReviews(format) {
    setExporting(format);
    setError("");
    try { await downloadLlmRetrievalExport(format); }
    catch (requestError) { setError(requestError.message); }
    finally { setExporting(""); }
  }

  return <main style={llmPageStyle}>
    <style>{FONTS}</style>
    <header style={llmHeaderStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
        <button type="button" onClick={onBackHome} style={homeNavButtonStyle}><Home size={15} />Trang chính</button>
        <span style={llmHeaderIconStyle}><Bot size={19} /></span>
        <span><strong style={{ display: "block", fontSize: 14 }}>Xác minh retrieval LLM</strong><span style={{ color: C.inkMuted, fontSize: 10 }}>Đánh giá ranking và nội dung giải thích của mô hình</span></span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {user.role === "admin" && <>
          <button type="button" onClick={() => exportReviews("csv")} disabled={Boolean(exporting)} style={exportLinkStyle}><Download size={14} />{exporting === "csv" ? "Đang tải…" : "CSV"}</button>
          <button type="button" onClick={() => exportReviews("json")} disabled={Boolean(exporting)} style={exportLinkStyle}><Download size={14} />{exporting === "json" ? "Đang tải…" : "JSON"}</button>
        </>}
        <span style={homeAccountStyle}><strong>{user.username}</strong> · {user.role === "admin" ? "Quản trị viên" : "Người đánh giá"}</span>
        <button type="button" onClick={onLogout} style={homeLogoutStyle}><LogOut size={15} />Đăng xuất</button>
      </div>
    </header>

    <section style={llmToolbarStyle}>
      <label style={{ ...scoreLabelStyle, minWidth: 280, flex: "1 1 360px" }}>LLM call
        <select value={selectedRequestId} onChange={(event) => setSelectedRequestId(event.target.value)} style={scoreSelectStyle} disabled={!catalogue?.calls?.length}>
          {(catalogue?.calls || []).map((item) => <option key={item.request_id} value={item.request_id}>
            Query {item.query_patient_id} · {item.model_version || "model không rõ"} · {item.reviewed_count}/{item.candidate_count} đã review
          </option>)}
        </select>
      </label>
      {catalogue && <span style={{ color: C.inkMuted, fontSize: 11 }}>{catalogue.calls.length} call hợp lệ{catalogue.invalid_file_count ? ` · ${catalogue.invalid_file_count} file lỗi` : ""}</span>}
    </section>

    {!loading && catalogue && !catalogue.configured && <LlmEmptyState onBackHome={onBackHome} message="Server chưa cấu hình LLM_RETRIEVAL_ROOT." />}
    {!loading && catalogue?.configured && !catalogue.calls.length && <LlmEmptyState onBackHome={onBackHome} message="Không tìm thấy file calls/*.json hợp lệ trong nguồn đã cấu hình." />}
    {loading && !call && <Centered>Đang đọc kết quả retrieval của LLM…</Centered>}
    {call && <section style={llmWorkspaceStyle}>
      <aside style={llmRankingStyle}>
        <div style={{ padding: "14px 14px 8px", borderBottom: `1px solid ${C.border}` }}>
          <strong style={{ fontSize: 12 }}>Ranking Top-{call.ranking.length}</strong>
          <div style={{ color: C.inkMuted, fontSize: 10, marginTop: 3 }}>Query {call.query_icd_assessment.patient_id} · ICD {call.query_icd_assessment.icd || "—"}</div>
        </div>
        <div style={{ overflowY: "auto", padding: 8 }}>
          {call.ranking.map((item) => <button type="button" key={item.patient_id} onClick={() => setSelectedPatientId(item.patient_id)} style={llmRankItemStyle(item.patient_id === selectedPatientId)}>
            <span style={llmRankNumberStyle}>#{item.rank}</span>
            <span style={{ flex: 1, minWidth: 0 }}><strong style={{ display: "block" }}>{item.patient_id}</strong><span style={{ display: "block", marginTop: 2, color: C.inkMuted, fontSize: 10 }}>ICD {item.icd_assessment?.icd || "—"}</span></span>
            {item.verification && <span title={`Đã chấm ${item.verification.retrieval_relevance}/5`} style={reviewedDotStyle} />}
            <ChevronRight size={14} color={C.inkFaint} />
          </button>)}
        </div>
      </aside>

      {candidate && <div style={llmDetailStyle}>
        <section style={llmSummaryGridStyle}>
          <LlmIcdCard title={`ICD query · ${call.query_icd_assessment.patient_id}`} assessment={call.query_icd_assessment} tone="query" />
          <LlmIcdCard title={`ICD candidate · ${candidate.patient_id}`} assessment={candidate.icd_assessment} tone="candidate" />
        </section>

        <section style={llmContextGridStyle}>
          <ClinicalContext title={`Hồ sơ query · ${call.query_icd_assessment.patient_id}`} value={call.query_context} tone="query" />
          <ClinicalContext title={`Hồ sơ candidate · ${candidate.patient_id}`} value={candidate.patient_context} tone="candidate" />
        </section>

        <section style={llmExplanationGridStyle}>
          <LlmTextCard title="Điểm giống do LLM nhận xét" value={candidate.similarities} evidence={[...(candidate.query_evidence || []), ...(candidate.candidate_evidence || [])]} color="#146B60" background="#F0FAF7" />
          <LlmTextCard title="Điểm khác do LLM nhận xét" value={candidate.differences} color="#8A5B10" background="#FFF8ED" />
          <LlmTextCard title="Giới hạn do LLM nêu" value={candidate.limitations || "LLM không nêu giới hạn."} color="#65428A" background="#F7F2FC" />
        </section>

        <section style={llmReviewStyle}>
          <div><strong style={{ fontSize: 14 }}>Phiếu xác minh kết quả LLM</strong><div style={{ marginTop: 3, color: C.inkMuted, fontSize: 11 }}>Chấm mức phù hợp của candidate và kiểm tra riêng từng phần giải thích.</div></div>
          <div style={llmReviewGridStyle}>
            <ScoreSelect label="Mức phù hợp retrieval" value={review.retrieval_relevance} disabled={saving} onChange={(value) => setReview((current) => ({ ...current, retrieval_relevance: value }))} />
            <AccuracySelect label="Nhận xét điểm giống" value={review.similarities_accuracy} disabled={saving} onChange={(value) => setReview((current) => ({ ...current, similarities_accuracy: value }))} />
            <AccuracySelect label="Nhận xét điểm khác" value={review.differences_accuracy} disabled={saving} onChange={(value) => setReview((current) => ({ ...current, differences_accuracy: value }))} />
            <AccuracySelect label="Đánh giá ICD" value={review.icd_accuracy} disabled={saving} onChange={(value) => setReview((current) => ({ ...current, icd_accuracy: value }))} />
          </div>
          <div style={{ display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}>
            <input value={review.note || ""} onChange={(event) => setReview((current) => ({ ...current, note: event.target.value }))} maxLength={5000} placeholder="Ghi chú cho kết quả LLM…" style={{ ...loginInputStyle, flex: "1 1 300px" }} />
            <button type="button" onClick={saveReview} disabled={!readyToSave || saving} style={{ ...saveReviewButtonStyle, opacity: !readyToSave || saving ? 0.55 : 1 }}><CheckCircle2 size={15} />{saving ? "Đang lưu…" : "Lưu xác minh"}</button>
          </div>
          {!readyToSave && <span style={{ color: C.inkMuted, fontSize: 10 }}>Chọn đủ điểm phù hợp và ba đánh giá nội dung để lưu.</span>}
        </section>
      </div>}
    </section>}
    {error && <div role="alert" style={llmErrorStyle}>{error}</div>}
  </main>;
}

function AccuracySelect({ label, value, onChange, disabled }) {
  return <label style={scoreLabelStyle}>{label}
    <select value={value || ""} onChange={(event) => onChange(event.target.value)} disabled={disabled} style={scoreSelectStyle}>
      <option value="">Chưa đánh giá</option>
      {llmAccuracyOptions.map(([option, text]) => <option key={option} value={option}>{text}</option>)}
    </select>
  </label>;
}

function LlmIcdCard({ title, assessment, tone }) {
  const palette = tone === "query" ? QUERY_PANEL : CANDIDATE_PANEL;
  return <article style={{ padding: 14, borderRadius: 9, border: `1px solid ${palette.border}`, background: palette.background }}>
    <strong style={{ color: palette.accent, fontSize: 12 }}>{title}</strong>
    <div style={{ marginTop: 7, fontSize: 11 }}><b>{assessment?.status || "—"}</b> · Visit {assessment?.visit || "—"}</div>
    <div style={{ marginTop: 6, color: C.inkMuted, fontSize: 12, lineHeight: 1.5 }}>{assessment?.reason || "Không có nhận xét ICD."}</div>
    {!!assessment?.evidence?.length && <div style={{ marginTop: 7 }}>{assessment.evidence.map((item) => <span key={item} style={{ ...evidenceChipStyle, marginRight: 4 }}>{item}</span>)}</div>}
  </article>;
}

function ClinicalContext({ title, value, tone }) {
  const palette = tone === "query" ? QUERY_PANEL : CANDIDATE_PANEL;
  return <article style={{ minWidth: 0, borderRadius: 9, border: `1px solid ${palette.border}`, background: palette.background, overflow: "hidden" }}>
    <header style={{ padding: "10px 12px", background: palette.header, color: palette.accent, fontSize: 12, fontWeight: 800 }}>{title}</header>
    <div style={clinicalContextTextStyle}>{value || "Không tìm thấy context trong request_body.json."}</div>
  </article>;
}

function LlmTextCard({ title, value, evidence = [], color, background }) {
  return <article style={{ padding: 13, borderRadius: 9, border: `1px solid ${C.border}`, background }}>
    <strong style={{ color, fontSize: 11, textTransform: "uppercase" }}>{title}</strong>
    <div style={{ marginTop: 7, fontSize: 12, lineHeight: 1.55 }}>{value || "Không có nội dung."}</div>
    {!!evidence.length && <div style={{ marginTop: 8 }}>{[...new Set(evidence)].map((item) => <span key={item} style={{ ...evidenceChipStyle, marginRight: 4 }}>{item}</span>)}</div>}
  </article>;
}

function LlmEmptyState({ message, onBackHome }) {
  return <section style={llmEmptyStyle}><Bot size={34} color="#7652A8" /><strong>{message}</strong><span>Hãy mount thư mục run vào container và đặt biến môi trường trước khi sử dụng tiện ích này.</span><button type="button" onClick={onBackHome} style={homeNavButtonStyle}><Home size={15} />Về trang chính</button></section>;
}

function LoginPage({ onAuthenticated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      onAuthenticated(await login(username, password));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return <main style={loginPageStyle}>
    <style>{FONTS}</style>
    <form onSubmit={submit} style={loginCardStyle}>
      <div style={loginIconStyle}><ShieldCheck size={28} /></div>
      <h1 style={{ margin: "16px 0 6px", fontSize: 22 }}>Đăng nhập hệ thống xác minh</h1>
      <p style={{ margin: "0 0 22px", color: C.inkMuted, fontSize: 13 }}>Dữ liệu bệnh nhân chỉ hiển thị cho tài khoản đã được quản trị viên cấp.</p>
      <label style={loginLabelStyle}>Tên đăng nhập<input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required style={loginInputStyle} /></label>
      <label style={loginLabelStyle}>Mật khẩu<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required style={loginInputStyle} /></label>
      {error && <div role="alert" style={{ color: C.red, fontSize: 12 }}>{error}</div>}
      <button type="submit" disabled={submitting} style={loginButtonStyle}>{submitting ? "Đang đăng nhập…" : "Đăng nhập"}</button>
    </form>
  </main>;
}

function AccountManager({ onClose }) {
  const [users, setUsers] = useState([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reviewer");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchUsers().then(setUsers).catch((requestError) => setError(requestError.message));
  }, []);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const created = await createAccount({ username, password, role });
      setUsers((current) => [...current, created].sort((left, right) => left.username.localeCompare(right.username, "vi")));
      setUsername("");
      setPassword("");
      setRole("reviewer");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return <div style={modalBackdropStyle} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section role="dialog" aria-modal="true" aria-label="Quản lý tài khoản" style={accountModalStyle}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div><h2 style={{ margin: 0, fontSize: 18 }}>Quản lý tài khoản</h2><div style={{ color: C.inkMuted, fontSize: 12, marginTop: 4 }}>Chỉ quản trị viên truy cập được khu vực này.</div></div>
        <button type="button" onClick={onClose} aria-label="Đóng" style={closeButtonStyle}><X size={18} /></button>
      </header>
      <form onSubmit={submit} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 150px auto", gap: 9, margin: "20px 0" }}>
        <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Tên đăng nhập" minLength={3} required style={loginInputStyle} />
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Mật khẩu (ít nhất 12 ký tự)" minLength={12} required style={loginInputStyle} />
        <select value={role} onChange={(event) => setRole(event.target.value)} style={loginInputStyle}><option value="reviewer">Người đánh giá</option><option value="admin">Quản trị viên</option></select>
        <button type="submit" disabled={saving} style={createButtonStyle}><UserPlus size={15} />{saving ? "Đang tạo…" : "Tạo"}</button>
      </form>
      {error && <div role="alert" style={{ color: C.red, fontSize: 12, marginBottom: 10 }}>{error}</div>}
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 8, overflow: "hidden" }}>
        {users.map((item) => <div key={item.username} style={{ display: "grid", gridTemplateColumns: "1fr 150px 180px", gap: 10, padding: "10px 12px", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}><strong>{item.username}</strong><span>{item.role === "admin" ? "Quản trị viên" : "Người đánh giá"}</span><span style={{ color: C.inkFaint }}>{new Date(item.created_at).toLocaleString("vi-VN")}</span></div>)}
        {!users.length && <div style={{ padding: 16, color: C.inkFaint, fontSize: 13 }}>Chưa có tài khoản.</div>}
      </div>
    </section>
  </div>;
}

function SimilarityEvidence({ evidence }) {
  if (!evidence) return <div style={evidenceBarStyle}>Đang xác định các điểm trùng quan sát được…</div>;
  const groups = [
    ["ICD chính chung", evidence.shared_primary_icd_groups, "#DFF3EF", "#146B60"],
    ["Cụm EHR chung", evidence.ehr_phrases?.length ? evidence.ehr_phrases : evidence.ehr_keywords, "#E8EFF8", "#24577B"],
    ["Xét nghiệm chung", evidence.shared_labs, "#F3ECFA", "#65428A"],
    ["Bất thường chung", evidence.shared_abnormal_labs, "#FCE9E5", C.red],
    ["Modality chung", evidence.shared_modalities, "#FFF1D9", "#8A5B10"],
  ].filter(([, values]) => values?.length);
  return <section style={evidenceBarStyle} title={evidence.disclaimer}>
    <strong style={{ whiteSpace: "nowrap", fontSize: 11 }}>Điểm giống quan sát được</strong>
    {groups.length
      ? groups.map(([label, values, background, color]) => <div key={label} style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
        <span style={{ color: C.inkFaint, fontSize: 10 }}>{label}:</span>
        {values.slice(0, 8).map((value) => <span key={value} style={{ ...evidenceChipStyle, background, color }}>{value}</span>)}
        {values.length > 8 && <span style={{ color: C.inkFaint, fontSize: 10 }}>+{values.length - 8}</span>}
      </div>)
      : <span style={{ color: C.inkFaint, fontSize: 11 }}>Chưa tìm thấy điểm trùng trực tiếp trong dữ liệu hiển thị.</span>}
  </section>;
}

function SimilarityFocus({ tab, evidence }) {
  if (!evidence) return null;
  if (tab === "ehr") {
    const rows = evidence.ehr_matches || [];
    return <section style={focusPanelStyle}>
      <strong>Phần EHR trùng nhau</strong>
      <span>{rows.length ? "Mỗi hàng bên dưới là một cặp trường tương ứng, đặt thẳng hàng để đối chiếu." : "Không tìm thấy cặp nội dung EHR lâm sàng trùng đủ rõ để đánh dấu."}</span>
    </section>;
  }
  const rows = evidence.shared_lab_results || [];
  return <section style={focusPanelStyle}><strong>Xét nghiệm/cận lâm sàng chung</strong><span>{rows.length ? "Mỗi chỉ số cùng tên được ghép một hàng với các kết quả của hai bên." : "Không có xét nghiệm trùng tên giữa hai hồ sơ."}</span></section>;
}

function AlignedComparison({ tab, evidence, queryId, candidateId }) {
  if (tab === "ehr") {
    const rows = evidence.ehr_matches || [];
    return <section style={alignedSectionStyle}>
      {rows.length ? <table style={alignedTableStyle}>
      <thead><tr><th style={{ ...thStyle, width: 190 }}>Trường EHR</th><th style={{ ...thStyle, ...alignedQueryHeaderStyle }}>Query · {queryId}</th><th style={{ ...thStyle, ...alignedCandidateHeaderStyle }}>Bệnh nhân tương tự · {candidateId}</th></tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row.query_title}-${index}`} style={{ borderTop: `1px solid ${C.border}`, verticalAlign: "top" }}>
          <td style={{ ...tdStyle, fontWeight: 700 }}><div>{row.query_title}</div><div style={{ marginTop: 5 }}>{[...(row.phrases || []), ...(row.terms || [])].slice(0, 4).map((value) => <span key={value} style={{ ...evidenceChipStyle, margin: "0 3px 3px 0", background: "#FFF0A8", color: C.ink }}>{value}</span>)}</div></td>
          <td style={{ ...tdStyle, ...alignedQueryCellStyle, lineHeight: 1.55 }}><HighlightedText value={row.query_value} terms={[...(row.phrases || []), ...(row.terms || [])]} /></td>
          <td style={{ ...tdStyle, ...alignedCandidateCellStyle, lineHeight: 1.55 }}><HighlightedText value={row.candidate_value} terms={[...(row.phrases || []), ...(row.terms || [])]} /></td>
        </tr>)}</tbody>
      </table> : <Empty label="Không có nội dung EHR trùng để xếp hàng đối chiếu" />}
    </section>;
  }

  const rows = evidence.shared_lab_results || [];
  return <section style={alignedSectionStyle}>
    {rows.length ? <table style={alignedTableStyle}>
      <thead><tr><th style={{ ...thStyle, width: 240 }}>Chỉ số/cận lâm sàng</th><th style={{ ...thStyle, ...alignedQueryHeaderStyle }}>Query · {queryId}</th><th style={{ ...thStyle, ...alignedCandidateHeaderStyle }}>Bệnh nhân tương tự · {candidateId}</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.name} style={{ borderTop: `1px solid ${C.border}`, verticalAlign: "top" }}><td style={{ ...tdStyle, fontWeight: 700 }}>{row.name}</td><td style={{ ...tdStyle, ...alignedQueryCellStyle }}>{formatLabResults(row.query_results)}</td><td style={{ ...tdStyle, ...alignedCandidateCellStyle }}>{formatLabResults(row.candidate_results)}</td></tr>)}</tbody>
    </table> : <Empty label="Không có chỉ số/cận lâm sàng trùng tên để xếp hàng đối chiếu" />}
  </section>;
}

function formatLabResults(results) {
  return (results || []).map((result) => <div key={`${result.date}-${result.value}`} style={{ color: result.flagged ? C.red : C.ink }}><span style={{ color: C.inkFaint }}>{result.date}: </span>{result.value} {result.unit}</div>);
}

// Pair by field/name, never by the position of independently rendered cards.
// Keep every occurrence on its own side; an absent value stays visibly absent.
function comparisonGroups(left, right, keyOf, labelOf = keyOf) {
  const groups = new Map();
  [left, right].forEach((items, side) => (items || []).forEach((item) => {
    const key = normalizeText(keyOf(item));
    if (!groups.has(key)) groups.set(key, { key, label: labelOf(item) || "Không rõ tên", values: [[], []] });
    groups.get(key).values[side].push(item);
  }));
  return [...groups.values()];
}

function ComparisonRow({ label, children, rowKey }) {
  return <tr data-comparison-row={rowKey} style={{ borderTop: `1px solid ${C.border}`, verticalAlign: "top" }}>
    <th scope="row" style={{ ...tdStyle, textAlign: "left", fontWeight: 700, background: "white" }}>{label}</th>
    {children.map((content, side) => <td key={side} data-comparison-side={side === 0 ? "query" : "candidate"} style={{ ...tdStyle, ...(side === 0 ? alignedQueryCellStyle : alignedCandidateCellStyle), whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.6 }}>{content}</td>)}
  </tr>;
}

function FullComparison({ query, candidate, tab }) {
  const patients = [query, candidate.patient];
  const [recordIds, setRecordIds] = useState(() => patients.map(patient => patient.records[0]?.id || ""));
  const records = patients.map((patient, side) => patient.records.find(record => record.id === recordIds[side]) || patient.records[0]);
  const evidence = candidate.similarity_evidence;
  const terms = [...(evidence?.ehr_phrases || []), ...(evidence?.ehr_keywords || [])];
  const missing = <span style={{ color: C.inkFaint }}>Không có dữ liệu</span>;
  const row = (label, values, key = label) => <ComparisonRow key={key} label={label} rowKey={key}>{values}</ComparisonRow>;
  const age = (patient, record) => {
    const value = record?.demographics?.age_at_visit ?? patient.age;
    return value == null ? missing : `${value} tuổi${record?.demographics?.birth_year ? ` (theo năm sinh ${record.demographics.birth_year})` : ""}`;
  };
  return <section aria-label="Đối chiếu thông tin theo từng trường" style={alignedSectionStyle}>
    <table style={{ ...alignedTableStyle, tableLayout: "fixed" }}>
      <colgroup><col style={{ width: "20%" }} /><col style={{ width: "40%" }} /><col style={{ width: "40%" }} /></colgroup>
      <thead><tr><th style={thStyle}>Trường thông tin</th><th style={{ ...thStyle, ...alignedQueryHeaderStyle }}>Bệnh nhân query · {query.id}</th><th style={{ ...thStyle, ...alignedCandidateHeaderStyle }}>Bệnh nhân tương tự #{candidate.rank} · {candidate.patient.id} · {(candidate.similarity_score * 100).toFixed(2)}%</th></tr></thead>
      <tbody>
        {row("Bệnh án", patients.map((patient, side) => <select aria-label={`Bệnh án ${side === 0 ? "query" : "candidate"}`} value={records[side]?.id || ""} onChange={event => setRecordIds(ids => ids.map((id, index) => index === side ? event.target.value : id))} style={selectStyle}>{patient.records.map(record => <option key={record.id} value={record.id}>{record.label} · {record.date}</option>)}</select>))}
        {row("Tuổi", patients.map((patient, side) => age(patient, records[side])))}
        {row("Giới tính", patients.map((patient, side) => records[side]?.demographics?.gender_code ? `Mã ${records[side].demographics.gender_code}` : patient.gender || missing))}
      </tbody>
      {tab === "ehr" && <tbody>
        {comparisonGroups(records[0]?.ehr?.details, records[1]?.ehr?.details, item => item[0]).map(group => row(group.label, group.values.map(items => items.length ? items.map(([title, value], index) => <div key={index} style={{ marginBottom: index + 1 < items.length ? 12 : 0 }}><HighlightedText value={value} terms={terms} /></div>) : missing), `ehr-${group.key}`))}
        {!records.some(record => record?.ehr?.details?.length) && row("EHR", [missing, missing])}
      </tbody>}
      {tab === "labs" && <ComparisonLabs key={recordIds.join(":")} records={records} sharedLabs={evidence?.shared_labs || []} />}
      {["diagnoses", "medicines", "procedures"].includes(tab) && <ComparisonClinical key={`${recordIds.join(":")}-${tab}`} records={records} tab={tab} />}
      {["XQ", "CT", "MRI"].includes(tab) && <tbody>{row(tab, patients.map((patient, side) => <Imaging key={`${records[side]?.id}-${tab}`} modality={tab} patient={patient} studies={records[side]?.studies?.[tab] || []} shared={evidence?.shared_modalities?.includes(tab)} />))}</tbody>}
    </table>
  </section>;
}

function ComparisonLabs({ records, sharedLabs }) {
  const labs = records.map(record => record?.labs || []);
  const dates = labs.map(items => [...new Set(items.map(lab => lab.date || "Không rõ ngày"))].sort((a, b) => b.localeCompare(a)));
  const [selectedDates, setSelectedDates] = useState(() => dates.map(items => items[0] || ""));
  const shared = new Set(sharedLabs.map(normalizeText));
  const visible = labs.map((items, side) => items.filter(lab => (lab.date || "Không rõ ngày") === selectedDates[side]));
  const groups = comparisonGroups(visible[0], visible[1], lab => lab.name);
  return <tbody>
    <ComparisonRow label="Ngày trả kết quả" rowKey="lab-dates">{dates.map((items, side) => items.length ? <select aria-label={`Ngày trả kết quả ${side === 0 ? "query" : "candidate"}`} style={selectStyle} value={selectedDates[side]} onChange={event => setSelectedDates(values => values.map((value, index) => index === side ? event.target.value : value))}>{items.map(date => <option key={date} value={date}>{date}</option>)}</select> : "Không có dữ liệu")}</ComparisonRow>
    {groups.map(group => <ComparisonRow key={group.key} label={<>{group.label}{shared.has(group.key) && <span style={{ ...evidenceChipStyle, marginLeft: 5 }}>Chung</span>}</>} rowKey={`lab-${group.key}`}>
      {group.values.map(items => items.length ? items.map((lab, index) => <div key={index} style={{ marginBottom: 12 }}>
        <strong style={{ color: lab.flagged ? C.red : C.ink }}>{lab.value} {lab.unit}</strong>
        <div>Tham chiếu: {lab.range || "—"}</div><div>Mẫu: {lab.sample || "—"}</div><div>Khoa xét nghiệm: {lab.department || "—"}</div>
        <details><summary>Chi tiết</summary>{Object.entries(lab.source_fields || {}).map(([key, value]) => <div key={key}>{key}: {typeof value === "object" ? JSON.stringify(value) : String(value)}</div>)}</details>
      </div>) : <span style={{ color: C.inkFaint }}>Không có dữ liệu trong ngày đã chọn</span>)}
    </ComparisonRow>)}
    {!groups.length && <ComparisonRow label="Xét nghiệm" rowKey="labs-empty">{["Không có dữ liệu", "Không có dữ liệu"]}</ComparisonRow>}
  </tbody>;
}

function ComparisonClinical({ records, tab }) {
  const [page, setPage] = useState(0);
  const kinds = records.map(record => tab === "medicines" && record?.source_medicines ? "source_medicines" : tab);
  const items = records.map((record, side) => record?.[kinds[side]] || []);
  const nameOf = item => tab === "diagnoses" ? `${item.diagnosis_code || ""} · ${item.diagnosis_text || ""}` : tab === "medicines" ? item.TenDuoc || item.drug_name || "" : item.procedure_name || "";
  const groups = comparisonGroups(items[0], items[1], nameOf);
  const pages = Math.max(1, Math.ceil(groups.length / 50));
  return <tbody>
    <tr><td colSpan={3} style={tdStyle}>Đối chiếu theo tên; mỗi bên giữ thời điểm và chi tiết riêng. {groups.length} nhóm · Trang {page + 1}/{pages} <button disabled={!page} onClick={() => setPage(value => value - 1)}>Trước</button> <button disabled={page + 1 >= pages} onClick={() => setPage(value => value + 1)}>Tiếp</button></td></tr>
    {groups.slice(page * 50, (page + 1) * 50).map(group => <ComparisonRow key={group.key} label={group.label} rowKey={`${tab}-${group.key}`}>
      {group.values.map((rows, side) => !records[side]?.structured_available ? "Thông tin này chưa được đồng bộ" : rows.length ? <ClinicalTable key={`${group.key}-${kinds[side]}`} kind={kinds[side]} rows={rows} /> : <span style={{ color: C.inkFaint }}>Không có dữ liệu</span>)}
    </ComparisonRow>)}
    {!groups.length && <ComparisonRow label="Bản ghi" rowKey="clinical-empty">{records.map(record => record?.structured_available ? "Không có bản ghi trong bệnh án gốc" : "Thông tin này chưa được đồng bộ")}</ComparisonRow>}
  </tbody>;
}

function PatientPanel({ title, patient, tab, evidence, similarOnly, side }) {
  const [recordId, setRecordId] = useState(patient.records[0]?.id || "");
  useEffect(() => setRecordId(patient.records[0]?.id || ""), [patient.id]);
  const record = patient.records.find((item) => item.id === recordId) || patient.records[0];
  const isQuery = side === "query";
  return <article data-patient-side={side} style={patientPanelStyle(isQuery)}>
    <div style={patientPanelHeaderStyle(isQuery)}>
      <span style={patientPanelRoleStyle(isQuery)}>{isQuery ? "Hồ sơ query" : "Hồ sơ đối chiếu"}</span>
      <h2 style={{ fontSize: 14, margin: "6px 0 0", color: isQuery ? QUERY_PANEL.accent : CANDIDATE_PANEL.accent }}>{title}</h2>
      <div style={{ color: C.inkMuted, fontSize: 12, marginTop: 4 }}>{patient.id} · {record.demographics?.age_at_visit ?? patient.age} tuổi{record.demographics?.birth_year ? ` (theo năm sinh ${record.demographics.birth_year})` : ""} · {record.demographics?.gender_code ? `Giới tính: mã ${record.demographics.gender_code}` : patient.gender}</div>
    </div>
    <label style={labelStyle}>Bệnh án
      <select aria-label="Bệnh án" value={recordId} onChange={(event) => setRecordId(event.target.value)} style={selectStyle}>
        {patient.records.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.date}</option>)}
      </select>
    </label>
    {tab === "ehr" && <Ehr ehr={record.ehr} highlightTerms={[...(evidence?.ehr_phrases || []), ...(evidence?.ehr_keywords || [])]} matchedTitles={(evidence?.ehr_matches || []).map((match) => side === "query" ? match.query_title : match.candidate_title)} similarOnly={similarOnly} />}
    {tab === "labs" && <Labs labs={record.labs} sharedLabs={evidence?.shared_labs || []} similarOnly={similarOnly} />}
    {["diagnoses", "medicines", "procedures"].includes(tab) && (record.structured_available ? <ClinicalTable key={`${record.id}-${tab}`} kind={tab === "medicines" && record.source_medicines ? "source_medicines" : tab} rows={tab === "medicines" && record.source_medicines ? record.source_medicines : record[tab] || []} /> : <Empty label="Thông tin này chưa được đồng bộ" />)}
    {["XQ", "CT", "MRI"].includes(tab) && <Imaging modality={tab} patient={patient} studies={record.studies[tab]} shared={evidence?.shared_modalities?.includes(tab)} />}
  </article>;
}

function Ehr({ ehr, highlightTerms, matchedTitles, similarOnly }) {
  const matched = new Set(matchedTitles.map(normalizeText));
  const details = similarOnly ? ehr.details.filter(([title]) => !isEhrMetadata(title) && matched.has(normalizeText(title))) : ehr.details;
  return <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
    {details.length
      ? details.map(([title, value]) => <Card key={title} title={title}><HighlightedText value={value} terms={highlightTerms} /></Card>)
      : <Empty label={similarOnly ? "Không tìm thấy nội dung EHR lâm sàng chung" : "Không có dữ liệu EHR"} />}
  </div>;
}

const clinicalColumns = {
  source_medicines: [["NgayKham", "Ngày kê"], ["TenDuoc", "Thuốc"], ["HamLuong", "Hàm lượng"], ["TenHoatChat", "Hoạt chất"], ["DuongDung", "Đường dùng"], ["strSLSang", "Sáng"], ["strSLTrua", "Trưa"], ["strSLChieu", "Chiều"], ["strSLToi", "Tối"], ["DonViTinh", "Đơn vị"], ["SoNgay", "Số ngày"], ["SoLuongTong", "Tổng lượng"], ["LoiDan", "Lời dặn"], ["GhiChu", "Ghi chú"], ["status", "Trạng thái"], ["LyDoTraThuoc", "Lý do trả"]],
  diagnoses: [["event_time", "Thời điểm"], ["diagnosis_code", "Mã"], ["diagnosis_text", "Chẩn đoán"], ["diagnosis_type", "Loại"]],
  medicines: [["prescribed_time", "Ngày kê"], ["drug_name", "Thuốc"], ["active_ingredient", "Hoạt chất"], ["route", "Đường dùng"], ["dose_morning", "Sáng"], ["dose_noon", "Trưa"], ["dose_afternoon", "Chiều"], ["dose_evening", "Tối"], ["unit", "Đơn vị"], ["days", "Số ngày"], ["total_quantity", "Tổng lượng"], ["instructions", "Hướng dẫn"], ["status", "Trạng thái"], ["return_reason", "Lý do trả"]],
  procedures: [["ordered_time", "Ngày chỉ định"], ["procedure_name", "Dịch vụ/thủ thuật"], ["status", "Trạng thái"], ["start_time", "Bắt đầu"], ["end_time", "Kết thúc"], ["result", "Kết quả"], ["procedure_report", "Báo cáo"]],
};
function ClinicalTable({ kind, rows }) {
  const [page, setPage] = useState(0);
  const size = 50, pages = Math.max(1, Math.ceil(rows.length / size));
  if (!rows.length) return <Empty label="Không có bản ghi trong bệnh án gốc" />;
  const columns = clinicalColumns[kind];
  const valueText = value => value == null || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
  const statusText = value => ({ prescribed: "Đã kê", returned: "Trả thuốc", ordered: "Đã chỉ định", performed: "Có bản ghi thực hiện" })[value] || valueText(value);
  return <section style={{ marginTop: 18 }}>
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
      <span>{rows.length} bản ghi · Trang {page + 1}/{pages}</span>
      <button disabled={!page} onClick={() => setPage(p => p - 1)}>Trước</button>
      <button disabled={page + 1 >= pages} onClick={() => setPage(p => p + 1)}>Tiếp</button>
    </div>
    <div style={{ overflowX: "auto", background: "white", border: `1px solid ${C.border}`, borderRadius: 8 }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
        <thead><tr>{columns.map(([key, label]) => <th key={key} style={{ ...thStyle, whiteSpace: "nowrap" }}>{label}</th>)}<th style={thStyle}>Chi tiết</th></tr></thead>
        <tbody>{rows.slice(page * size, (page + 1) * size).map((row, index) => <tr key={index} style={{ verticalAlign: "top", borderTop: `1px solid ${C.border}` }}>
          {columns.map(([key]) => <td key={key} style={{ ...tdStyle, minWidth: key.includes("name") || key.includes("text") || key.includes("report") ? 180 : 75, whiteSpace: "pre-wrap" }}>{key === "status" ? statusText(row[key]) : valueText(row[key])}</td>)}
          <td style={tdStyle}><details><summary>Xem đầy đủ</summary>{Object.entries(row).map(([key, value]) => <div key={key} style={{ minWidth: 220, overflowWrap: "anywhere", marginBottom: 5 }}><strong>{key}: </strong>{valueText(value)}</div>)}</details></td>
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}

function Labs({ labs, sharedLabs, similarOnly }) {
  const dates = [...new Set(labs.map((lab) => lab.date || "Không rõ ngày"))].sort((a, b) => b.localeCompare(a));
  const [selectedDate, setSelectedDate] = useState(dates[0] || "");
  useEffect(() => setSelectedDate(dates[0] || ""), [labs]);
  if (!labs.length) return <Empty label="Không có kết quả xét nghiệm" />;
  const shared = new Set(sharedLabs.map(normalizeText));
  const dailyLabs = labs.filter((lab) => (lab.date || "Không rõ ngày") === selectedDate);
  const visibleLabs = similarOnly ? labs.filter((lab) => shared.has(normalizeText(lab.name))) : dailyLabs;
  return <div style={{ marginTop: 18 }}>
    {!similarOnly && <label style={labelStyle}>Ngày trả kết quả
      <select aria-label="Ngày trả kết quả" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} style={selectStyle}>
        {dates.map((date) => <option key={date} value={date}>{date}</option>)}
      </select>
    </label>}
    <div style={{ marginTop: 12, overflowX: "auto", border: `1px solid ${C.border}`, borderRadius: 8, background: "white" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead><tr style={{ borderBottom: `1px solid ${C.border}` }}><th style={thStyle}>Chỉ số</th>{similarOnly && <th style={thStyle}>Ngày KQ</th>}<th style={thStyle}>Kết quả</th><th style={thStyle}>Tham chiếu</th><th style={thStyle}>Mẫu</th><th style={thStyle}>Khoa xét nghiệm</th></tr></thead>
        <tbody>{visibleLabs.map((lab, index) => {
          const isShared = shared.has(normalizeText(lab.name));
          return <tr key={`${lab.name}-${lab.date}-${index}`} style={{ borderBottom: `1px solid ${C.border}`, background: isShared ? "#F4FBF9" : "transparent" }}>
            <td style={{ ...tdStyle, fontWeight: isShared ? 700 : 400 }}>{lab.name}<details><summary>Chi tiết</summary>{Object.entries(lab.source_fields || {}).map(([key, value]) => <div key={key} style={{ overflowWrap: "anywhere" }}>{key}: {typeof value === "object" ? JSON.stringify(value) : String(value)}</div>)}</details>{isShared && <span style={{ ...evidenceChipStyle, marginLeft: 5 }}>Chung</span>}</td>
            {similarOnly && <td style={tdStyle}>{lab.date}</td>}
            <td style={{ ...tdStyle, color: lab.flagged ? C.red : C.ink, fontWeight: 600 }}>{lab.value} {lab.unit}</td>
            <td style={tdStyle}>{lab.range}</td><td style={tdStyle} title={lab.diagnosis}>{lab.sample}</td><td style={tdStyle} title={lab.diagnosis}>{lab.department || "—"}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <div style={{ marginTop: 7, fontSize: 11, color: C.inkFaint }}>{visibleLabs.length} chỉ số{similarOnly ? " chung ở mọi ngày" : " trong ngày"} · hàng xanh là xét nghiệm xuất hiện ở cả hai bệnh nhân</div>
  </div>;
}

function Imaging({ modality, patient, studies, shared }) {
  const [studyId, setStudyId] = useState("");
  const [seriesId, setSeriesId] = useState("");
  useEffect(() => { setStudyId(studies[0]?.id || ""); setSeriesId(""); }, [modality, studies]);
  const study = studies.find((item) => item.id === studyId) || studies[0];
  useEffect(() => setSeriesId(study?.series[0]?.id || ""), [study?.id]);
  if (!study) return <Empty label={`Không có dữ liệu ${modality}`} />;
  const currentSeries = study.series.find((item) => item.id === seriesId) || study.series[0];
  const previews = [currentSeries];
  return <div style={{ marginTop: 18 }}>
    {shared && <div style={{ ...evidenceChipStyle, display: "inline-block", marginBottom: 10 }}>Cả hai bệnh nhân đều có {modality}</div>}
    <label style={labelStyle}>{modality} study
      <select aria-label={`${modality} study`} value={study.id} onChange={(event) => setStudyId(event.target.value)} style={selectStyle}>
        {studies.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.date}</option>)}
      </select>
    </label>
    <label style={{ ...labelStyle, marginTop: 12 }}>Series
      <select aria-label={`${modality} series`} value={currentSeries.id} onChange={(event) => setSeriesId(event.target.value)} style={selectStyle}>
        {study.series.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
    </label>
    <div style={{ fontSize: 12, color: C.inkMuted, margin: "14px 0 8px" }}>{currentSeries.label} · {currentSeries.sliceCount} lát · {currentSeries.shape.join(" × ")}</div>
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
      {previews.map((series, index) => series
        ? <ScanViewport key={series.sliceUrl} patient={patient} modality={modality} series={series} />
        : <Empty key={`empty-${index}`} label="Không có ảnh XQ thứ hai" />)}
    </div>
    <details style={{ marginTop: 12, fontSize: 12 }}><summary>Thông tin series</summary>{Object.entries(currentSeries.metadata || {}).map(([key, value]) => <div key={key} style={{ overflowWrap: "anywhere", marginTop: 5 }}><strong>{key}: </strong>{typeof value === "object" ? JSON.stringify(value) : String(value)}</div>)}</details>
  </div>;
}

function HighlightedText({ value, terms }) {
  const text = String(value ?? "");
  const usefulTerms = [...new Set(terms.filter(Boolean))].sort((left, right) => right.length - left.length);
  if (!usefulTerms.length) return text;
  const pattern = new RegExp(`(${usefulTerms.map(escapeRegExp).join("|")})`, "giu");
  return text.split(pattern).map((part, index) => (
    usefulTerms.some((term) => normalizeText(term) === normalizeText(part))
      ? <mark key={`${part}-${index}`} style={{ background: "#FFF0A8", color: "inherit", padding: "0 1px", borderRadius: 2 }}>{part}</mark>
      : part
  ));
}

function containsSimilarTerm(value, terms) {
  const normalizedValue = normalizeText(value);
  return terms.some((term) => normalizeText(term).length >= 4 && normalizedValue.includes(normalizeText(term)));
}

function isEhrMetadata(title) {
  return new Set(["số bệnh án", "số vào viện", "mã bệnh án", "ngày vào viện", "ngày ra viện", "khoa điều trị", "kết quả điều trị"]).has(normalizeText(title));
}

function normalizeText(value) { return String(value || "").normalize("NFC").toLocaleLowerCase("vi").trim(); }
function escapeRegExp(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function Card({ title, children }) { return <div style={{ border: `1px solid ${C.border}`, background: "white", borderRadius: 8, padding: "11px 12px", fontSize: 13, lineHeight: 1.5 }}><div style={{ fontSize: 10, fontWeight: 700, color: C.inkFaint, textTransform: "uppercase", marginBottom: 4 }}>{title}</div>{children}</div>; }
function Empty({ label }) { return <div style={{ minHeight: 120, display: "grid", placeItems: "center", color: C.inkFaint, fontSize: 13, border: `1px dashed ${C.border}`, borderRadius: 8, marginTop: 18 }}>{label}</div>; }
function Centered({ children }) { return <div style={{ minHeight: "100%", display: "grid", placeItems: "center", fontFamily: "Inter, sans-serif", color: C.inkMuted, padding: 18 }}>{children}</div>; }
const labelStyle = { display: "block", fontSize: 11, color: C.inkMuted, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3 };
const selectStyle = { display: "block", marginTop: 5, width: "100%", padding: "8px 9px", border: `1px solid ${C.border}`, borderRadius: 6, background: "white", color: C.ink };
const searchBox = { margin: "0 14px 10px", padding: "8px 10px", background: "#0f1a22", border: "1px solid #2a3d4c", borderRadius: 7, display: "flex", gap: 7 };
const searchInput = { border: 0, outline: 0, width: "100%", minWidth: 0, background: "transparent", color: "white" };
const querySelectStyle = { display: "block", marginTop: 5, width: "100%", padding: "8px 9px", border: "1px solid #2a3d4c", borderRadius: 7, background: "#0f1a22", color: "white", outline: 0 };
const sidebarIcdStyle = { display: "block", width: "fit-content", marginTop: 3, padding: "1px 5px", borderRadius: 4, background: "#193441", color: "#8FE0D4", fontSize: 9 };
const sidebarItemStyle = (selected) => ({ display: "flex", alignItems: "center", textAlign: "left", width: "100%", border: 0, borderLeft: selected ? "3px solid #8FE0D4" : "3px solid transparent", borderRadius: 7, marginBottom: 3, padding: "9px 8px", background: selected ? C.navySoft : "transparent", color: "white", cursor: "pointer" });
const tabStyle = (selected) => ({ border: 0, borderBottom: selected ? `2px solid ${C.teal}` : "2px solid transparent", padding: "10px 14px", background: "none", cursor: "pointer", color: selected ? C.ink : C.inkFaint, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 });
const exportLinkStyle = { display: "inline-flex", alignItems: "center", gap: 5, padding: "9px 10px", borderRadius: 7, border: `1px solid ${C.border}`, color: C.inkMuted, textDecoration: "none", fontSize: 12, fontWeight: 600, background: "white" };
const evidenceBarStyle = { minHeight: 36, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "7px 22px", background: "#FBFCFD", borderBottom: `1px solid ${C.border}` };
const focusPanelStyle = { display: "flex", alignItems: "flex-start", gap: 9, flexWrap: "wrap", padding: "9px 22px", background: "#F4FBF9", borderBottom: `1px solid ${C.border}`, color: C.inkMuted, fontSize: 11 };
const alignedSectionStyle = { flex: 1, overflow: "auto", padding: 18, background: C.bg };
const alignedTableStyle = { width: "100%", minWidth: 760, borderCollapse: "collapse", background: "white", border: `1px solid ${C.border}`, borderRadius: 8, overflow: "hidden", fontSize: 12 };
const QUERY_PANEL = { accent: "#2563A6", background: "#F2F7FD", header: "#E2EEFA", border: "#AFCBE7" };
const CANDIDATE_PANEL = { accent: "#A35B08", background: "#FFF8ED", header: "#FCEACD", border: "#E7C38B" };
const patientPanelStyle = (isQuery) => {
  const palette = isQuery ? QUERY_PANEL : CANDIDATE_PANEL;
  return { background: palette.background, minWidth: 0, overflowY: "auto", padding: 18, borderTop: `4px solid ${palette.accent}`, boxShadow: `inset 0 0 0 1px ${palette.border}` };
};
const patientPanelHeaderStyle = (isQuery) => {
  const palette = isQuery ? QUERY_PANEL : CANDIDATE_PANEL;
  return { margin: "-18px -18px 15px", padding: "14px 18px 13px", background: palette.header, borderBottom: `1px solid ${palette.border}` };
};
const patientPanelRoleStyle = (isQuery) => {
  const palette = isQuery ? QUERY_PANEL : CANDIDATE_PANEL;
  return { display: "inline-block", padding: "2px 7px", borderRadius: 999, background: "rgba(255,255,255,.72)", border: `1px solid ${palette.border}`, color: palette.accent, fontSize: 9, fontWeight: 800, letterSpacing: 0.7, textTransform: "uppercase" };
};
const alignedQueryHeaderStyle = { background: QUERY_PANEL.header, color: QUERY_PANEL.accent, borderBottom: `3px solid ${QUERY_PANEL.accent}` };
const alignedCandidateHeaderStyle = { background: CANDIDATE_PANEL.header, color: CANDIDATE_PANEL.accent, borderBottom: `3px solid ${CANDIDATE_PANEL.accent}` };
const alignedQueryCellStyle = { background: QUERY_PANEL.background, borderLeft: `1px solid ${QUERY_PANEL.border}` };
const alignedCandidateCellStyle = { background: CANDIDATE_PANEL.background, borderLeft: `1px solid ${CANDIDATE_PANEL.border}` };
const evidenceChipStyle = { display: "inline-block", padding: "2px 6px", borderRadius: 999, background: "#DFF3EF", color: "#146B60", fontSize: 10, fontWeight: 700 };
const reviewPanelStyle = { padding: "13px 22px", background: "#FBFCFD", borderTop: `1px solid ${C.border}`, maxHeight: "34vh", overflowY: "auto" };
const criteriaGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "10px 14px" };
const scoreLabelStyle = { display: "grid", gap: 5, fontSize: 11, fontWeight: 700, color: C.inkMuted };
const scoreSelectStyle = { width: "100%", padding: "7px 9px", borderRadius: 6, border: `1px solid ${C.border}`, background: "white", color: C.ink, fontSize: 12 };
const overallScoreStyle = { gridColumn: "1 / -1", paddingTop: 10, borderTop: `1px solid ${C.border}`, maxWidth: 300 };
const saveReviewButtonStyle = { display: "inline-flex", alignItems: "center", gap: 6, padding: "9px 13px", border: 0, borderRadius: 7, background: C.teal, color: "white", fontSize: 12, fontWeight: 700, cursor: "pointer" };
const similarOnlyButtonStyle = (active, disabled) => ({ marginLeft: "auto", border: `2px solid ${active ? "#08776D" : C.teal}`, borderRadius: 9, padding: "8px 13px", background: active ? C.teal : "#F0FBF9", color: active ? "white" : "#08776D", fontSize: 12, fontWeight: 800, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1, display: "inline-flex", alignItems: "center", gap: 6, boxShadow: disabled ? "none" : active ? "0 4px 12px rgba(14,143,130,.32)" : "0 2px 7px rgba(14,143,130,.16)", transform: active ? "translateY(-1px)" : "none" });
const accountSummaryStyle = { marginTop: 14, paddingTop: 12, borderTop: "1px solid #2a3d4c", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, color: "#8da0ac", fontSize: 10 };
const darkIconButtonStyle = { border: "1px solid #2a3d4c", borderRadius: 6, padding: 7, display: "grid", placeItems: "center", background: "#0f1a22", color: "white", cursor: "pointer" };
const sidebarBackdropStyle = { position: "fixed", inset: 0, zIndex: 15, display: "flex", background: "rgba(5, 15, 22, .38)" };
const sidebarDrawerStyle = { width: "min(340px, 92vw)", height: "100%", flexShrink: 0, background: C.navy, color: "white", display: "flex", flexDirection: "column", boxShadow: "12px 0 36px rgba(5, 15, 22, .28)" };
const dashboardButtonStyle = { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 10px", border: `1px solid ${C.navySoft}`, borderRadius: 7, background: C.navy, color: "white", fontSize: 12, fontWeight: 700, cursor: "pointer" };
const homeNavButtonStyle = { display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 10px", border: `1px solid ${C.border}`, borderRadius: 7, background: "white", color: C.inkMuted, fontSize: 12, fontWeight: 700, cursor: "pointer" };
const utilityHomeStyle = { minHeight: "100vh", background: "linear-gradient(150deg, #F4F8F7 0%, #F8F6F0 55%, #EEF4F7 100%)", color: C.ink, fontFamily: "'Inter', sans-serif" };
const utilityHeaderStyle = { minHeight: 72, padding: "12px clamp(18px, 4vw, 52px)", boxSizing: "border-box", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 14, background: "rgba(255,255,255,.9)", borderBottom: `1px solid ${C.border}`, boxShadow: "0 3px 18px rgba(22,35,46,.05)" };
const utilityLogoStyle = { width: 42, height: 42, borderRadius: 11, display: "grid", placeItems: "center", background: C.navy, color: "#8FE0D4" };
const homeAccountStyle = { padding: "7px 10px", borderRadius: 999, background: C.tealSoft, color: "#0B6C62", fontSize: 11 };
const homeLogoutStyle = { display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 10px", borderRadius: 7, border: `1px solid ${C.border}`, background: "white", color: C.inkMuted, fontSize: 12, fontWeight: 700, cursor: "pointer" };
const utilityContentStyle = { width: "min(1120px, calc(100% - 36px))", margin: "0 auto", padding: "clamp(42px, 7vw, 84px) 0 60px" };
const homeEyebrowStyle = { display: "inline-block", padding: "5px 9px", borderRadius: 999, background: C.tealSoft, color: "#0B6C62", fontSize: 10, fontWeight: 800, letterSpacing: 0.8, textTransform: "uppercase" };
const utilityGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 18, marginTop: 34 };
const primaryUtilityCardStyle = { minHeight: 270, padding: 24, textAlign: "left", border: "1px solid #B9D8EF", borderRadius: 14, background: "linear-gradient(150deg, #FFFFFF 0%, #EDF6FF 100%)", boxShadow: "0 16px 40px rgba(37,99,166,.12)", fontFamily: "inherit", cursor: "pointer" };
const llmUtilityCardStyle = { ...primaryUtilityCardStyle, border: "1px solid #D9C6EE", background: "linear-gradient(150deg, #FFFFFF 0%, #F5EEFC 100%)", boxShadow: "0 16px 40px rgba(101,66,138,.11)" };
const adminUtilityCardStyle = { ...primaryUtilityCardStyle, border: "1px solid #B9DED7", background: "linear-gradient(150deg, #FFFFFF 0%, #EFF9F6 100%)", boxShadow: "0 12px 32px rgba(20,107,96,.09)" };
const futureUtilityCardStyle = { minHeight: 270, boxSizing: "border-box", padding: 24, border: `1px dashed ${C.border}`, borderRadius: 14, background: "rgba(255,255,255,.62)", opacity: 0.72 };
const primaryUtilityIconStyle = { width: 48, height: 48, borderRadius: 12, display: "grid", placeItems: "center", background: C.navy, color: "#8FE0D4" };
const llmUtilityIconStyle = { ...primaryUtilityIconStyle, background: "#3E2D56", color: "#D9C6EE" };
const adminUtilityIconStyle = { ...primaryUtilityIconStyle, background: "#146B60", color: "#DFF3EF" };
const futureUtilityIconStyle = { width: 48, height: 48, borderRadius: 12, display: "grid", placeItems: "center", background: "#EDF0F1", color: C.inkFaint };
const openUtilityStyle = { display: "flex", alignItems: "center", gap: 4, marginTop: 24, color: "#2563A6", fontSize: 12, fontWeight: 800 };
const loginPageStyle = { minHeight: "100vh", display: "grid", placeItems: "center", padding: 20, background: "linear-gradient(135deg, #0b1720, #16313d)", color: C.ink, fontFamily: "'Inter', sans-serif" };
const loginCardStyle = { width: "min(420px, 100%)", boxSizing: "border-box", padding: 32, borderRadius: 14, background: "white", boxShadow: "0 20px 70px rgba(0,0,0,.28)", display: "grid", gap: 14 };
const loginIconStyle = { width: 52, height: 52, borderRadius: 12, display: "grid", placeItems: "center", background: C.tealSoft, color: C.teal };
const loginLabelStyle = { display: "grid", gap: 6, color: C.inkMuted, fontSize: 12, fontWeight: 700 };
const loginInputStyle = { boxSizing: "border-box", width: "100%", minWidth: 0, padding: "10px 11px", border: `1px solid ${C.border}`, borderRadius: 7, background: "white", color: C.ink, outlineColor: C.teal };
const loginButtonStyle = { marginTop: 4, padding: "11px 14px", border: 0, borderRadius: 7, background: C.teal, color: "white", fontWeight: 700, cursor: "pointer" };
const modalBackdropStyle = { position: "fixed", inset: 0, zIndex: 20, display: "grid", placeItems: "center", padding: 24, background: "rgba(5, 15, 22, .7)" };
const accountModalStyle = { width: "min(850px, 100%)", maxHeight: "85vh", overflow: "auto", boxSizing: "border-box", padding: 24, borderRadius: 12, background: "white", boxShadow: "0 24px 80px rgba(0,0,0,.35)" };
const closeButtonStyle = { border: `1px solid ${C.border}`, borderRadius: 7, padding: 7, background: "white", color: C.inkMuted, display: "grid", placeItems: "center", cursor: "pointer" };
const createButtonStyle = { border: 0, borderRadius: 7, padding: "9px 12px", background: C.teal, color: "white", fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, cursor: "pointer" };
const llmPageStyle = { minHeight: "100vh", display: "flex", flexDirection: "column", background: "#F4F3F7", color: C.ink, fontFamily: "'Inter', sans-serif" };
const llmHeaderStyle = { minHeight: 68, boxSizing: "border-box", padding: "11px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, background: "white", borderBottom: `1px solid ${C.border}` };
const llmHeaderIconStyle = { width: 38, height: 38, display: "grid", placeItems: "center", borderRadius: 10, background: "#3E2D56", color: "#D9C6EE" };
const llmToolbarStyle = { minHeight: 64, boxSizing: "border-box", padding: "10px 18px", display: "flex", alignItems: "end", gap: 14, flexWrap: "wrap", background: "#FBFAFC", borderBottom: `1px solid ${C.border}` };
const llmWorkspaceStyle = { minHeight: 0, flex: 1, display: "grid", gridTemplateColumns: "minmax(230px, 290px) minmax(0, 1fr)" };
const llmRankingStyle = { minHeight: 0, background: "white", borderRight: `1px solid ${C.border}`, display: "flex", flexDirection: "column" };
const llmRankItemStyle = (selected) => ({ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "10px 9px", marginBottom: 4, border: `1px solid ${selected ? "#BFA5DD" : "transparent"}`, borderRadius: 7, background: selected ? "#F5EEFC" : "transparent", color: C.ink, textAlign: "left", fontFamily: "inherit", cursor: "pointer" });
const llmRankNumberStyle = { width: 28, color: "#7652A8", fontSize: 11, fontWeight: 800 };
const reviewedDotStyle = { width: 8, height: 8, borderRadius: "50%", background: C.teal, flexShrink: 0 };
const llmDetailStyle = { minWidth: 0, overflowY: "auto", padding: 16, display: "grid", gap: 14, alignContent: "start" };
const llmSummaryGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 };
const llmContextGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(330px, 1fr))", gap: 12 };
const clinicalContextTextStyle = { maxHeight: 260, overflowY: "auto", padding: 12, whiteSpace: "pre-wrap", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 11, lineHeight: 1.55 };
const llmExplanationGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 };
const llmReviewStyle = { display: "grid", gap: 12, padding: 15, borderRadius: 10, border: "1px solid #D9C6EE", background: "white", boxShadow: "0 8px 28px rgba(62,45,86,.07)" };
const llmReviewGridStyle = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 10 };
const llmEmptyStyle = { margin: "50px auto", width: "min(560px, calc(100% - 36px))", boxSizing: "border-box", padding: 28, display: "grid", justifyItems: "center", gap: 12, textAlign: "center", borderRadius: 12, border: `1px dashed ${C.border}`, background: "white", color: C.inkMuted, fontSize: 12 };
const llmErrorStyle = { position: "fixed", right: 18, bottom: 18, zIndex: 30, maxWidth: 480, padding: "10px 12px", borderRadius: 8, background: C.redSoft, border: "1px solid #E5B7B2", color: C.red, fontSize: 12, boxShadow: "0 8px 28px rgba(0,0,0,.12)" };
