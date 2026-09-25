"""Conservative lexical overlap highlights for paired patient case text.

These marks describe literal overlap in the input, not why a retrieval model
ranked a candidate or whether two cases are clinically equivalent.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
import re
import unicodedata


FIELD_RE = re.compile(
    r"(?m)^(ICD chính|ICD phụ|Chẩn đoán ra viện|Tóm tắt bệnh án): (.*)$"
)
ICD_RE = re.compile(r"(?<![\w])(?:[A-TV-Z]|U)[0-9]{2}(?:\.[A-Z0-9]{1,4})?(?![\w])", re.I)
WORD_RE = re.compile(r"\w+", re.UNICODE)
NEGATORS = {"không", "chưa", "chẳng", "chả", "phủ", "âm"}
GENERIC = {
    "bệnh", "nhân", "vào", "ra", "viện", "được", "theo", "dõi", "điều", "trị",
    "khám", "lần", "tình", "trạng", "với", "và", "các", "của", "trong", "sau",
    "trước", "này", "đã", "có", "bị", "không", "chưa", "ngày", "tháng", "năm",
    "khi", "tại", "từ", "đến", "là", "do", "cho", "thấy", "ghi", "nhận",
}
KIND_CLASS = {"icd": "match-icd", "diagnosis": "match-diagnosis", "summary": "match-summary"}
KIND_TITLE = {
    "icd": "ICD trùng chính xác",
    "diagnosis": "Cụm chẩn đoán trùng",
    "summary": "Cụm từ tóm tắt trùng",
}


def _norm(token: str) -> str:
    return unicodedata.normalize("NFC", token).casefold()


def _fields(text: str, names: set[str]):
    for match in FIELD_RE.finditer(text):
        if match.group(1) in names:
            yield match.group(2), match.start(2)


def _icd_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    found: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for value, offset in _fields(text, {"ICD chính", "ICD phụ"}):
        for match in ICD_RE.finditer(value):
            found[match.group().upper()].append((offset + match.start(), offset + match.end()))
    return found


def _phrases(text: str, field_name: str, min_words: int, max_words: int, min_chars: int, min_content_words: int):
    found: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for value, offset in _fields(text, {field_name}):
        tokens = list(WORD_RE.finditer(value))
        runs = []
        current = []
        for token in tokens:
            if current and not value[current[-1].end():token.start()].isspace():
                runs.append(current)
                current = []
            current.append(token)
        if current:
            runs.append(current)
        for run in runs:
            words = [_norm(token.group()) for token in run]
            for start in range(len(run)):
                for size in range(min_words, min(max_words, len(run) - start) + 1):
                    end = start + size
                    phrase = tuple(words[start:end])
                    if sum(word not in GENERIC and not word.isdigit() for word in phrase) < min_content_words:
                        continue
                    left, right = run[start].start(), run[end - 1].end()
                    if right - left < min_chars:
                        continue
                    if field_name == "Tóm tắt bệnh án" and any(word in NEGATORS for word in words[:end]):
                        # Skip a negated clause altogether; a literal substring
                        # after "không" must not be called a positive match.
                        continue
                    found[phrase].append((offset + left, offset + right))
    return found


def _shared_intervals(query_map, candidate_map, kind: str):
    query_intervals, candidate_intervals = [], []
    for key in query_map.keys() & candidate_map.keys():
        query_intervals.extend((left, right, kind) for left, right in query_map[key])
        candidate_intervals.extend((left, right, kind) for left, right in candidate_map[key])
    return query_intervals, candidate_intervals


def _nonoverlapping(intervals: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    priority = {"icd": 0, "diagnosis": 1, "summary": 2}
    chosen = []
    for left, right, kind in sorted(intervals, key=lambda value: (
        priority[value[2]], -(value[1] - value[0]), value[0]
    )):
        if all(right <= other_left or left >= other_right for other_left, other_right, _ in chosen):
            chosen.append((left, right, kind))
    return sorted(chosen)


def matched_spans(query_text: str, candidate_text: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    query, candidate = [], []
    rules = (
        (_icd_spans, "icd"),
        (lambda text: _phrases(text, "Chẩn đoán ra viện", 2, 6, 8, 1), "diagnosis"),
        (lambda text: _phrases(text, "Tóm tắt bệnh án", 2, 6, 6, 2), "summary"),
    )
    for extract, kind in rules:
        query_spans, candidate_spans = _shared_intervals(extract(query_text), extract(candidate_text), kind)
        query.extend(query_spans)
        candidate.extend(candidate_spans)
    return _nonoverlapping(query), _nonoverlapping(candidate)


def marked_html(text: str, spans: list[tuple[int, int, str]]) -> str:
    parts = []
    position = 0
    for left, right, kind in spans:
        if not position <= left < right <= len(text):
            raise ValueError("Invalid or overlapping highlight spans")
        parts.append(escape(text[position:left]))
        parts.append(
            f'<mark class="{KIND_CLASS[kind]}" title="{KIND_TITLE[kind]}">'
            f'{escape(text[left:right])}</mark>'
        )
        position = right
    parts.append(escape(text[position:]))
    return "".join(parts)
