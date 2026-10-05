const API_URL = import.meta.env.VITE_API_URL || "/api";
export const API_ORIGIN = API_URL.startsWith("http") ? API_URL.replace(/\/api$/, "") : "";
const TOKEN_KEY = "patient_verify_token";
const queryParam = (queryPatientId) => queryPatientId
  ? `query_patient_id=${encodeURIComponent(queryPatientId)}` : "";

export function getAuthToken() {
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setAuthToken(token) {
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401 && token) {
    setAuthToken("");
    window.dispatchEvent(new Event("auth-expired"));
  }
  return response;
}

async function errorMessage(response, fallback) {
  try {
    const body = await response.json();
    return body.error || fallback;
  } catch {
    return fallback;
  }
}

export async function login(username, password) {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Không đăng nhập được"));
  const data = await res.json();
  setAuthToken(data.token);
  return data.user;
}

export async function fetchCurrentUser() {
  if (!getAuthToken()) return null;
  const res = await apiFetch(`${API_URL}/auth/me`);
  if (!res.ok) return null;
  return (await res.json()).user;
}

export async function logout() {
  try { await apiFetch(`${API_URL}/auth/logout`, { method: "POST" }); } finally { setAuthToken(""); }
}

export async function fetchUsers() {
  const res = await apiFetch(`${API_URL}/auth/users`);
  if (!res.ok) throw new Error(await errorMessage(res, "Không tải được danh sách tài khoản"));
  return (await res.json()).users;
}

export async function createAccount(payload) {
  const res = await apiFetch(`${API_URL}/auth/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Không tạo được tài khoản"));
  return (await res.json()).user;
}

export async function downloadComparisonExport(format, queryPatientId) {
  const res = await apiFetch(`${API_URL}/comparison/export?format=${format}&${queryParam(queryPatientId)}`);
  if (!res.ok) throw new Error(await errorMessage(res, "Không tải được file kết quả"));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `comparison-results-${queryPatientId}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function fetchPatientList() {
  const res = await apiFetch(`${API_URL}/patients`);
  if (!res.ok) throw new Error("Không tải được danh sách bệnh nhân");
  return res.json();
}

export async function fetchPatientDetail(id) {
  const res = await apiFetch(`${API_URL}/patients/${id}`);
  if (!res.ok) throw new Error("Không tải được chi tiết bệnh nhân");
  return res.json();
}

export async function submitVerification(id, { status, note }) {
  const res = await apiFetch(`${API_URL}/patients/${id}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note }),
  });
  if (!res.ok) throw new Error("Không lưu được kết quả xác minh");
  return res.json();
}

export async function fetchComparisonQueries() {
  const res = await apiFetch(`${API_URL}/comparison/queries`);
  if (!res.ok) throw new Error("Không tải được danh sách query");
  return res.json();
}

export async function fetchComparison(queryPatientId) {
  const suffix = queryParam(queryPatientId);
  const res = await apiFetch(`${API_URL}/comparison${suffix ? `?${suffix}` : ""}`);
  if (!res.ok) throw new Error("Không tải được phiên đối chiếu");
  return res.json();
}

export async function fetchComparisonCandidate(queryPatientId, id) {
  const res = await apiFetch(`${API_URL}/comparison/${encodeURIComponent(id)}?${queryParam(queryPatientId)}`);
  if (!res.ok) throw new Error("Không tải được hồ sơ bệnh nhân tương tự");
  return res.json();
}

export async function submitComparisonVerification(
  queryPatientId,
  id,
  { criteria_scores: criteriaScores, overall_similarity: overallSimilarity, note },
) {
  const res = await apiFetch(`${API_URL}/comparison/${encodeURIComponent(id)}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query_patient_id: queryPatientId,
      criteria_scores: criteriaScores,
      overall_similarity: overallSimilarity,
      note,
    }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Không lưu được kết quả xác minh"));
  return res.json();
}

export async function fetchLlmRetrievalCalls() {
  const res = await apiFetch(`${API_URL}/llm-retrieval`);
  if (!res.ok) throw new Error(await errorMessage(res, "Không tải được danh sách kết quả LLM"));
  return res.json();
}

export async function fetchLlmRetrievalCall(requestId) {
  const res = await apiFetch(`${API_URL}/llm-retrieval/${encodeURIComponent(requestId)}`);
  if (!res.ok) throw new Error(await errorMessage(res, "Không tải được kết quả LLM"));
  return res.json();
}

export async function submitLlmRetrievalReview(requestId, patientId, payload) {
  const res = await apiFetch(
    `${API_URL}/llm-retrieval/${encodeURIComponent(requestId)}/candidates/${encodeURIComponent(patientId)}/verify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) throw new Error(await errorMessage(res, "Không lưu được đánh giá LLM"));
  return res.json();
}

export async function downloadLlmRetrievalExport(format) {
  const res = await apiFetch(`${API_URL}/llm-retrieval/export?format=${format}`);
  if (!res.ok) throw new Error(await errorMessage(res, "Không tải được file đánh giá LLM"));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `llm-retrieval-verifications.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
