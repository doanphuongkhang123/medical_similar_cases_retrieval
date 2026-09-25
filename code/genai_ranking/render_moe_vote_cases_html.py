#!/usr/bin/env python3
"""Render ordered MoE retrieval cases without displaying ranking scores."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import socket

from common import sha256, write_json
from moe_vote_rank import QUERY_COUNT, TOP_K, read_json, read_jsonl, verify


HTML_NAME = "moe_vote_top20.html"
PSEUDONYM = re.compile(r"P\d{5}\Z")


def load_content(input_bundle: Path, ranking_manifest: dict, needed_ids: set[str]) -> tuple[dict[str, str], Path, dict]:
    input_manifest_path = input_bundle / "manifest.json"
    source = ranking_manifest["sources"]["input_bundle_manifest"]
    if input_manifest_path.resolve() != Path(source["path"]).resolve() or sha256(input_manifest_path) != source["sha256"]:
        raise ValueError("Patient content bundle differs from the ranking source")
    input_manifest = read_json(input_manifest_path)
    if (input_manifest.get("raw_input") != ranking_manifest["raw_input"] or
            input_manifest.get("raw_sha256") != ranking_manifest["raw_sha256"]):
        raise ValueError("Patient content raw lineage differs")
    input_path = input_bundle / input_manifest["output_file"]
    if sha256(input_path) != input_manifest["output_sha256"]:
        raise ValueError("Patient content SHA-256 mismatch")
    texts = {}
    seen = set()
    count = 0
    for row in read_jsonl(input_path):
        count += 1
        patient_id = row.get("patient_id")
        if not isinstance(patient_id, str) or not PSEUDONYM.fullmatch(patient_id) or patient_id in seen:
            raise ValueError("Patient content IDs are invalid")
        seen.add(patient_id)
        if patient_id in needed_ids:
            content = row.get("embedding_text")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Empty patient content for {patient_id}")
            texts[patient_id] = content
    if count != input_manifest["patients"] or set(texts) != needed_ids:
        raise ValueError("Patient content coverage is incomplete")
    return texts, input_path, input_manifest


def checked_inputs(results_root: Path, input_bundle: Path) -> tuple[list[dict], dict[str, str], dict, Path, dict]:
    verify(results_root)
    ranking_manifest = read_json(results_root / "manifest.json")
    rows = list(read_jsonl(results_root / "moe_vote_top20.jsonl"))
    if len(rows) != QUERY_COUNT:
        raise ValueError("Expected 50 query rankings")
    needed_ids = set()
    for row in rows:
        query_id = row["query_patient_id"]
        if not PSEUDONYM.fullmatch(query_id):
            raise ValueError("Query ID is not pseudonymized")
        needed_ids.add(query_id)
        candidates = row["top20"]
        if len(candidates) != TOP_K or [item["rank"] for item in candidates] != list(range(1, TOP_K + 1)):
            raise ValueError("Candidate ranking is incomplete")
        for item in candidates:
            patient_id = item["patient_id"]
            if not PSEUDONYM.fullmatch(patient_id):
                raise ValueError("Candidate ID is not pseudonymized")
            needed_ids.add(patient_id)
    texts, input_path, input_manifest = load_content(input_bundle, ranking_manifest, needed_ids)
    return rows, texts, ranking_manifest, input_path, input_manifest


def render(rows: list[dict], texts: dict[str, str]) -> str:
    options = ''.join(
        f'<option value="query-{index}">{escape(row["query_patient_id"])}</option>'
        for index, row in enumerate(rows)
    )
    panels = []
    for query_index, row in enumerate(rows):
        query_id = row["query_patient_id"]
        choices = []
        case_views = []
        for item in row["top20"]:
            rank = item["rank"]
            patient_id = item["patient_id"]
            active = ' active' if rank == 1 else ''
            hidden = '' if rank == 1 else ' hidden'
            choices.append(
                f'<button type="button" class="choice{active}" data-target="case-{query_index}-{rank}">'
                f'<span class="rank">{rank:02d}</span><strong>{escape(patient_id)}</strong></button>'
            )
            case_views.append(
                f'<article class="case" id="case-{query_index}-{rank}"{hidden}>'
                f'<span class="eyebrow">CANDIDATE #{rank:02d}</span>'
                f'<h2>{escape(patient_id)}</h2>'
                f'<pre>{escape(texts[patient_id])}</pre></article>'
            )
        panels.append(
            f'<section class="query-panel" id="query-{query_index}"'
            + ('' if query_index == 0 else ' hidden') + '>'
            '<div class="query-content"><span class="eyebrow">BỆNH NHÂN QUERY</span>'
            f'<h2>{escape(query_id)}</h2><pre>{escape(texts[query_id])}</pre></div>'
            '<div class="candidate-content"><div class="candidate-list">'
            + ''.join(choices) + '</div><div class="case-container">'
            + ''.join(case_views) + '</div></div></section>'
        )
    return f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MoE ranking · Nội dung Top 20</title>
<style>
:root{{--ink:#173027;--muted:#567066;--line:#d6e5db;--green:#176449;--paper:#f2f7f2}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{padding:26px max(22px,calc((100vw - 1500px)/2));background:#174d39;color:white}}header h1{{margin:4px 0;font-size:clamp(24px,3vw,36px)}}header p{{margin:4px 0 0;color:#d7ece0}}
main{{max-width:1540px;margin:auto;padding:22px 20px 42px}}.toolbar{{display:flex;gap:14px;align-items:center;margin-bottom:16px;flex-wrap:wrap}}
label{{font-weight:750}}select{{padding:9px 12px;border:1px solid #a7c0af;border-radius:9px;background:white;color:var(--ink);font:inherit;min-width:180px}}
.eyebrow{{font-size:11px;font-weight:850;letter-spacing:.12em;color:var(--green)}}.query-panel{{display:grid;grid-template-columns:minmax(280px,1fr) minmax(480px,1.6fr);gap:16px}}
[hidden]{{display:none!important}}.query-content,.candidate-content{{background:white;border:1px solid var(--line);border-radius:14px;box-shadow:0 5px 20px #284e3010}}
.query-content{{padding:22px;min-width:0}}h2{{font-size:25px;margin:5px 0 16px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;padding:16px;background:#f8faf7;border:1px solid #e5eee7;border-radius:10px}}
.candidate-content{{min-width:0;display:grid;grid-template-columns:205px minmax(0,1fr)}}.candidate-list{{padding:10px;border-right:1px solid var(--line);max-height:75vh;overflow:auto}}
.choice{{display:flex;align-items:center;gap:10px;width:100%;padding:10px 12px;margin-bottom:5px;text-align:left;border:1px solid transparent;border-radius:9px;background:#f5f8f4;color:var(--ink);cursor:pointer;font:inherit}}
.choice:hover,.choice.active{{background:#e4f1e7;border-color:#a6cfb2}}.choice .rank{{color:var(--green);font-weight:900;font-variant-numeric:tabular-nums}}.choice strong{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}}
.case-container{{padding:20px;min-width:0;max-height:75vh;overflow:auto}}.case h2{{margin-bottom:15px}}
@media(max-width:900px){{.query-panel{{grid-template-columns:1fr}}.candidate-content{{grid-template-columns:1fr}}.candidate-list{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;border-right:0;border-bottom:1px solid var(--line);max-height:230px}}.choice{{margin:0}}.case-container{{max-height:none}}}}
@media(max-width:600px){{main{{padding:14px 10px}}.query-content{{padding:16px}}.candidate-list{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body>
<header><h1>Top 20 bệnh nhân tương tự</h1><p>Chọn query và candidate để xem nội dung bệnh án theo thứ tự xếp hạng.</p></header>
<main><div class="toolbar"><label for="query-select">Bệnh nhân query</label><select id="query-select">{options}</select></div>
{''.join(panels)}</main>
<script>
const querySelect=document.getElementById('query-select');
querySelect.addEventListener('change',()=>{{
  document.querySelectorAll('.query-panel').forEach(panel=>panel.hidden=panel.id!==querySelect.value);
}});
document.querySelectorAll('.choice').forEach(button=>button.addEventListener('click',()=>{{
  const panel=button.closest('.candidate-content');
  panel.querySelectorAll('.choice').forEach(choice=>choice.classList.remove('active'));
  panel.querySelectorAll('.case').forEach(item=>item.hidden=true);
  button.classList.add('active');
  document.getElementById(button.dataset.target).hidden=false;
}}));
</script></body></html>'''


def run(results_root: Path, input_bundle: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    rows, texts, ranking_manifest, input_path, input_manifest = checked_inputs(results_root, input_bundle)
    output.mkdir(parents=True)
    html_path = output / HTML_NAME
    html_path.write_text(render(rows, texts), encoding="utf-8")
    report_manifest = {
        "schema_version": 1,
        "status": "complete_not_clinically_validated",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "query_count": QUERY_COUNT,
        "result_count": QUERY_COUNT * TOP_K,
        "raw_input": ranking_manifest["raw_input"],
        "raw_sha256": ranking_manifest["raw_sha256"],
        "ranking_manifest": str(results_root / "manifest.json"),
        "ranking_manifest_sha256": sha256(results_root / "manifest.json"),
        "patient_content_path": str(input_path),
        "patient_content_sha256": input_manifest["output_sha256"],
        "code_sha256": sha256(Path(__file__)),
        "contains_clinical_text": True,
        "raw_patient_id_fields_added": False,
        "similarity_scores_displayed": False,
        "outputs": {HTML_NAME: sha256(html_path)},
    }
    write_json(output / "manifest.json", report_manifest)
    print(json.dumps({"html": str(html_path), "queries": len(rows), "cases": len(rows) * TOP_K, "bytes": html_path.stat().st_size}))


def check_report(output: Path) -> None:
    manifest = read_json(output / "manifest.json")
    html_path = output / HTML_NAME
    if (manifest.get("query_count") != QUERY_COUNT or
            manifest.get("result_count") != QUERY_COUNT * TOP_K or
            manifest.get("contains_clinical_text") is not True or
            manifest.get("similarity_scores_displayed") is not False or
            sha256(html_path) != manifest["outputs"][HTML_NAME] or
            sha256(Path(manifest["ranking_manifest"])) != manifest["ranking_manifest_sha256"] or
            sha256(Path(manifest["patient_content_path"])) != manifest["patient_content_sha256"]):
        raise ValueError("Report manifest or source SHA-256 mismatch")
    page = html_path.read_text(encoding="utf-8")
    if (page.count('class="query-panel"') != QUERY_COUNT or
            page.count('class="choice') != QUERY_COUNT * TOP_K or
            page.count('class="case"') != QUERY_COUNT * TOP_K or
            any(label in page for label in ("cosine_similarity", "normalized_cosine", "vote_count", "rank TB"))):
        raise ValueError("Report content check failed")
    print(json.dumps({"status": "pass", "html": str(html_path), "queries": QUERY_COUNT, "cases": QUERY_COUNT * TOP_K}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--results-root", type=Path, required=True)
    run_parser.add_argument("--input-bundle", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args.results_root.resolve(), args.input_bundle.resolve(), args.output.resolve())
    else:
        check_report(args.output.resolve())


if __name__ == "__main__":
    main()
