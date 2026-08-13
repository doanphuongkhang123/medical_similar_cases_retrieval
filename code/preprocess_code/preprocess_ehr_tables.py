"""Chuẩn hóa workbook EHR thành các bảng dùng cho mô hình theo lượt khám.

Dữ liệu gốc chỉ được đọc. Đầu ra không chứa tên bệnh nhân, địa chỉ, bảo hiểm,
người liên hệ hoặc định danh nhân viên y tế.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SHEETS = {
    "visits": "thông tin bệnh án",
    "orders": "chỉ định DVKT",
    "medicines": "Thuốc",
    "labs": "KQCLS",
    "procedures": "Phẫu thuật thủ thuật",
}

EMPTY_TEXT = {"", "null", "none", "nan", "nat"}

MAIN_NOTE_FIELDS = [
    ("Lý do vào viện", "LyDoVaoVien"),
    ("Bệnh sử", "QuaTrinhBenhLy"),
    ("Tiền sử bản thân", "TienSuBanThan"),
    ("Tiền sử gia đình", "TienSuGiaDinh"),
    ("Khám toàn thân", "KhamBenhToanThan"),
    ("Khám vùng tổn thương", "KhamBenhBoPhanTonThuong"),
    ("Khám thần kinh", "ThanKinh"),
    ("Khám tuần hoàn", "TuanHoan"),
    ("Khám hô hấp", "HoHap"),
    ("Khám tiêu hóa", "TieuHoa"),
    ("Khám cơ xương khớp", "CoXuongKhop"),
    ("Khám tiết niệu", "TietNieu"),
    ("Khám sinh dục", "SinhDuc"),
    ("Khám khác", "KhamBenhKhac"),
    ("Cận lâm sàng cần làm", "XetNghiemCLSCanLam"),
    ("Tóm tắt bệnh án", "TomTatBenhAn"),
    ("Tiên lượng", "KhamBenhTienLuong"),
    ("Hướng điều trị", "HuongDanDieuTri"),
    ("Diễn biến lâm sàng", "QuaTrinhBenhLyVaDienBienLamSang"),
    ("Tóm tắt xét nghiệm máu", "XNMau"),
    ("Tóm tắt xét nghiệm tế bào", "XNTeBao"),
    ("Tóm tắt giải phẫu bệnh", "XNBLGP"),
    ("Tóm tắt X-quang", "XNXQuang"),
    ("Tóm tắt siêu âm", "XNSieuAm"),
    ("Tóm tắt cận lâm sàng khác", "CacXNKhac"),
    ("Phẫu thuật", "PPPhauThuat"),
    ("Hóa chất", "PPHoaChat"),
    ("Điều trị khác", "PPDieuTriKhac"),
    ("Tình trạng ra viện", "TinhTrangNguoiBenhRaVien"),
    ("Hướng điều trị tiếp theo", "HuongDieuTriVaCheDoTiepTheo"),
    ("Mô tả tổn thương", "MoTaTonThuong"),
    ("Lời dặn thầy thuốc", "LoiDanThayThuoc"),
    ("Phương pháp điều trị", "PPDT"),
    ("Ghi chú", "GhiChu"),
]

MAIN_DIAGNOSIS_FIELDS = [
    ("discharge", "ChanDoanRaVien"),
    ("preoperative", "ChanDoanTruocPhauThuat"),
    ("postoperative", "ChanDoanSauPhauThuat"),
    ("primary_exam", "KhamBenhBenhChinh"),
    ("comorbidity", "KhamBenhBenhKemTheo"),
    ("differential", "KhamBenhPhanBiet"),
]

VITAL_FIELDS = [
    ("Mach", "pulse", "lần/phút"),
    ("NhipTho", "respiratory_rate", "lần/phút"),
    ("NhietDo", "temperature", "°C"),
    ("CanNang", "weight", "kg"),
    ("HuyetApCao", "systolic_blood_pressure", "mmHg"),
    ("HuyetApThap", "diastolic_blood_pressure", "mmHg"),
]


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()
    return "" if text.casefold() in EMPTY_TEXT else text


def clean_key(value: Any) -> str:
    text = clean(value)
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def normalized(value: Any) -> str:
    return clean(value).casefold()


def clean_frame_columns(frame: pd.DataFrame, fields: Iterable[str]) -> None:
    for field in fields:
        if field in frame.columns:
            frame[field] = frame[field].map(clean)


def parse_time(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def first_nonempty(values: Iterable[Any]) -> str:
    for value in values:
        text = clean(value)
        if text:
            return text
    return ""


def join_unique(values: Iterable[Any], separator: str = " | ") -> str:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean(value)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return separator.join(result)


def stable_id(prefix: str, *values: Any) -> str:
    payload = json.dumps([clean(value) for value in values], ensure_ascii=False).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:24]}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_workbook(path: Path) -> dict[str, pd.DataFrame]:
    excel = pd.ExcelFile(path, engine="openpyxl")
    missing = set(SHEETS.values()) - set(excel.sheet_names)
    if missing:
        raise ValueError(f"Thiếu trang tính bắt buộc: {sorted(missing)}")
    return {
        key: pd.read_excel(excel, sheet_name=sheet, dtype=object)
        for key, sheet in SHEETS.items()
    }


def build_visits(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, str]]:
    raw = frames["visits"].copy()
    raw["visit_id"] = raw["SoBenhAn"].map(clean_key)
    raw["patient_id"] = raw["SoVaoVien"].map(clean_key)
    if (raw["visit_id"] == "").any() or (raw["patient_id"] == "").any():
        raise ValueError("SoBenhAn hoặc SoVaoVien có giá trị rỗng; không thể tạo khóa chính.")
    if raw["visit_id"].duplicated().any():
        raise ValueError("SoBenhAn không duy nhất trong trang thông tin bệnh án.")

    orders = frames["orders"].copy()
    orders["visit_id"] = orders["SoBenhAn"].map(clean_key)
    demographics = (
        orders.groupby("visit_id", as_index=False)
        .agg(birth_year=("NamSinh", first_nonempty), gender_code=("GioiTinh", first_nonempty))
    )
    visits = pd.DataFrame({
        "patient_id": raw["patient_id"],
        "visit_id": raw["visit_id"],
        "admission_time": parse_time(raw["NgayVaoVien"]),
        "discharge_time": parse_time(raw["NgayRaVien"]),
        "department": raw["TenPhongBan"].map(clean),
    }).merge(demographics, on="visit_id", how="left")
    visits["birth_year"] = pd.to_numeric(visits["birth_year"], errors="coerce").astype("Int64")
    visits["age_at_visit"] = visits["admission_time"].dt.year - visits["birth_year"]
    visits.loc[~visits["age_at_visit"].between(0, 120), "age_at_visit"] = pd.NA
    visits["age_at_visit"] = visits["age_at_visit"].astype("Int64")
    visit_to_patient = dict(zip(visits["visit_id"], visits["patient_id"]))
    return visits, visit_to_patient


def build_diagnoses(frames: dict[str, pd.DataFrame], visit_to_patient: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(visit: Any, diag_type: str, code: Any, text: Any, event_time: Any,
            sheet: str, field: str) -> None:
        visit_id = clean_key(visit)
        patient_id = visit_to_patient.get(visit_id, "")
        code_value, text_value = clean(code), clean(text)
        if patient_id and (code_value or text_value):
            rows.append({
                "patient_id": patient_id,
                "visit_id": visit_id,
                "diagnosis_code": code_value,
                "diagnosis_text": text_value,
                "diagnosis_type": diag_type,
                "event_time": event_time,
                "source_sheet": sheet,
                "source_field": field,
            })

    main = frames["visits"]
    for row in main.itertuples(index=False):
        data = row._asdict()
        visit_id = data["SoBenhAn"]
        admission, discharge = data.get("NgayVaoVien"), data.get("NgayRaVien")
        add(visit_id, "primary_icd", data.get("MaICD"), "", admission, SHEETS["visits"], "MaICD")
        for code in re.split(r"[;,|]+", clean(data.get("ICD_phu"))):
            add(visit_id, "secondary_icd", code, "", admission, SHEETS["visits"], "ICD_phu")
        for diag_type, field in MAIN_DIAGNOSIS_FIELDS:
            time = discharge if diag_type == "discharge" else admission
            add(visit_id, diag_type, "", data.get(field), time, SHEETS["visits"], field)

    source_specs = [
        ("orders", "SoBenhAn", "ChanDoan", "NgayYeuCau", "order_context"),
        ("medicines", "sobenhan", "ChanDoanKhoaKham", "NgayKham", "medicine_context"),
        ("labs", "SoBenhAn", "ChanDoan", "NGAY_KQ", "result_context"),
    ]
    for frame_key, visit_field, text_field, time_field, diag_type in source_specs:
        frame = frames[frame_key]
        for visit, text, event_time in frame[[visit_field, text_field, time_field]].itertuples(index=False, name=None):
            add(visit, diag_type, "", text, event_time, SHEETS[frame_key], text_field)

    order_visit = {
        clean_key(order_id): clean_key(visit_id)
        for order_id, visit_id in frames["orders"][["YeuCauChiTiet_Id", "SoBenhAn"]].itertuples(index=False, name=None)
        if clean_key(order_id)
    }
    procedure = frames["procedures"]
    for order_id, before, after, event_time in procedure[
        ["YeuCauChiTiet_Id", "ICD_TruocPhauThuat_MoTa", "ICD_SauPhauThuat_MoTa", "ThoiGianBatDau"]
    ].itertuples(index=False, name=None):
        visit = order_visit.get(clean_key(order_id), "")
        add(visit, "preoperative", "", before, event_time, SHEETS["procedures"], "ICD_TruocPhauThuat_MoTa")
        add(visit, "postoperative", "", after, event_time, SHEETS["procedures"], "ICD_SauPhauThuat_MoTa")

    diagnoses = pd.DataFrame(rows)
    diagnoses["event_time"] = parse_time(diagnoses["event_time"])
    diagnoses["code_key"] = diagnoses["diagnosis_code"].map(normalized)
    diagnoses["text_key"] = diagnoses["diagnosis_text"].map(normalized)
    grouped = (
        diagnoses.sort_values(["patient_id", "visit_id", "event_time"], na_position="last")
        .groupby(["patient_id", "visit_id", "code_key", "text_key"], as_index=False, dropna=False)
        .agg(
            diagnosis_code=("diagnosis_code", first_nonempty),
            diagnosis_text=("diagnosis_text", first_nonempty),
            diagnosis_type=("diagnosis_type", join_unique),
            event_time=("event_time", "min"),
            source_sheet=("source_sheet", join_unique),
            source_field=("source_field", join_unique),
            source_row_count=("visit_id", "size"),
        )
    )
    grouped["diagnosis_id"] = [
        stable_id("diag", row.patient_id, row.visit_id, row.code_key, row.text_key)
        for row in grouped.itertuples(index=False)
    ]
    return grouped[[
        "diagnosis_id", "patient_id", "visit_id", "diagnosis_code", "diagnosis_text",
        "diagnosis_type", "event_time", "source_sheet", "source_field", "source_row_count",
    ]]


def build_medicines(frames: dict[str, pd.DataFrame], visit_to_patient: dict[str, str]) -> pd.DataFrame:
    frame = frames["medicines"].copy()
    frame["visit_id"] = frame["sobenhan"].map(clean_key)
    frame["patient_id"] = frame["visit_id"].map(visit_to_patient)
    fields = [
        "TenDuoc", "TenHoatChat", "DuongDung", "strSLSang", "strSLTrua",
        "strSLChieu", "strSLToi", "DonViTinh", "SoNgay", "SoLuongTong",
        "LoiDan", "GhiChu", "LyDoTraThuoc",
    ]
    clean_frame_columns(frame, fields)
    medicines = pd.DataFrame({
        "patient_id": frame["patient_id"],
        "visit_id": frame["visit_id"],
        "drug_name": frame["TenDuoc"],
        "active_ingredient": frame["TenHoatChat"],
        "route": frame["DuongDung"],
        "dose_morning": frame["strSLSang"],
        "dose_noon": frame["strSLTrua"],
        "dose_afternoon": frame["strSLChieu"],
        "dose_evening": frame["strSLToi"],
        "unit": frame["DonViTinh"],
        "days": pd.to_numeric(frame["SoNgay"].str.replace(",", ".", regex=False), errors="coerce"),
        "total_quantity": pd.to_numeric(frame["SoLuongTong"].str.replace(",", ".", regex=False), errors="coerce"),
        "instructions": [join_unique(values, separator="; ") for values in zip(frame["GhiChu"], frame["LoiDan"])],
        "prescribed_time": parse_time(frame["NgayKham"]),
        "status": np.where(frame["LyDoTraThuoc"].ne(""), "returned", "prescribed"),
        "return_reason": frame["LyDoTraThuoc"],
        "source_sheet": SHEETS["medicines"],
    })
    medicines = medicines[medicines["patient_id"].notna() & medicines["drug_name"].ne("")]
    dedup_fields = [column for column in medicines.columns if column != "source_sheet"]
    medicines = (
        medicines.groupby(dedup_fields, as_index=False, dropna=False)
        .agg(source_row_count=("source_sheet", "size"))
    )
    medicines["medicine_id"] = [
        stable_id("med", row.patient_id, row.visit_id, row.drug_name, row.active_ingredient,
                  row.prescribed_time, row.route, row.dose_morning, row.dose_noon,
                  row.dose_afternoon, row.dose_evening, row.unit, row.days,
                  row.total_quantity, row.instructions, row.status, row.return_reason)
        for row in medicines.itertuples(index=False)
    ]
    medicines["source_sheet"] = SHEETS["medicines"]
    return medicines[[
        "medicine_id", "patient_id", "visit_id", "drug_name", "active_ingredient", "route",
        "dose_morning", "dose_noon", "dose_afternoon", "dose_evening", "unit", "days",
        "total_quantity", "instructions", "prescribed_time", "status", "return_reason",
        "source_sheet", "source_row_count",
    ]]


def build_procedures(frames: dict[str, pd.DataFrame], visit_to_patient: dict[str, str]) -> pd.DataFrame:
    orders = frames["orders"].copy()
    orders["visit_id"] = orders["SoBenhAn"].map(clean_key)
    orders["patient_id"] = orders["visit_id"].map(visit_to_patient)
    orders["order_id"] = orders["YeuCauChiTiet_Id"].map(clean_key)
    clean_frame_columns(orders, ["TenDichVu", "TenPhongBan", "TenPhongBan.1", "loaimau", "ViTriMau", "GhiChu", "ChanDoan"])

    labs = frames["labs"].copy()
    labs["order_id"] = labs["YeuCauChiTiet_Id"].map(clean_key)
    clean_frame_columns(labs, ["MA_DICH_VU"])
    service_codes = labs.groupby("order_id", as_index=False).agg(service_code=("MA_DICH_VU", join_unique))

    actual = frames["procedures"].copy()
    actual["order_id"] = actual["YeuCauChiTiet_Id"].map(clean_key)
    actual_fields = [
        "TenDichVu", "ten_dich_vu", "CanThiepPhauThuat", "LoaiPhauThuat", "pp_vocam",
        "TrinhTuThucHien_Text", "DanLuu", "KetQua", "nhom_chiphi", "noi_thuc_hien",
    ]
    clean_frame_columns(actual, actual_fields)
    actual["start_time"] = parse_time(actual["ThoiGianBatDau"])
    actual["end_time"] = parse_time(actual["ThoiGianKetThuc"])
    actual["received_time"] = parse_time(actual["ThoiGianTiepNhan"])
    actual_agg = actual.groupby("order_id", as_index=False).agg(
        performed_name=("ten_dich_vu", join_unique),
        source_performed_name=("TenDichVu", join_unique),
        intervention=("CanThiepPhauThuat", join_unique),
        procedure_class=("LoaiPhauThuat", join_unique),
        anesthesia=("pp_vocam", join_unique),
        procedure_report=("TrinhTuThucHien_Text", join_unique),
        drainage=("DanLuu", join_unique),
        result=("KetQua", join_unique),
        procedure_group=("nhom_chiphi", join_unique),
        performed_department=("noi_thuc_hien", join_unique),
        received_time=("received_time", "min"),
        start_time=("start_time", "min"),
        end_time=("end_time", "max"),
        performed_row_count=("order_id", "size"),
    )

    procedures = pd.DataFrame({
        "patient_id": orders["patient_id"],
        "visit_id": orders["visit_id"],
        "order_id": orders["order_id"],
        "procedure_name": orders["TenDichVu"],
        "ordered_time": parse_time(orders["NgayYeuCau"]),
        "ordering_department": orders["TenPhongBan"],
        "target_department": orders["TenPhongBan.1"],
        "sample_type": orders["loaimau"],
        "sample_site": orders["ViTriMau"],
        "order_note": orders["GhiChu"],
        "indication_diagnosis": orders["ChanDoan"],
    }).merge(service_codes, on="order_id", how="left").merge(actual_agg, on="order_id", how="left")
    procedures = procedures[procedures["patient_id"].notna() & procedures["procedure_name"].ne("")]
    procedures["status"] = np.where(procedures["performed_row_count"].notna(), "performed", "ordered")
    procedures["performed_row_count"] = procedures["performed_row_count"].fillna(0).astype("Int64")
    # Một số bản xuất có thể lặp đúng cùng một dòng chỉ định. Chỉ loại bản lặp
    # hoàn toàn; không gộp các lần chỉ định khác thời gian hoặc khác nội dung.
    procedure_identity = [
        "patient_id", "visit_id", "order_id", "procedure_name", "ordered_time",
        "ordering_department", "target_department", "sample_type", "sample_site",
        "order_note", "indication_diagnosis", "service_code", "performed_name",
        "intervention", "status", "start_time", "end_time", "procedure_report", "result",
    ]
    procedures = procedures.drop_duplicates(procedure_identity, keep="first").copy()
    procedures["procedure_id"] = [
        stable_id("proc", row.patient_id, row.visit_id, row.order_id, row.procedure_name, row.ordered_time)
        for row in procedures.itertuples(index=False)
    ]
    procedures["source_sheet"] = SHEETS["orders"] + " | " + SHEETS["procedures"]
    ordered = [
        "procedure_id", "patient_id", "visit_id", "order_id", "service_code", "procedure_name",
        "performed_name", "intervention", "status", "procedure_class", "procedure_group",
        "ordered_time", "received_time", "start_time", "end_time", "ordering_department",
        "target_department", "performed_department", "anesthesia", "drainage", "sample_type",
        "sample_site", "indication_diagnosis", "order_note", "procedure_report", "result",
        "source_sheet", "performed_row_count",
    ]
    for column in ordered:
        if column not in procedures:
            procedures[column] = ""
    return procedures[ordered]


def build_clinical_notes(frames: dict[str, pd.DataFrame], visit_to_patient: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(visit: Any, note_type: str, section: str, text: Any, event_time: Any,
            sheet: str, source_key: Any = "") -> None:
        visit_id = clean_key(visit)
        patient_id, value = visit_to_patient.get(visit_id, ""), clean(text)
        if patient_id and value and value.casefold() != "richeditcontrol1":
            rows.append({
                "patient_id": patient_id,
                "visit_id": visit_id,
                "note_type": note_type,
                "section_name": section,
                "note_text": value,
                "event_time": event_time,
                "source_sheet": sheet,
                "source_key": clean_key(source_key),
            })

    main = frames["visits"]
    for row in main.itertuples(index=False):
        data = row._asdict()
        for section, field in MAIN_NOTE_FIELDS:
            add(data["SoBenhAn"], "visit_note", section, data.get(field), data.get("NgayVaoVien"), SHEETS["visits"], field)

    orders = frames["orders"]
    for visit, order_id, note, event_time in orders[["SoBenhAn", "YeuCauChiTiet_Id", "GhiChu", "NgayYeuCau"]].itertuples(index=False, name=None):
        add(visit, "order_note", "Ghi chú chỉ định", note, event_time, SHEETS["orders"], order_id)

    labs = frames["labs"]
    for visit, order_id, description, conclusion, event_time in labs[
        ["SoBenhAn", "YeuCauChiTiet_Id", "MO_TA", "KET_LUAN", "NGAY_KQ"]
    ].itertuples(index=False, name=None):
        text = "\n".join(part for part in [
            f"Mô tả: {clean(description)}" if clean(description) else "",
            f"Kết luận: {clean(conclusion)}" if clean(conclusion) else "",
        ] if part)
        add(visit, "clinical_report", "Báo cáo cận lâm sàng", text, event_time, SHEETS["labs"], order_id)

    order_visit = {
        clean_key(order_id): clean_key(visit_id)
        for order_id, visit_id in orders[["YeuCauChiTiet_Id", "SoBenhAn"]].itertuples(index=False, name=None)
        if clean_key(order_id)
    }
    procedures = frames["procedures"]
    for order_id, report, result, event_time in procedures[
        ["YeuCauChiTiet_Id", "TrinhTuThucHien_Text", "KetQua", "ThoiGianBatDau"]
    ].itertuples(index=False, name=None):
        text = "\n".join(part for part in [
            f"Trình tự thực hiện: {clean(report)}" if clean(report) else "",
            f"Kết quả: {clean(result)}" if clean(result) else "",
        ] if part)
        add(order_visit.get(clean_key(order_id), ""), "procedure_report", "Biên bản thủ thuật", text, event_time, SHEETS["procedures"], order_id)

    notes = pd.DataFrame(rows)
    notes["event_time"] = parse_time(notes["event_time"])
    notes["text_key"] = notes["note_text"].map(normalized)
    notes = (
        notes.sort_values(["patient_id", "visit_id", "event_time"], na_position="last")
        .groupby(["patient_id", "visit_id", "note_type", "section_name", "text_key"], as_index=False)
        .agg(
            note_text=("note_text", first_nonempty),
            event_time=("event_time", "min"),
            source_sheet=("source_sheet", join_unique),
            source_key=("source_key", join_unique),
            source_row_count=("visit_id", "size"),
        )
    )
    notes["note_id"] = [
        stable_id("note", row.patient_id, row.visit_id, row.note_type, row.section_name, row.text_key)
        for row in notes.itertuples(index=False)
    ]
    return notes[[
        "note_id", "patient_id", "visit_id", "note_type", "section_name", "note_text",
        "event_time", "source_sheet", "source_key", "source_row_count",
    ]]


def build_observations(frames: dict[str, pd.DataFrame], visit_to_patient: dict[str, str]) -> pd.DataFrame:
    labs = frames["labs"].copy()
    labs["visit_id"] = labs["SoBenhAn"].map(clean_key)
    labs["patient_id"] = labs["visit_id"].map(visit_to_patient)
    clean_frame_columns(labs, ["TEN_CHI_SO", "GIA_TRI", "DON_VI_DO", "khoang_tham_chieu", "LoaiMau", "MA_DICH_VU"])
    numeric_text = labs["GIA_TRI"].str.replace(",", ".", regex=False).str.replace(r"^[<>]=?\s*", "", regex=True)
    observations = pd.DataFrame({
        "patient_id": labs["patient_id"],
        "visit_id": labs["visit_id"],
        "order_id": labs["YeuCauChiTiet_Id"].map(clean_key),
        "service_code": labs["MA_DICH_VU"],
        "observation_name": labs["TEN_CHI_SO"],
        "result_text": labs["GIA_TRI"],
        "result_numeric": pd.to_numeric(numeric_text, errors="coerce"),
        "unit": labs["DON_VI_DO"],
        "reference_range": labs["khoang_tham_chieu"],
        "specimen_type": labs["LoaiMau"],
        "observed_time": parse_time(labs["NGAY_KQ"]),
        "source_sheet": SHEETS["labs"],
    })
    observations = observations[observations["patient_id"].notna() & observations["observation_name"].ne("")]

    main = frames["visits"].copy()
    main["visit_id"] = main["SoBenhAn"].map(clean_key)
    main["patient_id"] = main["visit_id"].map(visit_to_patient)
    vital_rows: list[dict[str, Any]] = []
    for field, name, unit in VITAL_FIELDS:
        for patient_id, visit_id, value, event_time in main[["patient_id", "visit_id", field, "NgayVaoVien"]].itertuples(index=False, name=None):
            text = clean(value)
            number = pd.to_numeric(pd.Series([text.replace(",", ".")]), errors="coerce").iloc[0]
            if text and pd.notna(number):
                vital_rows.append({
                    "patient_id": patient_id, "visit_id": visit_id, "order_id": "", "service_code": "",
                    "observation_name": name, "result_text": text, "result_numeric": float(number),
                    "unit": unit, "reference_range": "", "specimen_type": "",
                    "observed_time": event_time, "source_sheet": SHEETS["visits"],
                })
    if vital_rows:
        observations = pd.concat([observations, pd.DataFrame(vital_rows)], ignore_index=True)
    observations["observed_time"] = pd.to_datetime(observations["observed_time"], errors="coerce")
    observations["observation_id"] = [
        stable_id("obs", row.patient_id, row.visit_id, row.order_id, row.observation_name,
                  row.observed_time, row.result_text, index)
        for index, row in enumerate(observations.itertuples(index=False))
    ]
    return observations[[
        "observation_id", "patient_id", "visit_id", "order_id", "service_code",
        "observation_name", "result_text", "result_numeric", "unit", "reference_range",
        "specimen_type", "observed_time", "source_sheet",
    ]]


def attach_visit_summary(visits: pd.DataFrame, diagnoses: pd.DataFrame, medicines: pd.DataFrame,
                         procedures: pd.DataFrame, notes: pd.DataFrame,
                         observations: pd.DataFrame) -> pd.DataFrame:
    result = visits.copy()
    note_text = notes.copy()
    note_text["section"] = "[" + note_text["section_name"] + "]\n" + note_text["note_text"]
    aggregated_notes = note_text.groupby(["patient_id", "visit_id"])["section"].agg("\n\n".join).rename("clinical_note")
    result = result.merge(aggregated_notes, on=["patient_id", "visit_id"], how="left")
    result["clinical_note"] = result["clinical_note"].fillna("")
    tables = [
        ("diagnosis_count", diagnoses), ("medicine_count", medicines),
        ("procedure_count", procedures), ("note_section_count", notes),
        ("observation_count", observations),
    ]
    for column, frame in tables:
        counts = frame.groupby(["patient_id", "visit_id"]).size().rename(column)
        result = result.merge(counts, on=["patient_id", "visit_id"], how="left")
        result[column] = result[column].fillna(0).astype("Int64")
    result["has_diagnosis"] = result["diagnosis_count"] > 0
    result["has_medicine"] = result["medicine_count"] > 0
    result["has_procedure"] = result["procedure_count"] > 0
    result["has_clinical_note"] = result["note_section_count"] > 0
    result["primary_key"] = result["patient_id"] + "::" + result["visit_id"]
    columns = [
        "patient_id", "visit_id", "primary_key", "admission_time", "discharge_time", "department",
        "birth_year", "age_at_visit", "gender_code", "clinical_note", "diagnosis_count",
        "medicine_count", "procedure_count", "note_section_count", "observation_count",
        "has_diagnosis", "has_medicine", "has_procedure", "has_clinical_note",
    ]
    return result[columns]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _records_json(frame: pd.DataFrame, fields: list[str]) -> str:
    records = []
    for row in frame[fields].itertuples(index=False, name=None):
        records.append({field: _json_value(value) for field, value in zip(fields, row)})
    return json.dumps(records, ensure_ascii=False, separators=(",", ":"))


def build_visit_ehr_rows(visits: pd.DataFrame, diagnoses: pd.DataFrame, medicines: pd.DataFrame,
                         procedures: pd.DataFrame) -> pd.DataFrame:
    """Tạo bảng một dòng cho mỗi lượt khám.

    Ba cột sự kiện là chuỗi JSON để không làm mất cấu trúc khi lưu một lượt
    khám trên một dòng. Các bảng sự kiện riêng vẫn là nguồn thuận tiện nhất để
    dựng đồ thị và huấn luyện.
    """
    diagnosis_fields = ["diagnosis_id", "diagnosis_code", "diagnosis_text", "diagnosis_type", "event_time"]
    medicine_fields = [
        "medicine_id", "drug_name", "active_ingredient", "route", "dose_morning", "dose_noon",
        "dose_afternoon", "dose_evening", "unit", "days", "total_quantity", "instructions",
        "prescribed_time", "status",
    ]
    procedure_fields = [
        "procedure_id", "order_id", "service_code", "procedure_name", "performed_name",
        "intervention", "status", "ordered_time", "start_time", "end_time", "procedure_report", "result",
    ]

    def aggregate(frame: pd.DataFrame, fields: list[str], output_name: str) -> pd.DataFrame:
        rows = []
        for (patient_id, visit_id), group in frame.groupby(["patient_id", "visit_id"], sort=False):
            rows.append({"patient_id": patient_id, "visit_id": visit_id, output_name: _records_json(group, fields)})
        return pd.DataFrame(rows, columns=["patient_id", "visit_id", output_name])

    result = visits.copy()
    for frame, fields, output_name in [
        (diagnoses, diagnosis_fields, "diagnosis"),
        (medicines, medicine_fields, "medicine"),
        (procedures, procedure_fields, "procedure"),
    ]:
        result = result.merge(aggregate(frame, fields, output_name), on=["patient_id", "visit_id"], how="left")
        result[output_name] = result[output_name].fillna("[]")
    result.insert(0, "ehr_row_id", result["primary_key"])
    return result


def build_graph_tables(visits: pd.DataFrame, diagnoses: pd.DataFrame, medicines: pd.DataFrame,
                       procedures: pd.DataFrame, notes: pd.DataFrame,
                       observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chuyển mỗi lượt khám thành một đồ thị sao với các liên kết phụ có nghĩa."""
    node_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, str]] = []
    visit_nodes: dict[tuple[str, str], str] = {}
    procedure_by_order: dict[tuple[str, str, str], str] = {}

    def graph_id(patient_id: str, visit_id: str) -> str:
        return f"{patient_id}::{visit_id}"

    def add_node(patient_id: Any, visit_id: Any, node_id: str, node_type: str,
                 concept_code: Any = "", concept_name: Any = "", text_value: Any = "",
                 numeric_value: Any = np.nan, unit: Any = "", event_time: Any = pd.NaT,
                 source_event_id: Any = "") -> None:
        patient, visit = clean_key(patient_id), clean_key(visit_id)
        node_rows.append({
            "graph_id": graph_id(patient, visit), "patient_id": patient, "visit_id": visit,
            "node_id": node_id, "node_type": node_type, "concept_code": clean(concept_code),
            "concept_name": clean(concept_name), "text_value": clean(text_value),
            "numeric_value": numeric_value, "unit": clean(unit), "event_time": event_time,
            "source_event_id": clean_key(source_event_id),
        })

    def add_edge(patient_id: Any, visit_id: Any, source: str, relation: str, target: str) -> None:
        patient, visit = clean_key(patient_id), clean_key(visit_id)
        edge_rows.append({
            "graph_id": graph_id(patient, visit), "patient_id": patient, "visit_id": visit,
            "source_node_id": source, "relation_type": relation, "target_node_id": target,
        })

    relation_names = {
        "DIAGNOSIS": ("has_diagnosis", "diagnosis_of"),
        "MEDICINE": ("has_medicine", "medicine_of"),
        "PROCEDURE": ("has_procedure", "procedure_of"),
        "NOTE": ("has_note", "note_of"),
        "OBSERVATION": ("has_observation", "observation_of"),
    }

    for row in visits.itertuples(index=False):
        node_id = stable_id("visit", row.patient_id, row.visit_id)
        visit_nodes[(row.patient_id, row.visit_id)] = node_id
        add_node(row.patient_id, row.visit_id, node_id, "VISIT", concept_name=row.department,
                 text_value="", event_time=row.admission_time, source_event_id=row.primary_key)

    def connect_to_visit(patient: str, visit: str, node_id: str, node_type: str) -> None:
        visit_node = visit_nodes[(patient, visit)]
        forward, reverse = relation_names[node_type]
        add_edge(patient, visit, visit_node, forward, node_id)
        add_edge(patient, visit, node_id, reverse, visit_node)

    for row in diagnoses.itertuples(index=False):
        name = row.diagnosis_text or row.diagnosis_code
        add_node(row.patient_id, row.visit_id, row.diagnosis_id, "DIAGNOSIS",
                 row.diagnosis_code, name, row.diagnosis_type, event_time=row.event_time,
                 source_event_id=row.diagnosis_id)
        connect_to_visit(row.patient_id, row.visit_id, row.diagnosis_id, "DIAGNOSIS")

    for row in medicines.itertuples(index=False):
        name = row.active_ingredient or row.drug_name
        add_node(row.patient_id, row.visit_id, row.medicine_id, "MEDICINE", concept_name=name,
                 text_value=join_unique([row.drug_name, row.route, row.instructions], "; "),
                 numeric_value=row.total_quantity, unit=row.unit, event_time=row.prescribed_time,
                 source_event_id=row.medicine_id)
        connect_to_visit(row.patient_id, row.visit_id, row.medicine_id, "MEDICINE")

    for row in procedures.itertuples(index=False):
        name = first_nonempty([row.performed_name, row.intervention, row.procedure_name])
        text = join_unique([row.procedure_report, row.result, row.order_note], "\n")
        event_time = row.start_time if pd.notna(row.start_time) else row.ordered_time
        add_node(row.patient_id, row.visit_id, row.procedure_id, "PROCEDURE", row.service_code,
                 name, text, event_time=event_time,
                 source_event_id=row.order_id)
        connect_to_visit(row.patient_id, row.visit_id, row.procedure_id, "PROCEDURE")
        procedure_by_order[(row.patient_id, row.visit_id, clean_key(row.order_id))] = row.procedure_id

    for row in notes.itertuples(index=False):
        add_node(row.patient_id, row.visit_id, row.note_id, "NOTE", concept_name=row.section_name,
                 text_value=row.note_text, event_time=row.event_time, source_event_id=row.source_key)
        connect_to_visit(row.patient_id, row.visit_id, row.note_id, "NOTE")
        procedure_node = procedure_by_order.get((row.patient_id, row.visit_id, clean_key(row.source_key)))
        if procedure_node:
            add_edge(row.patient_id, row.visit_id, procedure_node, "has_report", row.note_id)
            add_edge(row.patient_id, row.visit_id, row.note_id, "report_of", procedure_node)

    for row in observations.itertuples(index=False):
        add_node(row.patient_id, row.visit_id, row.observation_id, "OBSERVATION", row.service_code,
                 row.observation_name, row.result_text, row.result_numeric, row.unit,
                 row.observed_time, row.order_id)
        connect_to_visit(row.patient_id, row.visit_id, row.observation_id, "OBSERVATION")
        procedure_node = procedure_by_order.get((row.patient_id, row.visit_id, clean_key(row.order_id)))
        if procedure_node:
            add_edge(row.patient_id, row.visit_id, procedure_node, "has_result", row.observation_id)
            add_edge(row.patient_id, row.visit_id, row.observation_id, "result_of", procedure_node)

    nodes = pd.DataFrame(node_rows)
    edges = pd.DataFrame(edge_rows)
    nodes["event_time"] = pd.to_datetime(nodes["event_time"], errors="coerce")
    nodes["numeric_value"] = pd.to_numeric(nodes["numeric_value"], errors="coerce")
    if nodes.duplicated(["graph_id", "node_id"]).any():
        duplicate_types = (
            nodes.loc[nodes.duplicated(["graph_id", "node_id"], keep=False), "node_type"]
            .value_counts().to_dict()
        )
        raise ValueError(f"node_id bị trùng trong cùng một đồ thị: {duplicate_types}")
    known_nodes = set(zip(nodes["graph_id"], nodes["node_id"]))
    edge_sources = set(zip(edges["graph_id"], edges["source_node_id"]))
    edge_targets = set(zip(edges["graph_id"], edges["target_node_id"]))
    if (edge_sources | edge_targets) - known_nodes:
        raise ValueError("Có cạnh tham chiếu đến nút không tồn tại.")
    return nodes, edges


def validate(visits: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    known = set(zip(visits["patient_id"], visits["visit_id"]))
    report: dict[str, Any] = {
        "visit_primary_key_unique": not visits.duplicated(["patient_id", "visit_id"]).any(),
        "visit_id_unique": not visits["visit_id"].duplicated().any(),
        "empty_patient_id": int(visits["patient_id"].eq("").sum()),
        "empty_visit_id": int(visits["visit_id"].eq("").sum()),
        "clinical_note_max_characters": int(visits["clinical_note"].str.len().max()),
        "tables": {},
    }
    for name, frame in tables.items():
        keys = set(zip(frame["patient_id"], frame["visit_id"]))
        report["tables"][name] = {
            "rows": int(len(frame)),
            "visits": int(frame["visit_id"].nunique()),
            "orphan_visit_keys": int(len(keys - known)),
        }
    if not report["visit_primary_key_unique"] or report["empty_patient_id"] or report["empty_visit_id"]:
        raise ValueError(f"Kiểm tra khóa chính thất bại: {report}")
    if any(item["orphan_visit_keys"] for item in report["tables"].values()):
        raise ValueError(f"Có sự kiện không nối được với lượt khám: {report}")
    return report


def write_readme(output: Path, counts: dict[str, int]) -> None:
    text = f"""# EHR đã tiền xử lý

Khóa chính của bảng `visits` là `(patient_id, visit_id)`.

- `patient_id`: lấy từ `SoVaoVien`; đã đối chiếu với `mayte` ở trang Thuốc.
- `visit_id`: lấy từ `SoBenhAn`.
- `visits.parquet`: một dòng cho mỗi lượt khám, có cột `clinical_note`.
- `visit_ehr.parquet`: một dòng cho mỗi lượt khám, có bốn cột `diagnosis`,
  `medicine`, `procedure`, `clinical_note`; ba cột đầu là danh sách JSON.
- `diagnoses.parquet`: các chẩn đoán đã loại bản lặp trong từng lượt khám.
- `medicines.parquet`: thuốc, liều theo buổi, đường dùng, thời gian và trạng thái trả thuốc.
- `procedures.parquet`: dịch vụ đã chỉ định; nếu nối được biên bản thì trạng thái là `performed`.
- `clinical_notes.parquet`: từng phần ghi chú/báo cáo, phù hợp để đưa qua bộ mã hóa văn bản.
- `observations.parquet`: xét nghiệm và dấu hiệu sinh tồn; giữ riêng vì không thuộc ba nhóm trên.
- `graph_nodes.parquet` và `graph_edges.parquet`: mỗi `graph_id` là một đồ thị của một lượt khám.

Số dòng: {json.dumps(counts, ensure_ascii=False)}

Đã loại tên bệnh nhân, địa chỉ, số bảo hiểm, người liên hệ và định danh nhân viên y tế.
Các trường văn bản lâm sàng chưa được khử định danh bên trong nội dung tự do;
không chia sẻ các tệp này ra ngoài môi trường được phép.
Đây là bản toàn bộ lượt khám, nên có thể chứa thông tin lúc ra viện và sau thủ thuật.
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tiền xử lý XLSX EHR thành các bảng theo lượt khám.")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frames = read_workbook(args.workbook)
    visits, visit_to_patient = build_visits(frames)
    diagnoses = build_diagnoses(frames, visit_to_patient)
    medicines = build_medicines(frames, visit_to_patient)
    procedures = build_procedures(frames, visit_to_patient)
    notes = build_clinical_notes(frames, visit_to_patient)
    observations = build_observations(frames, visit_to_patient)
    visits = attach_visit_summary(visits, diagnoses, medicines, procedures, notes, observations)
    visit_ehr = build_visit_ehr_rows(visits, diagnoses, medicines, procedures)
    graph_nodes, graph_edges = build_graph_tables(
        visits, diagnoses, medicines, procedures, notes, observations,
    )

    tables = {
        "diagnoses": diagnoses, "medicines": medicines, "procedures": procedures,
        "clinical_notes": notes, "observations": observations,
    }
    quality = validate(visits, tables)
    args.output.mkdir(parents=True, exist_ok=True)
    visits.to_parquet(args.output / "visits.parquet", index=False)
    visit_ehr.to_parquet(args.output / "visit_ehr.parquet", index=False)
    graph_nodes.to_parquet(args.output / "graph_nodes.parquet", index=False)
    graph_edges.to_parquet(args.output / "graph_edges.parquet", index=False)
    for name, frame in tables.items():
        frame.to_parquet(args.output / f"{name}.parquet", index=False)

    counts = {"patients": int(visits["patient_id"].nunique()), "visits": int(len(visits))}
    counts.update({name: int(len(frame)) for name, frame in tables.items()})
    counts.update({"graph_nodes": int(len(graph_nodes)), "graph_edges": int(len(graph_edges))})
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_workbook": str(args.workbook),
        "source_sha256": file_sha256(args.workbook),
        "snapshot_scope": "full_visit",
        "primary_key": ["patient_id", "visit_id"],
        "patient_id_definition": "SoVaoVien; đối chiếu với mayte ở trang Thuốc",
        "visit_id_definition": "SoBenhAn",
        "direct_identifiers_removed": [
            "TenBenhNhan", "ten_benh_nhan", "DiaChi", "SoBHYT", "NguoiLienHe",
            "BacSi", "MA_BS_DOC_KQ", "LanhDaoKhoa_Id", "ThuTruongDonVi_Id",
        ],
        "clinical_free_text_deidentified": False,
        "counts": counts,
        "quality": quality,
        "runtime": {"python": platform.python_version(), "pandas": pd.__version__},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(args.output, counts)
    print(json.dumps({"output": str(args.output), "counts": counts, "quality": quality}, ensure_ascii=False))


if __name__ == "__main__":
    main()
