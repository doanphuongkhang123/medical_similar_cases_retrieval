from __future__ import annotations

import html
import os
from typing import Any

import pandas as pd
import streamlit as st

from config import AppConfig
from ehr_repository import EHRRepository
from retrieval import FusedRetrievalIndex, RetrievalResult, clean_id
from storage import ReviewStore


st.set_page_config(
    page_title="Expert Review · Similar Cases",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.25rem; padding-bottom: 3rem;}
      div[data-testid="stMetric"] {background: rgba(127, 127, 127, 0.08);
                                  border: 1px solid rgba(127, 127, 127, 0.28);
                                  border-radius: 0.75rem; padding: 0.6rem;}
      .case-meta {color: #52606d; font-size: 0.9rem; line-height: 1.45;}
      .case-diagnosis {font-size: 0.92rem; margin-top: 0.35rem;}
      .query-badge {display: inline-block; padding: .2rem .55rem; border-radius: 999px;
                    background: #e8f0fe; color: #174ea6; font-weight: 600;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="Đang tải fused embeddings của toàn bộ dataset…")
def load_services(config: AppConfig):
    config.validate()
    index = FusedRetrievalIndex.from_files(
        config.ehr_embeddings,
        config.text_embeddings,
        ehr_weight=config.ehr_weight,
        text_weight=config.text_weight,
    )
    repository = EHRRepository(config.ehr_root)
    store = ReviewStore(config.database_path)
    return index, repository, store


def display_frame(frame: pd.DataFrame, empty_message: str) -> None:
    if frame.empty:
        st.caption(empty_message)
        return
    st.dataframe(frame, hide_index=True, width="stretch")


def render_overview(repository: EHRRepository, visit_id: str, *, compact: bool) -> None:
    overview = repository.overview(visit_id)
    st.markdown(
        (
            f'<span class="query-badge">Visit {html.escape(overview["visit_id"])}</span>'
            if not compact
            else ""
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        (
            f'<div class="case-meta"><b>Patient:</b> {html.escape(overview["patient_id"])}'
            f' · <b>Tuổi:</b> {html.escape(overview["age_at_visit"] or "—")}'
            f' · <b>Giới:</b> {html.escape(overview["gender_code"] or "—")}<br>'
            f'<b>Khoa:</b> {html.escape(overview["department"] or "—")}<br>'
            f'<b>Điều trị:</b> {html.escape(overview["admission_time"] or "—")}'
            f' → {html.escape(overview["discharge_time"] or "—")}<br>'
            f'<b>Số mục:</b> chẩn đoán {overview["diagnosis_count"] or "0"}'
            f' · thuốc {overview["medicine_count"] or "0"}'
            f' · DVKT {overview["procedure_count"] or "0"}'
            f' · xét nghiệm {overview["observation_count"] or "0"}</div>'
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="case-diagnosis"><b>Chẩn đoán:</b> '
        f'{html.escape(repository.diagnosis_summary(visit_id, limit=6))}</div>',
        unsafe_allow_html=True,
    )


def render_full_ehr(repository: EHRRepository, visit_id: str) -> None:
    render_overview(repository, visit_id, compact=False)
    with st.expander("Ghi chú lâm sàng", expanded=True):
        note = repository.clinical_note(visit_id)
        st.text(note or "Không có ghi chú lâm sàng.")
    with st.expander("Chẩn đoán"):
        display_frame(repository.diagnoses(visit_id), "Không có chẩn đoán.")
    with st.expander("Thuốc"):
        display_frame(repository.medicines(visit_id), "Không có dữ liệu thuốc.")
    with st.expander("Dịch vụ kỹ thuật / thủ thuật"):
        display_frame(repository.procedures(visit_id), "Không có dữ liệu DVKT.")
    with st.expander("Xét nghiệm / quan sát"):
        display_frame(repository.observations(visit_id), "Không có dữ liệu xét nghiệm.")


def candidate_card(
    repository: EHRRepository,
    query_id: str,
    result: RetrievalResult,
) -> bool:
    visit_id = result.candidate_visit_id
    selection_key = f"selected::{query_id}::{visit_id}"
    detail_key = f"detail::{query_id}::{visit_id}"
    with st.container(border=True):
        choose_col, content_col = st.columns([0.08, 0.92], gap="small")
        with choose_col:
            selected = st.checkbox(
                f"Chọn case {visit_id}",
                key=selection_key,
                label_visibility="collapsed",
            )
        with content_col:
            title_col, score_col = st.columns([0.72, 0.28])
            with title_col:
                st.markdown(f"#### #{result.rank} · `{visit_id}`")
            with score_col:
                st.metric("Cosine", f"{result.score:.4f}")
            render_overview(repository, visit_id, compact=True)
            note = repository.clinical_note(visit_id)
            if note:
                normalized_note = " ".join(note.split())
                preview = normalized_note[:420]
                if len(normalized_note) > len(preview):
                    preview += "…"
                st.caption(preview)
            show_detail = st.checkbox("Xem chi tiết EHR", key=detail_key)
            if show_detail:
                tabs = st.tabs(["Ghi chú", "Chẩn đoán", "Thuốc", "DVKT", "Xét nghiệm"])
                with tabs[0]:
                    st.text(note or "Không có ghi chú lâm sàng.")
                with tabs[1]:
                    display_frame(repository.diagnoses(visit_id), "Không có chẩn đoán.")
                with tabs[2]:
                    display_frame(repository.medicines(visit_id), "Không có dữ liệu thuốc.")
                with tabs[3]:
                    display_frame(repository.procedures(visit_id), "Không có dữ liệu DVKT.")
                with tabs[4]:
                    display_frame(
                        repository.observations(visit_id),
                        "Không có dữ liệu xét nghiệm.",
                    )
    return selected


config = AppConfig.from_environment()
panel_height = int(os.environ.get("EXPERT_REVIEW_PANEL_HEIGHT", "720"))
try:
    retrieval_index, ehr_repository, review_store = load_services(config)
except Exception as exc:
    st.error("Không thể khởi tạo expert-review app.")
    st.exception(exc)
    st.stop()

st.title("🩺 Expert Review · Similar Cases")
st.caption(
    "Exact cosine trên fused embedding EHR graph + clinical note, "
    f"toàn bộ {len(retrieval_index.ids):,} lượt khám. Ảnh không tham gia retrieval."
)

header_left, header_right = st.columns([0.55, 0.45])
with header_left:
    reviewer_id = st.text_input(
        "Mã expert *",
        value=st.session_state.get("reviewer_id", ""),
        placeholder="Ví dụ: BS_001",
    )
    st.session_state.reviewer_id = reviewer_id
with header_right:
    st.metric("Số lượt review đã lưu", review_store.count())

if "active_query_id" not in st.session_state:
    default_query = os.environ.get("EXPERT_REVIEW_DEFAULT_QUERY", "")
    st.session_state.active_query_id = clean_id(default_query)

query_input = st.text_input(
    "Nhập Visit ID của ca query",
    value=st.session_state.active_query_id,
    placeholder="Ví dụ: 25.013029",
)
load_query = st.button("Tìm 20 ca liên quan nhất", type="primary")
if load_query:
    query_input = clean_id(query_input)
    if query_input not in retrieval_index:
        st.error("Visit ID không tồn tại trong giao của EHR và note embeddings.")
    elif not ehr_repository.has_visit(query_input):
        st.error("Visit ID có embedding nhưng không có trong bảng EHR.")
    else:
        st.session_state.active_query_id = query_input
        st.rerun()

query_id = clean_id(st.session_state.active_query_id)
if not query_id:
    st.info("Nhập một Visit ID để bắt đầu expert review.")
    st.stop()
if query_id not in retrieval_index or not ehr_repository.has_visit(query_id):
    st.warning("Query hiện tại không còn hợp lệ. Hãy nhập lại Visit ID.")
    st.stop()

results = retrieval_index.retrieve(query_id, k=config.top_k)
left, right = st.columns([0.38, 0.62], gap="large")

with left:
    with st.container(height=panel_height, border=True):
        st.subheader("Ca query")
        render_full_ehr(ehr_repository, query_id)

with right:
    with st.container(height=panel_height, border=True):
        st.subheader("Top 20 ca liên quan")
        st.caption("Tick các ca thực sự liên quan. Có thể chọn từ 1 đến 19 ca.")
        selected_ids: list[str] = []
        for result in results:
            if candidate_card(ehr_repository, query_id, result):
                selected_ids.append(result.candidate_visit_id)

        st.divider()
        no_relevant_case = st.checkbox(
            "Không có ca nào trong Top 20 đủ liên quan",
            key=f"none::{query_id}",
        )
        reviewer_note = st.text_area(
            "Ghi chú của expert",
            key=f"note::{query_id}",
            placeholder="Tiêu chí lựa chọn, nhận xét hoặc lý do không chọn…",
        )
        st.write(f"Đã chọn **{len(selected_ids)} / 20** ca.")
        if st.button("Submit ground truth", type="primary", width="stretch"):
            try:
                review_uuid = review_store.save_review(
                    reviewer_id=reviewer_id,
                    query_visit_id=query_id,
                    candidates=results,
                    selected_visit_ids=selected_ids,
                    no_relevant_case=no_relevant_case,
                    reviewer_note=reviewer_note,
                    retrieval_config=retrieval_index.config,
                    query_snapshot=ehr_repository.overview(query_id),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success(
                    f"Đã lưu ground truth: {len(selected_ids)} ca liên quan "
                    f"(review `{review_uuid}`)."
                )

with st.sidebar:
    st.subheader("Cấu hình")
    st.json(retrieval_index.config)
    st.caption(f"Database: {config.database_path}")
    st.subheader("Review gần đây")
    recent = review_store.recent_reviews(limit=10)
    if recent:
        st.dataframe(pd.DataFrame(recent), hide_index=True, width="stretch")
    else:
        st.caption("Chưa có review nào.")
