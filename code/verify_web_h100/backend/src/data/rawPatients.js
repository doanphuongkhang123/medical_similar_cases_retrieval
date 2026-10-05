import fs from "fs";
import path from "path";

// The source tree is read-only. Verification decisions are intentionally saved
// elsewhere by store.js, never alongside clinical source data.
export const RAW_ROOT = process.env.RAW_ROOT || path.resolve(process.cwd(), "raw");
export const QUERY_PATIENT_ID = process.env.QUERY_PATIENT_ID || "";
const STRUCTURED_ROOT = process.env.STRUCTURED_ROOT || "";

function readJson(filePath, fallback = {}) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function directories(dirPath) {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch {
    return [];
  }
}

function isSafeSegment(value) {
  return typeof value === "string" && value.length > 0 && value === path.basename(value) && !value.includes("\\") && value !== "." && value !== "..";
}

function formatDate(value) {
  const text = String(value || "");
  if (/^\d{8}/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  return text.slice(0, 10) || "—";
}

function isFlagged(value, referenceRange) {
  const result = Number.parseFloat(value);
  const bounds = String(referenceRange || "").match(/-?\d+(?:[.,]\d+)?/g)?.map((item) => Number.parseFloat(item.replace(",", ".")));
  return Number.isFinite(result) && bounds?.length >= 2 && (result < bounds[0] || result > bounds[1]);
}

function imageUrl(patientId, recordId, modality, studyId, seriesId) {
  const params = new URLSearchParams({ patientId, recordId, modality, studyId, seriesId });
  return `/api/imaging/slice?${params.toString()}`;
}

function readStudies(patientId, recordId, recordDir, modality) {
  const modalityDir = path.join(recordDir, modality);
  return directories(modalityDir).map((studyId) => {
    const studyDir = path.join(modalityDir, studyId);
    const series = directories(studyDir).flatMap((seriesId) => {
      const seriesDir = path.join(studyDir, seriesId);
      if (!fs.existsSync(path.join(seriesDir, "raw.npy"))) return [];
      const meta = readJson(path.join(seriesDir, "meta.json"));
      return [{
        id: seriesId,
        label: meta.SeriesDescription || seriesId,
        sliceCount: Number(meta.n_slices) || 1,
        shape: Array.isArray(meta.shape) ? meta.shape : [],
        sliceUrl: imageUrl(patientId, recordId, modality, studyId, seriesId),
        metadata: Object.fromEntries(Object.entries(meta).filter(([key]) => !["source_zip", "sop_instance_uids_in_order", "frame_indices_in_order"].includes(key))),
      }];
    });
    const firstMeta = series[0] ? readJson(path.join(studyDir, series[0].id, "meta.json")) : {};
    return {
      id: studyId,
      label: `${modality} ${firstMeta.AccessionNumber || studyId}`,
      date: formatDate(firstMeta.StudyDate || studyId.match(/\d{8}/)?.[0]),
      series,
    };
  }).filter((study) => study.series.length > 0);
}

function recordFromDirectory(patientId, recordId) {
  const recordDir = path.join(RAW_ROOT, patientId, recordId);
  const sourceEhr = readJson(path.join(recordDir, "EHR", "text.json"));
  const sourceLabs = readJson(path.join(recordDir, "lab_result", "lab.json"), { results: [] });
  const supplementFile = STRUCTURED_ROOT ? path.join(STRUCTURED_ROOT, patientId, `${recordId}.json`) : "";
  const supplement = supplementFile && fs.existsSync(supplementFile) ? JSON.parse(fs.readFileSync(supplementFile, "utf8")) : {};
  if (supplement.patient_id && (supplement.patient_id !== patientId || supplement.visit_id !== recordId)) throw new Error("Thông tin bổ sung không khớp bệnh nhân/bệnh án");
  const labelledFields = [
    ["Chẩn đoán ra viện", sourceEhr.ChanDoanRaVien],
    ["Lý do vào viện", sourceEhr.LyDoVaoVien],
    ["Quá trình bệnh lý", sourceEhr.QuaTrinhBenhLy],
    ["Tóm tắt bệnh án", sourceEhr.TomTatBenhAn],
    ["Tiền sử bản thân", sourceEhr.TienSuBanThan],
    ["Tiền sử gia đình", sourceEhr.TienSuGiaDinh],
    ["Khoa điều trị", sourceEhr.TenPhongBan],
    ["Kết quả điều trị", sourceEhr.ketquadieutri],
    ["Chẩn đoán chính", sourceEhr.KhamBenhBenhChinh],
    ["Bệnh kèm theo", sourceEhr.KhamBenhBenhKemTheo],
    ["Khám tổn thương", sourceEhr.KhamBenhBoPhanTonThuong],
    ["Cận lâm sàng", sourceEhr.XetNghiemCLSCanLam],
    ["Diễn biến lâm sàng", sourceEhr.QuaTrinhBenhLyVaDienBienLamSang],
    ["Chẩn đoán trước phẫu thuật", sourceEhr.ChanDoanTruocPhauThuat],
    ["Chẩn đoán sau phẫu thuật", sourceEhr.ChanDoanSauPhauThuat],
    ["Phương pháp điều trị", sourceEhr.PPDT],
    ["Hướng điều trị", sourceEhr.HuongDieuTriVaCheDoTiepTheo],
  ];
  const displayValue = value => typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
  const details = labelledFields.filter(([, value]) => value != null && value !== "").map(([label, value]) => [label, displayValue(value)]);
  const shownKeys = new Set(["ChanDoanRaVien", "LyDoVaoVien", "QuaTrinhBenhLy", "TomTatBenhAn", "TienSuBanThan", "TienSuGiaDinh", "TenPhongBan", "ketquadieutri", "KhamBenhBenhChinh", "KhamBenhBenhKemTheo", "KhamBenhBoPhanTonThuong", "XetNghiemCLSCanLam", "QuaTrinhBenhLyVaDienBienLamSang", "ChanDoanTruocPhauThuat", "ChanDoanSauPhauThuat", "PPDT", "HuongDieuTriVaCheDoTiepTheo"]);
  for (const [key, value] of Object.entries(sourceEhr)) {
    if (!shownKeys.has(key) && value != null && value !== "") details.push([key, displayValue(value)]);
  }
  for (const [key, value] of Object.entries(supplement.canonical_ehr || {})) {
    if (value == null || value === "" || displayValue(value) === displayValue(sourceEhr[key])) continue;
    details.push([`${key} (bệnh án gốc)`, displayValue(value)]);
  }
  const labs = Array.isArray(sourceLabs.results) ? sourceLabs.results.map((lab) => ({
    name: lab.TEN_CHI_SO || lab.name || "—",
    value: lab.GIA_TRI ?? lab.value ?? "—",
    unit: lab.DON_VI_DO || lab.unit || "",
    range: lab.khoang_tham_chieu || lab.range || "—",
    flagged: isFlagged(lab.GIA_TRI ?? lab.value, lab.khoang_tham_chieu || lab.range),
    date: formatDate(lab.NGAY_KQ || lab.date),
    sample: lab.LoaiMau || lab.sample || "—",
    department: lab.TenPhongBan || lab.department || "—",
    diagnosis: lab.ChanDoan || "",
    source_fields: lab,
  })) : [];

  return {
    id: recordId,
    label: `Bệnh án ${recordId}`,
    date: formatDate(sourceEhr.NgayVaoVien),
    ehr: { details, source_fields: sourceEhr },
    labs,
    structured_available: Boolean(supplement.patient_id),
    demographics: supplement.demographics || {},
    canonical_ehr: supplement.canonical_ehr || {},
    diagnoses: supplement.diagnoses || [],
    medicines: supplement.medicines || [],
    source_medicines: supplement.source_medicines || null,
    procedures: supplement.procedures || [],
    studies: {
      XQ: readStudies(patientId, recordId, recordDir, "XQ"),
      CT: readStudies(patientId, recordId, recordDir, "CT"),
      MRI: readStudies(patientId, recordId, recordDir, "MRI"),
    },
    sourceEhr,
  };
}

export function getPatient(patientId) {
  if (!isSafeSegment(patientId)) return null;
  const patientDir = path.join(RAW_ROOT, patientId);
  if (!fs.statSync(patientDir, { throwIfNoEntry: false })?.isDirectory()) return null;
  // DICOM is the retired legacy layout, not an admission record.
  const records = directories(patientDir)
    .filter((recordId) => recordId !== "DICOM")
    .map((recordId) => recordFromDirectory(patientId, recordId));
  if (records.length === 0) return null;
  const primary = records[0];
  const source = primary.sourceEhr;
  return {
    id: patientId,
    age: source.Tuoi || source.tuoi || "—",
    gender: source.GioiTinh || source.Gioi || "—",
    records: records.map(({ sourceEhr, ...record }) => record),
  };
}

function shuffle(values) {
  const copy = [...values];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

export function chooseRandomCandidates(count = 20) {
  const ids = directories(RAW_ROOT)
    .filter((id) => id !== QUERY_PATIENT_ID)
    .filter((id) => directories(path.join(RAW_ROOT, id)).some((recordId) => recordId !== "DICOM"));
  return shuffle(ids).slice(0, count);
}

export function resolveRawNpy({ patientId, recordId, modality, studyId, seriesId }) {
  if (![patientId, recordId, modality, studyId, seriesId].every(isSafeSegment)) return null;
  if (!["XQ", "CT", "MRI"].includes(modality)) return null;
  const seriesDir = path.join(RAW_ROOT, patientId, recordId, modality, studyId, seriesId);
  const npyPath = path.join(seriesDir, "raw.npy");
  return fs.existsSync(npyPath) ? { npyPath, meta: readJson(path.join(seriesDir, "meta.json")) } : null;
}

export function listPatients() {
  return directories(RAW_ROOT).filter(isSafeSegment).flatMap(id => {
    const recordIds = directories(path.join(RAW_ROOT, id)).filter(record => record !== "DICOM");
    if (!recordIds.length) return [];
    const modalities = ["XQ", "CT", "MRI"].filter(modality => recordIds.some(record => directories(path.join(RAW_ROOT, id, record, modality)).length));
    return [{ id, record_count: recordIds.length, modalities }];
  });
}
