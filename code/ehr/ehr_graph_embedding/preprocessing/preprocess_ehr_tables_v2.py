"""Semantic EHR preprocessing v2.

This wrapper keeps the v1 relational/graph output contract, but adds
semantic value typing and audit artifacts.  Numeric, censored numeric,
range, categorical and free-text values are kept distinct; a non-numeric
clinical result is never silently converted to missing.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import numbers
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import preprocess_ehr_tables as v1


MISSING_LITERALS = {"", "null", "none", "nan", "nat", "not available"}
FREE_TEXT_FIELDS = {
    "Lý do vào viện", "Bệnh sử", "Tiền sử bản thân", "Tiền sử gia đình",
    "Khám toàn thân", "Khám vùng tổn thương", "Khám thần kinh",
    "Khám tuần hoàn", "Khám hô hấp", "Khám tiêu hóa", "Khám cơ xương khớp",
    "Khám tiết niệu", "Khám sinh dục", "Khám khác", "Cận lâm sàng cần làm",
    "Tóm tắt bệnh án", "Tiên lượng", "Hướng điều trị", "Diễn biến lâm sàng",
    "Tóm tắt xét nghiệm máu", "Tóm tắt xét nghiệm tế bào",
    "Tóm tắt giải phẫu bệnh", "Tóm tắt X-quang", "Tóm tắt siêu âm",
    "Tóm tắt cận lâm sàng khác", "Phẫu thuật", "Hóa chất", "Điều trị khác",
    "Tình trạng ra viện", "Hướng điều trị tiếp theo", "Mô tả tổn thương",
    "Lời dặn thầy thuốc", "Phương pháp điều trị", "Ghi chú", "ChanDoan",
    "ChanDoanKhoaKham", "MO_TA", "KET_LUAN", "KetQua",
}
ID_FIELDS = {
    "SoBenhAn", "sobenhan", "SoVaoVien", "mayte", "YeuCauChiTiet_Id",
    "BenhAn_Id", "BenhAnChiTiet_Id", "MA_DICH_VU", "MaICD", "ICD_phu",
}

POSITIVE = {"positive", "pos", "dương tính", "duong tinh", "phát hiện", "phat hien", "detected"}
NEGATIVE = {"negative", "neg", "âm tính", "am tinh", "không phát hiện", "khong phat hien", "not detected"}
INDETERMINATE = {"indeterminate", "không xác định", "khong xac dinh", "nghi ngờ", "nghi ngo", "equivocal"}
NORMAL = {"normal", "bình thường", "binh thuong"}
ABNORMAL = {"abnormal", "bất thường", "bat thuong"}
NOT_APPLICABLE = {"n/a", "not applicable", "không áp dụng", "khong ap dung"}
NOT_PERFORMED = {"not done", "not performed", "chưa thực hiện", "chua thuc hien", "chưa làm", "chua lam"}
UNKNOWN = {"unknown", "không rõ", "khong ro", "không xác định", "khong xac dinh"}
ORDINAL_LEVELS = {
    "trace": 1.0,
    "low": 1.0,
    "thấp": 1.0,
    "thap": 1.0,
    "mild": 1.0,
    "moderate": 2.0,
    "vừa": 2.0,
    "vua": 2.0,
    "medium": 2.0,
    "high": 3.0,
    "cao": 3.0,
    "severe": 3.0,
}

COMPARATOR_RE = re.compile(r"^\s*(<=|>=|<|>)\s*([+-]?\d+(?:[.,]\d+)?)\s*$")
RANGE_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:-|–|—|to|đến)\s*([+-]?\d+(?:[.,]\d+)?)\s*$",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"^\s*[+-]?\d+(?:[.,]\d+)?\s*$")
APPROX_RE = re.compile(
    r"^\s*(?:~|≈|about|approximately|approx\.?|khoảng|khoang)\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(.*)$",
    re.IGNORECASE,
)
SCIENTIFIC_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*[x×]\s*10\s*\^?\s*([+-]?\d+)\s*(.*)$",
    re.IGNORECASE,
)


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if not isinstance(result, (list, tuple, np.ndarray, pd.Series)) else False
    except (TypeError, ValueError):
        return False


def clean(value: Any) -> str:
    if _is_missing(value):
        return ""
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()
    return "" if text.casefold() in MISSING_LITERALS else text


def clean_key(value: Any) -> str:
    text = clean(value)
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def normalized(value: Any) -> str:
    return clean(value).casefold()


def entity_key(value: Any) -> str:
    text = normalized(value)
    return re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()


def _number(value: str) -> float | None:
    text = value.strip().replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_one_time(value: Any) -> pd.Timestamp:
    if _is_missing(value):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    raw = clean(value)
    compact = re.sub(r"\.0+$", "", raw)
    if re.fullmatch(r"\d{12}", compact):
        return pd.to_datetime(compact, format="%Y%m%d%H%M", errors="coerce")
    if re.fullmatch(r"\d{8}", compact):
        return pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    if isinstance(value, numbers.Number) and 20000 <= float(value) <= 60000:
        return pd.to_datetime(float(value), unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def parse_time(series: pd.Series) -> pd.Series:
    return series.map(_parse_one_time)


def _category(value: str) -> tuple[str, str] | None:
    key = normalized(value)
    if not key:
        return None
    if key in POSITIVE:
        return "positive", "polarity"
    if key in NEGATIVE:
        return "negative", "polarity"
    if key in INDETERMINATE:
        return "indeterminate", "polarity"
    if key in NORMAL:
        return "normal", "interpretation"
    if key in ABNORMAL:
        return "abnormal", "interpretation"
    if key in NOT_APPLICABLE:
        return "not_applicable", "status"
    if key in NOT_PERFORMED:
        return "not_performed", "status"
    if key in UNKNOWN:
        return "unknown", "status"
    if key in ORDINAL_LEVELS:
        return key, "ordinal"
    if key in {"-", "negative"}:
        return "negative", "polarity"
    if re.fullmatch(r"\+{1,4}", key) or re.fullmatch(r"[1-4]\+", key):
        normalized_plus = key.replace("+", "plus")
        return f"positive_{normalized_plus}", "semi_quantitative"
    return None


def _ordinal_level(category: str) -> float:
    if category.startswith("positive_"):
        encoded = category.removeprefix("positive_")
        if encoded and encoded.replace("plus", "") == "":
            return float(encoded.count("plus"))
        suffix = encoded.replace("plus", "")
        if suffix.isdigit():
            return float(suffix)
        if suffix == "":
            return 1.0
    return float(ORDINAL_LEVELS.get(category, np.nan))


def parse_result(value: Any) -> dict[str, Any]:
    raw = clean(value)
    base = {
        "result_raw": raw,
        "result_type": "missing",
        "result_numeric": np.nan,
        "value_proxy": np.nan,
        "proxy_method": "",
        "numeric_subtype": "",
        "value_unit": "",
        "result_operator": "",
        "result_lower_bound": np.nan,
        "result_upper_bound": np.nan,
        "result_category": "",
        "result_category_group": "",
        "ordinal_level": np.nan,
    }
    if not raw:
        return base

    category = _category(raw)
    if category:
        result_type = "semi_quantitative" if category[1] in {"semi_quantitative", "ordinal"} else "categorical"
        base.update(
            result_type=result_type,
            result_category=category[0],
            result_category_group=category[1],
            ordinal_level=_ordinal_level(category[0]),
        )
        return base

    match = COMPARATOR_RE.match(raw)
    if match:
        operator = match.group(1)
        upper = _number(match.group(2)) if operator in {"<", "<="} else np.nan
        lower = _number(match.group(2)) if operator in {">", ">="} else np.nan
        base.update(
            result_type="numeric_censored",
            result_operator=operator,
            result_upper_bound=upper,
            result_lower_bound=lower,
            value_proxy=(upper / 2.0 if math.isfinite(upper) and upper >= 0 else lower),
            proxy_method="half_upper_bound_nonnegative" if math.isfinite(upper) and upper >= 0 else "lower_bound",
        )
        return base

    match = RANGE_RE.match(raw)
    if match:
        lower = _number(match.group(1))
        upper = _number(match.group(2))
        base.update(
            result_type="numeric_interval",
            result_lower_bound=lower,
            result_upper_bound=upper,
            value_proxy=(lower + upper) / 2.0 if lower is not None and upper is not None else np.nan,
            proxy_method="interval_midpoint",
        )
        return base

    match = APPROX_RE.match(raw)
    if match:
        number = _number(match.group(1))
        base.update(
            result_type="numeric_approx",
            result_numeric=number,
            value_proxy=number,
            proxy_method="approximate_value",
            numeric_subtype="approximate",
            value_unit=clean(match.group(2)),
        )
        return base

    match = SCIENTIFIC_RE.match(raw)
    if match:
        coefficient = _number(match.group(1))
        exponent = int(match.group(2))
        number = None if coefficient is None else coefficient * (10 ** exponent)
        base.update(
            result_type="numeric_with_unit",
            result_numeric=number,
            value_proxy=number,
            proxy_method="scientific_notation",
            numeric_subtype="scientific_notation",
            value_unit=clean(match.group(3)),
        )
        return base

    if NUMBER_RE.match(raw):
        number = _number(raw)
        base.update(
            result_type="numeric_exact",
            result_numeric=number,
            value_proxy=number,
            proxy_method="exact_value",
        )
        return base

    base["result_type"] = "free_text"
    return base


def _stable_category_id(category: str) -> int:
    fixed = {
        "negative": 0,
        "positive": 1,
        "indeterminate": -1,
        "normal": 10,
        "abnormal": 11,
    }
    if category in fixed:
        return fixed[category]
    digest = int.from_bytes(category.encode("utf-8"), "little", signed=False)
    return 100 + digest % 900000


def _assign_value_proxies(observations: pd.DataFrame) -> pd.DataFrame:
    """Create model proxies without overwriting the raw or exact result."""
    result = observations.copy()
    result["value_proxy"] = pd.to_numeric(result["value_proxy"], errors="coerce")
    result["proxy_method"] = result["proxy_method"].fillna("").astype(str)
    result["observation_name_normalized"] = result["observation_name"].map(entity_key)
    result["unit_normalized"] = result["unit"].map(entity_key)

    interval = result["result_type"].eq("numeric_interval")
    interval_missing_proxy = interval & result["value_proxy"].isna()
    result.loc[interval_missing_proxy, "value_proxy"] = (
        result.loc[interval_missing_proxy, "result_lower_bound"]
        + result.loc[interval_missing_proxy, "result_upper_bound"]
    ) / 2.0
    result.loc[interval & result["proxy_method"].eq(""), "proxy_method"] = "interval_midpoint"

    left_censored = result["result_type"].eq("numeric_censored") & result["result_operator"].isin(["<", "<="])
    left_missing_proxy = left_censored & result["value_proxy"].isna()
    result.loc[left_missing_proxy, "value_proxy"] = (
        result.loc[left_missing_proxy, "result_upper_bound"] / 2.0
    )
    result.loc[left_censored & result["proxy_method"].eq(""), "proxy_method"] = "half_upper_bound_nonnegative"

    right_censored = result["result_type"].eq("numeric_censored") & result["result_operator"].isin([">", ">="])
    for index, row in result.loc[right_censored].iterrows():
        lower = _number(str(row["result_lower_bound"]))
        if lower is None:
            continue
        same_test = (
            result["result_type"].isin(["numeric_exact", "numeric_with_unit"])
            & result["observation_name_normalized"].eq(row["observation_name_normalized"])
            & result["unit_normalized"].eq(row["unit_normalized"])
        )
        tail = pd.to_numeric(result.loc[same_test, "result_numeric"], errors="coerce")
        tail = tail[tail > lower]
        if not tail.empty:
            result.at[index, "value_proxy"] = lower + float((tail - lower).median())
            result.at[index, "proxy_method"] = "threshold_plus_group_tail_median"
        else:
            result.at[index, "value_proxy"] = lower
            result.at[index, "proxy_method"] = "lower_bound_fallback"

    return result


def _profile_frames(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    profiles: list[dict[str, Any]] = []
    dictionaries: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for sheet_key, frame in frames.items():
        sheet_name = v1.SHEETS[sheet_key]
        for column in frame.columns:
            values = frame[column].map(clean)
            nonempty = values[values.ne("")]
            counts = nonempty.value_counts(dropna=False)
            unique = int(nonempty.nunique())
            free_text = column in FREE_TEXT_FIELDS
            identifier = column in ID_FIELDS or column.lower().endswith("_id")
            high_cardinality = unique > 100
            data_kind = "free_text" if free_text else "identifier" if identifier else "categorical_or_mixed"
            examples = [] if free_text else [str(value) for value in counts.head(8).index.tolist()]
            profiles.append({
                "sheet_key": sheet_key,
                "sheet_name": sheet_name,
                "column": column,
                "row_count": int(len(frame)),
                "missing_count": int(values.eq("").sum()),
                "nonmissing_count": int(nonempty.size),
                "unique_count": unique,
                "data_kind": data_kind,
                "high_cardinality": high_cardinality,
                "top_examples": json.dumps(examples, ensure_ascii=False),
                "review_required": bool(high_cardinality and not identifier and not free_text),
            })
            if not free_text and not identifier and unique <= 1000:
                for raw, count in counts.items():
                    canon = entity_key(raw)
                    dictionaries.append({
                        "sheet_key": sheet_key,
                        "sheet_name": sheet_name,
                        "column": column,
                        "raw_value": raw,
                        "normalized_value": canon,
                        "value_count": int(count),
                        "category_id": _stable_category_id(canon) if canon else pd.NA,
                        "mapping_method": "NFKC_casefold_whitespace_punctuation",
                    })
            if high_cardinality and not identifier and not free_text:
                candidates = list(counts.head(500).index.astype(str))
                for value in candidates:
                    matches = difflib.get_close_matches(value, candidates, n=2, cutoff=0.92)
                    for suggestion in matches:
                        if suggestion != value and entity_key(suggestion) != entity_key(value):
                            review.append({
                                "sheet_key": sheet_key,
                                "column": column,
                                "value": value,
                                "suggested_value": suggestion,
                                "similarity": difflib.SequenceMatcher(None, value.casefold(), suggestion.casefold()).ratio(),
                                "action": "review_before_merge",
                            })

    return pd.DataFrame(profiles), pd.DataFrame(dictionaries), pd.DataFrame(review)


def build_observations_v2(frames: dict[str, pd.DataFrame], visit_to_patient: dict[str, str]) -> pd.DataFrame:
    labs = frames["labs"].copy()
    labs["visit_id"] = labs["SoBenhAn"].map(clean_key)
    labs["patient_id"] = labs["visit_id"].map(visit_to_patient)
    for field in ["TEN_CHI_SO", "GIA_TRI", "DON_VI_DO", "khoang_tham_chieu", "LoaiMau", "MA_DICH_VU"]:
        if field in labs:
            labs[field] = labs[field].map(clean)
    parsed = pd.DataFrame([parse_result(value) for value in labs["GIA_TRI"]])
    observations = pd.DataFrame({
        "patient_id": labs["patient_id"],
        "visit_id": labs["visit_id"],
        "order_id": labs["YeuCauChiTiet_Id"].map(clean_key),
        "service_code": labs["MA_DICH_VU"],
        "observation_name": labs["TEN_CHI_SO"],
        "result_text": labs["GIA_TRI"],
        "result_numeric": parsed["result_numeric"],
        "value_proxy": parsed["value_proxy"],
        "proxy_method": parsed["proxy_method"],
        "numeric_subtype": parsed["numeric_subtype"],
        "value_unit": parsed["value_unit"],
        "result_type": parsed["result_type"],
        "result_operator": parsed["result_operator"],
        "result_lower_bound": parsed["result_lower_bound"],
        "result_upper_bound": parsed["result_upper_bound"],
        "result_category": parsed["result_category"],
        "result_category_group": parsed["result_category_group"],
        "ordinal_level": parsed["ordinal_level"],
        "unit": labs["DON_VI_DO"],
        "reference_range": labs["khoang_tham_chieu"],
        "specimen_type": labs["LoaiMau"],
        "observed_time": parse_time(labs["NGAY_KQ"]),
        "source_sheet": v1.SHEETS["labs"],
    })
    observations = observations[observations["patient_id"].notna() & observations["observation_name"].ne("")]

    main = frames["visits"].copy()
    main["visit_id"] = main["SoBenhAn"].map(clean_key)
    main["patient_id"] = main["visit_id"].map(visit_to_patient)
    vital_rows: list[dict[str, Any]] = []
    for field, name, unit in v1.VITAL_FIELDS:
        for patient_id, visit_id, value, event_time in main[
            ["patient_id", "visit_id", field, "NgayVaoVien"]
        ].itertuples(index=False, name=None):
            parsed_value = parse_result(value)
            if parsed_value["result_type"] != "missing":
                vital_rows.append({
                    "patient_id": patient_id, "visit_id": visit_id, "order_id": "",
                    "service_code": "", "observation_name": name, "result_text": clean(value),
                    **{key: parsed_value[key] for key in (
                        "result_numeric", "value_proxy", "proxy_method", "numeric_subtype", "value_unit",
                        "result_type", "result_operator",
                        "result_lower_bound", "result_upper_bound", "result_category",
                        "result_category_group", "ordinal_level",
                    )},
                    "unit": unit, "reference_range": "", "specimen_type": "",
                    "observed_time": _parse_one_time(event_time),
                    "source_sheet": v1.SHEETS["visits"],
                })
    if vital_rows:
        observations = pd.concat([observations, pd.DataFrame(vital_rows)], ignore_index=True)

    observations["observation_name_normalized"] = observations["observation_name"].map(entity_key)
    observations["unit_normalized"] = observations["unit"].map(entity_key)
    observations = _assign_value_proxies(observations)
    observations["result_category_id"] = observations["result_category"].map(
        lambda value: _stable_category_id(value) if value else pd.NA
    ).astype("Int64")
    observations["observed_time"] = parse_time(observations["observed_time"])
    observations["observation_id"] = [
        v1.stable_id(
            "obs", row.patient_id, row.visit_id, row.order_id, row.observation_name,
            row.observed_time, row.result_text, index,
        )
        for index, row in enumerate(observations.itertuples(index=False))
    ]
    return observations[[
        "observation_id", "patient_id", "visit_id", "order_id", "service_code",
        "observation_name", "observation_name_normalized", "result_text", "result_numeric",
        "value_proxy", "proxy_method", "numeric_subtype", "value_unit", "result_type",
        "result_operator", "result_lower_bound", "result_upper_bound",
        "result_category", "result_category_group", "result_category_id", "unit",
        "ordinal_level", "unit_normalized", "reference_range", "specimen_type",
        "observed_time", "source_sheet",
    ]]


def _enrich_canonical_tables(
    medicines: pd.DataFrame,
    procedures: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    medicines = medicines.copy()
    medicines["drug_name_normalized"] = medicines["drug_name"].map(entity_key)
    medicines["active_ingredient_normalized"] = medicines["active_ingredient"].map(entity_key)
    medicines["route_normalized"] = medicines["route"].map(entity_key)
    medicines["unit_normalized"] = medicines["unit"].map(entity_key)
    medicines["status_id"] = medicines["status"].map({"prescribed": 1, "returned": 0}).astype("Int64")

    procedures = procedures.copy()
    procedures["procedure_name_normalized"] = procedures["procedure_name"].map(entity_key)
    procedures["status_id"] = procedures["status"].map({"performed": 1, "ordered": 0}).astype("Int64")
    procedures["service_code_normalized"] = procedures["service_code"].map(entity_key)
    return medicines, procedures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Patch v1 helpers so every reused builder receives the v2 semantics.
    v1.clean = clean
    v1.clean_key = clean_key
    v1.normalized = normalized
    v1.parse_time = parse_time
    v1.clean_frame_columns = lambda frame, fields: [
        frame.__setitem__(field, frame[field].map(clean)) for field in fields if field in frame.columns
    ]

    frames = v1.read_workbook(args.workbook)
    profiles, dictionaries, review = _profile_frames(frames)
    visits, visit_to_patient = v1.build_visits(frames)
    diagnoses = v1.build_diagnoses(frames, visit_to_patient)
    medicines = v1.build_medicines(frames, visit_to_patient)
    procedures = v1.build_procedures(frames, visit_to_patient)
    medicines, procedures = _enrich_canonical_tables(medicines, procedures)
    notes = v1.build_clinical_notes(frames, visit_to_patient)
    observations = build_observations_v2(frames, visit_to_patient)

    visits["admission_time"] = parse_time(frames["visits"]["NgayVaoVien"])
    visits["discharge_time"] = parse_time(frames["visits"]["NgayRaVien"])
    visits = v1.attach_visit_summary(visits, diagnoses, medicines, procedures, notes, observations)
    visit_ehr = v1.build_visit_ehr_rows(visits, diagnoses, medicines, procedures)
    graph_nodes, graph_edges = v1.build_graph_tables(
        visits, diagnoses, medicines, procedures, notes, observations,
    )

    tables = {
        "diagnoses": diagnoses,
        "medicines": medicines,
        "procedures": procedures,
        "clinical_notes": notes,
        "observations": observations,
    }
    quality = v1.validate(visits, tables)
    args.output.mkdir(parents=True, exist_ok=True)
    visits.to_parquet(args.output / "visits.parquet", index=False)
    visit_ehr.to_parquet(args.output / "visit_ehr.parquet", index=False)
    graph_nodes.to_parquet(args.output / "graph_nodes.parquet", index=False)
    graph_edges.to_parquet(args.output / "graph_edges.parquet", index=False)
    for name, frame in tables.items():
        frame.to_parquet(args.output / f"{name}.parquet", index=False)
    profiles.to_parquet(args.output / "column_profile.parquet", index=False)
    dictionaries.to_parquet(args.output / "value_dictionary.parquet", index=False)
    review.to_parquet(args.output / "normalization_review_candidates.parquet", index=False)

    counts = {"patients": int(visits["patient_id"].nunique()), "visits": int(len(visits))}
    counts.update({name: int(len(frame)) for name, frame in tables.items()})
    counts.update({"graph_nodes": int(len(graph_nodes)), "graph_edges": int(len(graph_edges))})
    manifest = {
        "preprocessing_version": "semantic_v2",
        "source_workbook": str(args.workbook),
        "snapshot_scope": "full_visit",
        "primary_key": ["patient_id", "visit_id"],
        "normalization_policy": {
            "missing_only_true_missing": True,
            "categorical_values_preserved": True,
            "censored_numeric_preserved": True,
            "range_numeric_preserved": True,
            "approximate_numeric_preserved": True,
            "compound_numeric_with_unit_preserved": True,
            "value_proxy_is_not_ground_truth": True,
            "fuzzy_auto_merge": False,
            "review_candidates_written": True,
        },
        "supported_result_types": [
            "missing", "numeric_exact", "numeric_censored", "numeric_interval",
            "numeric_approx", "numeric_with_unit", "categorical",
            "semi_quantitative", "not_applicable", "not_performed", "unknown", "free_text",
        ],
        "outputs": {
            "column_profile": "column_profile.parquet",
            "value_dictionary": "value_dictionary.parquet",
            "review_candidates": "normalization_review_candidates.parquet",
        },
        "counts": counts,
        "quality": quality,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "counts": counts, "quality": quality}, ensure_ascii=False))


if __name__ == "__main__":
    main()
