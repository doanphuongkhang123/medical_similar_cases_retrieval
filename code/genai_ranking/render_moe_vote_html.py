#!/usr/bin/env python3
"""Render a de-identified, self-contained HTML review of 50 voting rankings."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import math
from pathlib import Path
import re
import socket

from common import sha256, write_json
from moe_vote_rank import MODELS, QUERY_COUNT, TOP_K, read_json, read_jsonl, verify


HTML_NAME = "moe_vote_top20.html"
MODEL_LABELS = {"fusion": "Model retrieval", "openai": "OpenAI", "qwen3": "Qwen3"}
PSEUDONYM = re.compile(r"P\d{5}\Z")


def checked_rows(results_root: Path) -> tuple[list[dict], dict]:
    verify(results_root)
    manifest = read_json(results_root / "manifest.json")
    rows = list(read_jsonl(results_root / "moe_vote_top20.jsonl"))
    if len(rows) != QUERY_COUNT:
        raise ValueError("Expected 50 queries")
    for row in rows:
        if not PSEUDONYM.fullmatch(row["query_patient_id"]):
            raise ValueError("Query ID is not pseudonymized")
        if len(row["top20"]) != TOP_K:
            raise ValueError("Expected 20 results per query")
        for item in row["top20"]:
            if not PSEUDONYM.fullmatch(item["patient_id"]):
                raise ValueError("Candidate ID is not pseudonymized")
            if set(item["model_scores"]) - set(MODELS):
                raise ValueError("Unexpected model in ranking")
            for value in item["model_scores"].values():
                if any(not math.isfinite(value[key]) for key in ("cosine_similarity", "normalized_cosine")):
                    raise ValueError("Non-finite score")
    return rows, manifest


def score_cell(item: dict, model: str) -> str:
    value = item["model_scores"].get(model)
    if value is None:
        return '<td class="score-cell absent"><span class="dash">—</span></td>'
    return (
        '<td class="score-cell">'
        f'<span class="source-rank">#{value["rank"]}</span>'
        f'<span class="score-line">cos <strong>{value["cosine_similarity"]:.4f}</strong></span>'
        f'<span class="score-line">chuẩn hóa <strong>{value["normalized_cosine"]:.3f}</strong></span>'
        '</td>'
    )


def render(rows: list[dict]) -> str:
    total_votes = Counter(item["vote_count"] for row in rows for item in row["top20"])
    options = ''.join(
        f'<option value="query-{index}">{escape(row["query_patient_id"])}</option>'
        for index, row in enumerate(rows)
    )
    sections = []
    for index, row in enumerate(rows):
        query_id = escape(row["query_patient_id"])
        counts = Counter(item["vote_count"] for item in row["top20"])
        table_rows = []
        for item in row["top20"]:
            patient_id = escape(item["patient_id"])
            votes = item["vote_count"]
            mean_rank = item["mean_source_rank"]
            # A one-vote candidate is ordered by normalized cosine; show that value prominently.
            priority = (
                f'{next(iter(item["model_scores"].values()))["normalized_cosine"]:.3f}'
                if votes == 1 else f'{mean_rank:.2f}'
            )
            priority_label = "cos chuẩn hóa" if votes == 1 else "rank TB"
            table_rows.append(
                f'<tr data-candidate="{patient_id}">'
                f'<td class="result-rank">{item["rank"]:02d}</td>'
                f'<td class="patient-id">{patient_id}</td>'
                f'<td><span class="vote vote-{votes}">{votes}/3 vote</span></td>'
                f'<td class="priority"><span>{priority_label}</span><strong>{priority}</strong></td>'
                + ''.join(score_cell(item, model) for model in MODELS)
                + '</tr>'
            )
        sections.append(
            f'<section class="query-panel" id="query-{index}" data-query="{query_id}"'
            + ('' if index == 0 else ' hidden') + '>'
            '<div class="panel-head">'
            f'<div><span class="eyebrow">QUERY {index + 1:02d} / {len(rows):02d}</span>'
            f'<h2>{query_id}</h2></div>'
            f'<div class="query-counts"><span class="vote vote-3">{counts[3]} × 3 vote</span>'
            f'<span class="vote vote-2">{counts[2]} × 2 vote</span>'
            f'<span class="vote vote-1">{counts[1]} × 1 vote</span></div>'
            '</div>'
            '<div class="table-wrap"><table><thead><tr>'
            '<th>#</th><th>Candidate</th><th>Overlap</th><th>Tiêu chí xếp</th>'
            + ''.join(f'<th>{escape(MODEL_LABELS[model])}</th>' for model in MODELS)
            + '</tr></thead><tbody>' + ''.join(table_rows) + '</tbody></table></div>'
            '<p class="empty" hidden>Không có candidate khớp bộ lọc.</p>'
            '</section>'
        )
    return f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MoE voting · Top 20 của 50 query</title>
<style>
:root{{--ink:#15261f;--muted:#587063;--line:#d9e4dc;--green:#12684c;--paper:#f5f8f3;--white:#fff;--amber:#a05b05;--violet:#6945a5}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{padding:32px max(24px,calc((100vw - 1440px)/2));background:linear-gradient(120deg,#123f31,#1b7152);color:#fff}}
.eyebrow{{font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase;opacity:.78}}h1{{font-size:clamp(26px,4vw,42px);line-height:1.12;margin:8px 0}}header p{{max-width:920px;margin:8px 0 0;color:#deeee3}}
.summary{{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}}.summary span{{background:#ffffff21;border:1px solid #ffffff3d;border-radius:10px;padding:7px 12px;font-weight:700}}
main{{max-width:1490px;margin:auto;padding:25px 24px 50px}}.controls{{display:flex;align-items:end;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
label{{display:grid;gap:5px;font-size:12px;font-weight:800;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}}
select,input{{font:inherit;color:var(--ink);background:white;border:1px solid #b8cbbb;border-radius:10px;padding:10px 12px;min-width:220px}}
input{{min-width:280px}}.hint{{color:var(--muted);font-size:13px;margin:0 0 18px}}
.query-panel{{background:var(--white);border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:0 6px 22px #1b4e2a0d}}
.query-panel[hidden],tr[hidden],.empty[hidden]{{display:none}}.panel-head{{display:flex;justify-content:space-between;align-items:end;gap:20px;padding:21px 24px;border-bottom:1px solid var(--line)}}
h2{{font-size:29px;margin:2px 0 0;letter-spacing:.01em}}.query-counts{{display:flex;gap:7px;flex-wrap:wrap}}
.vote{{display:inline-block;white-space:nowrap;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800}}
.vote-3{{background:#e9e0f7;color:var(--violet)}}.vote-2{{background:#fff0d7;color:var(--amber)}}.vote-1{{background:#e7f2eb;color:var(--green)}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:900px}}th{{text-align:left;background:#f3f7f3;color:#53685b;font-size:11px;letter-spacing:.07em;text-transform:uppercase;white-space:nowrap}}
th,td{{padding:12px 14px;border-bottom:1px solid #e6eee8;vertical-align:middle}}tbody tr:hover{{background:#f8fbf7}}tbody tr:last-child td{{border-bottom:0}}
.result-rank{{color:var(--green);font-weight:900;font-variant-numeric:tabular-nums}}.patient-id{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:800}}
.priority span,.score-line{{display:block;color:var(--muted);font-size:11px}}.priority strong{{font-variant-numeric:tabular-nums}}.score-cell{{min-width:135px;font-variant-numeric:tabular-nums}}
.source-rank{{font-size:12px;font-weight:900;color:var(--green)}}.score-line strong{{color:var(--ink)}}.dash{{color:#a9bbb0}}.empty{{padding:20px;color:var(--muted)}}
.footnote{{color:var(--muted);font-size:12px;margin-top:18px}}
@media(max-width:700px){{header{{padding:27px 18px}}main{{padding:18px 12px}}.panel-head{{padding:17px;align-items:start;flex-direction:column}}select,input{{min-width:100%}}.controls label{{width:100%}}}}
</style></head><body>
<header><span class="eyebrow">Patient retrieval · voting ensemble</span><h1>Top 20 từ ba model</h1>
<p>Mỗi model đề cử 20 candidate theo cosine. Nhiều vote đứng trước; cùng 2 hoặc 3 vote xếp theo rank trung bình. Candidate 1 vote được fill theo cosine min–max trong Top 20 của model đó.</p>
<div class="summary"><span>{len(rows)} query</span><span>{len(rows)*TOP_K} kết quả</span><span>{total_votes[3]} candidate 3 vote</span><span>{total_votes[2]} candidate 2 vote</span><span>{total_votes[1]} candidate 1 vote</span></div></header>
<main><div class="controls"><label>Chọn query<select id="query-select">{options}</select></label>
<label>Lọc candidate trong query<input id="candidate-filter" type="search" placeholder="Ví dụ P01234" autocomplete="off"></label></div>
<p class="hint">Dấu — nghĩa là model không chọn candidate đó. Cosine gốc và cosine chuẩn hóa được giữ riêng để đối chiếu. Chỉ có ID giả danh và điểm số trong report này.</p>
{''.join(sections)}
<p class="footnote">Kết quả từ embedding retrieval; chưa được xác nhận về độ phù hợp lâm sàng.</p></main>
<script>
const select=document.getElementById('query-select');
const filter=document.getElementById('candidate-filter');
function refresh(){{
  document.querySelectorAll('.query-panel').forEach(panel=>{{
    panel.hidden=panel.id!==select.value;
    if(panel.hidden)return;
    const needle=filter.value.trim().toUpperCase();
    let shown=0;
    panel.querySelectorAll('tbody tr').forEach(row=>{{
      row.hidden=Boolean(needle)&&!row.dataset.candidate.toUpperCase().includes(needle);
      if(!row.hidden)shown++;
    }});
    panel.querySelector('.empty').hidden=shown!==0;
  }});
}}
select.addEventListener('change',()=>{{filter.value='';refresh()}});
filter.addEventListener('input',refresh);
</script></body></html>'''


def run(results_root: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"Choose a new report directory: {output}")
    rows, source_manifest = checked_rows(results_root)
    page = render(rows)
    output.mkdir(parents=True)
    html_path = output / HTML_NAME
    html_path.write_text(page, encoding="utf-8")
    report_manifest = {
        "schema_version": 1,
        "status": "complete_not_clinically_validated",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "query_count": QUERY_COUNT,
        "result_count": QUERY_COUNT * TOP_K,
        "raw_input": source_manifest["raw_input"],
        "raw_sha256": source_manifest["raw_sha256"],
        "ranking_manifest": str(results_root / "manifest.json"),
        "ranking_manifest_sha256": sha256(results_root / "manifest.json"),
        "ranking_jsonl_sha256": source_manifest["outputs"]["moe_vote_top20.jsonl"],
        "code_sha256": sha256(Path(__file__)),
        "contains_clinical_text": False,
        "contains_raw_patient_ids": False,
        "outputs": {HTML_NAME: sha256(html_path)},
    }
    write_json(output / "manifest.json", report_manifest)
    print(json.dumps({"html": str(html_path), "bytes": html_path.stat().st_size, "queries": len(rows)}))


def check_report(output: Path) -> None:
    manifest = read_json(output / "manifest.json")
    html_path = output / HTML_NAME
    if (manifest.get("query_count") != QUERY_COUNT or
            manifest.get("result_count") != QUERY_COUNT * TOP_K or
            manifest.get("contains_clinical_text") is not False or
            manifest.get("contains_raw_patient_ids") is not False or
            sha256(html_path) != manifest["outputs"][HTML_NAME] or
            sha256(Path(manifest["ranking_manifest"])) != manifest["ranking_manifest_sha256"]):
        raise ValueError("HTML report manifest mismatch")
    page = html_path.read_text(encoding="utf-8")
    if (page.count('class="query-panel"') != QUERY_COUNT or
            page.count('data-candidate="') != QUERY_COUNT * TOP_K or
            "embedding_text" in page or "SoVaoVien" in page):
        raise ValueError("HTML report content check failed")
    print(json.dumps({"status": "pass", "html": str(html_path), "queries": QUERY_COUNT, "rows": QUERY_COUNT * TOP_K}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--results-root", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args.results_root.resolve(), args.output.resolve())
    else:
        check_report(args.output.resolve())


if __name__ == "__main__":
    main()
