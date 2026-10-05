#!/usr/bin/env python3
"""Package verified modality results; preserve ranking units and source scores."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import socket
from datetime import datetime, timezone

import numpy as np
import pandas as pd

RAW_SHA = '4d621a576164aef695f7349fa770b916216401632d93078d62639842da1ec899'
BUDGET = 64 * 1024 * 1024


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def checked_file(root, name, hashes):
    path = root / name
    expected = hashes[name]
    expected = expected['sha256'] if isinstance(expected, dict) else expected
    assert sha(path) == expected, f'Source fingerprint changed: {path}'
    return path


def validate(data):
    items = data['items']
    assert items and len({x['id'] for x in items}) == len(items)
    pairs = 0
    for i, item in enumerate(items):
        assert item['id'] and item['patient_id']
        assert len(item['neighbors']) <= 20
        seen = set()
        previous = None
        for hit in item['neighbors']:
            target, score = hit[:2]
            assert isinstance(target, int) and 0 <= target < len(items) and target != i
            assert target not in seen
            seen.add(target)
            assert items[target]['patient_id'] != item['patient_id']
            value = float(score)
            assert math.isfinite(value)
            assert -1.00001 <= value <= (2.00001 if data['metric'] == 'cosine_distance' else 1.00001)
            if previous is not None:
                assert value >= previous - 1e-12 if data['metric'] == 'cosine_distance' else value <= previous + 1e-12
            previous = value
            if data['id'] == 'biochemistry':
                assert hit[2] >= 3 and hit[3] >= .5
            pairs += 1
        if 'measurements' in item:
            assert len(item['measurements']) == len(data['features'])
            assert all(value is None or math.isfinite(value) for value in item['measurements'])
        for rid in item.get('report_ids', []):
            assert rid in data.get('reports', {})
        if item.get('report_ids'):
            assert item['metadata']['report_link_status'] == 'exact_order_reports'
    return pairs


def image_bundle(data_root, method, run_name, prefix, model, linkage):
    root = data_root / 'image_embedding_retrieval' / run_name
    manifest = json.loads((root / 'manifest.json').read_text())
    verification = json.loads((root / 'verification.json').read_text())
    assert verification['passed'] and manifest['config']['exclude_same_patient'] is True
    assert manifest['raw_input']['sha256'] == RAW_SHA
    detail = checked_file(root, prefix + '_embedding_top20.csv', manifest['files'])
    reports_path = root / 'structured/reports.parquet'
    recorded_report_hashes = []
    def report_hashes(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).endswith('reports.parquet'):
                    recorded_report_hashes.append(child.get('sha256') if isinstance(child, dict) else child)
                report_hashes(child)
        elif isinstance(value, list):
            for child in value:
                report_hashes(child)
    report_hashes(manifest)
    assert sha(reports_path) in recorded_report_hashes, 'Normalized report source hash changed'
    reports = pd.read_parquet(reports_path).fillna('')
    rows = list(csv.DictReader(detail.open(encoding='utf-8-sig')))
    lookup = {row['embedding_id']: i for i, row in enumerate(rows)}
    assert len(lookup) == len(rows)
    report_map = {str(row['report_id']): {key: str(row[key]) for key in ['report_id', 'visit_id', 'order_id', 'service_kind', 'MO_TA', 'KET_LUAN', 'GIA_TRI', 'report_note', 'result_datetime']} for row in reports.to_dict('records')}
    wanted = set()
    items = []
    for row in rows:
        ids = json.loads(row['report_ids_json'])
        if ids:
            assert row['report_link_status'] == 'exact_order_reports'
        wanted.update(ids)
        source_study = linkage.get((method.upper() if method != 'xray' else 'XQ', row['study_uid']))
        archives = []
        if source_study:
            for archive in json.loads(source_study['source_zips_json']):
                relative = Path(archive).relative_to(data_root / 'raw').as_posix()
                assert '..' not in Path(relative).parts
                archives.append(relative)
        metadata = {key: row.get(key, '') for key in ['study_uid', 'series_uid', 'accession_number', 'series_description', 'body_part_group', 'sequence', 'source_ehr_case_id', 'source_ehr_join_status', 'report_link_status', 'dicom_modality', 'auxiliary_xray_overlay']}
        hits = [[lookup[row[f'top{rank:02}_embedding_id']], row[f'top{rank:02}_cosine_similarity']] for rank in range(1, 21)]
        items.append(dict(id=row['embedding_id'], patient_id=row['patient_id'], label=f"{row['patient_id']} · {row.get('series_description') or row.get('sequence') or method.upper()} · {row['embedding_id']}", metadata=metadata, report_ids=ids, candidate_report_ids=json.loads(row['report_candidates_json']), archives=archives, neighbors=hits))
    data = dict(id=method, label={'ct': 'Ảnh CT', 'mri': 'Ảnh MRI', 'xray': 'Ảnh X-quang'}[method], model=model, unit='Bộ ảnh / embedding', metric='cosine_similarity', description='Top-20 gốc theo từng embedding; loại cùng bệnh nhân, giữ cả trường hợp chưa nối được report.', items=items, reports={rid: report_map[rid] for rid in sorted(wanted)}, features=[])
    data['provenance'] = {str(path): sha(path) for path in [root/'manifest.json', root/'verification.json', detail, reports_path]}
    # Replay each original CSV hit and its exact decimal score after packaging.
    for item, row in zip(items, rows):
        for rank, hit in enumerate(item['neighbors'], 1):
            assert items[hit[0]]['id'] == row[f'top{rank:02}_embedding_id']
            assert hit[1] == row[f'top{rank:02}_cosine_similarity']
    return data


def text_bundle(data_root):
    root = data_root / 'ehr/genai_ranking/qwen3_patient_retrieval_0_6b_v1'
    manifest = json.loads((root/'manifest.json').read_text())
    assert manifest['raw_sha256'] == RAW_SHA and manifest['model_id'] == 'Qwen/Qwen3-Embedding-0.6B'
    for name in manifest['outputs']:
        checked_file(root, name, manifest['outputs'])
    input_path = root/'input_bundle/embedding_inputs.jsonl'
    assert sha(input_path) == manifest['input_sha256']
    profile_root = root/'input_bundle/source_profiles'
    pm = json.loads((profile_root/'manifest.json').read_text())
    identity_path = checked_file(profile_root, 'identity_map.jsonl', pm['artifacts'])
    identities = {row['profile_id']: row for row in map(json.loads, identity_path.open())}
    rows = list(map(json.loads, input_path.open()))
    ids = json.loads((root/'patient_ids.json').read_text())
    assert ids == [row['patient_id'] for row in rows] and set(ids) == set(identities)
    documents = np.load(root/'document_embeddings.npy', allow_pickle=False)
    queries = np.load(root/'query_embeddings.npy', allow_pickle=False)
    assert documents.shape == queries.shape == (len(rows), manifest['embedding_dimension'])
    assert documents.dtype == queries.dtype == np.float32
    assert np.isfinite(documents).all() and np.isfinite(queries).all()
    assert np.allclose(np.linalg.norm(documents, axis=1), 1, atol=1e-4)
    assert np.allclose(np.linalg.norm(queries, axis=1), 1, atol=1e-4)
    items = []
    for i, row in enumerate(rows):
        # Exactly the existing Qwen demo contract: float32 documents @ instructed query.
        scores = documents @ queries[i]
        scores[i] = -np.inf
        selected = np.argpartition(-scores, 19)[:20]
        order = sorted(selected.tolist(), key=lambda j: (-float(scores[j]), ids[j]))
        identity = identities[row['patient_id']]
        items.append(dict(id=row['patient_id'], patient_id=identity['patient_id'], label=f"{row['patient_id']} · {identity['patient_id']}", metadata=dict(visit_count=row['visit_count'], visits=[v['visit_id'] for v in identity['visits']]), fields=[['Mô tả bệnh đưa vào model', row['embedding_text']]], neighbors=[[j, float(scores[j])] for j in order]))
    data = dict(id='text', label='Mô tả bệnh', model=manifest['model_id'], model_revision=manifest['model_revision'], unit='Bệnh nhân', metric='cosine_similarity', description='Qwen 0.6B: query có task instruction, candidate dùng document embedding; tối đa 3 lần nhập viện gần nhất.', items=items, features=[])
    data['provenance'] = {str(path): sha(path) for path in [root/'manifest.json', input_path, identity_path, root/'patient_ids.json', root/'document_embeddings.npy', root/'query_embeddings.npy']}
    return data


def biochemistry_bundle(data_root):
    root = data_root/'ehr/biochemistry_retrieval/neural39_20261004_v1'
    manifest = json.loads((root/'manifest.json').read_text())
    assert manifest['raw_input_sha256'] == RAW_SHA
    assert json.loads((root/'verification.json').read_text())['passed']
    baseline = Path(manifest['baseline_run'])
    bm = json.loads((baseline/'manifest.json').read_text())
    assert sha(baseline/'manifest.json') == manifest['baseline_manifest_sha256']
    index_path = checked_file(baseline, manifest['index_directory']+'/index.npz', bm['files'])
    feature_path = checked_file(root, 'features.json', manifest['files'])
    visits_path = checked_file(baseline, 'visits.parquet', bm['files'])
    neighbors_path = checked_file(root, 'seed_20261004/neighbors_neural.parquet', manifest['files'])
    index = np.load(index_path, allow_pickle=False)
    features = json.loads(feature_path.read_text())
    assert len(features) == 39
    visits = pd.read_parquet(visits_path).set_index('visit_id').to_dict('index')
    ids = index['visit_ids'].tolist()
    lookup = {key: i for i, key in enumerate(ids)}
    items = []
    for i, key in enumerate(ids):
        visit = visits[key]
        items.append(dict(id=key, patient_id=str(index['patient_ids'][i]), label=f"{index['patient_ids'][i]} · Bệnh án {key}", metadata={'admission': str(visit['admission']), 'discharge': str(visit['discharge']), 'observed_tests': int(np.isfinite(index['values'][i]).sum())}, measurements=[float(x) if np.isfinite(x) else None for x in index['values'][i]], neighbors=[]))
    neighbors = pd.read_parquet(neighbors_path)
    for row in neighbors.itertuples(index=False):
        hits = items[lookup[row.query_visit_id]]['neighbors']
        assert row.rank == len(hits)+1
        hits.append([lookup[row.candidate_visit_id], float(row.distance), int(row.shared_tests), float(row.query_coverage), float(row.jaccard)])
    data = dict(id='biochemistry', label='Xét nghiệm sinh hoá', model='Masked denoising autoencoder · 39 chỉ số · seed 20261004', unit='Bệnh án / lần nhập viện', metric='cosine_distance', description='Embedding 16 chiều; ít nhất 3 chỉ số chung và phủ 50% query. 12 nhãn đơn vị mới là suy luận chưa xác nhận.', items=items, features=features)
    data['provenance'] = {str(path): sha(path) for path in [root/'manifest.json', root/'verification.json', baseline/'manifest.json', index_path, feature_path, visits_path, neighbors_path]}
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = args.data_root.resolve()
    if args.verify_only:
        manifest = json.loads((args.output/'manifest.json').read_text())
        assert sha(Path(manifest['raw_input']['path'])) == manifest['raw_input']['sha256'] == RAW_SHA
        for path, expected in manifest['inputs'].items():
            assert sha(Path(path)) == expected
        for method in manifest['methods']:
            path = args.output/method['file']
            assert sha(path) == method['sha256']
            data = json.loads(path.read_text())
            assert validate(data) == method['pairs'] and len(data['items']) == method['items']
            for source, expected in data['provenance'].items():
                assert sha(Path(source)) == expected
        print(json.dumps({'output':str(args.output),'all_sources_and_outputs_verified':True}),flush=True)
        return
    assert not args.output.exists(), 'Refuse to overwrite a prepared bundle'
    raw = root/'raw/thông tin bệnh án.xlsx'
    assert sha(raw) == RAW_SHA
    link_path = root/'image_report_linkage/20261003_image_visit_csv_v4/study_visit_report_links.csv'
    lm_path = link_path.parent/'study_visit_report_links.manifest.json'
    lm = json.loads(lm_path.read_text())
    assert lm['verification']['passed'] and sha(link_path) == lm['csv_sha256']
    linkage = {(r['modality'], r['study_uid']): r for r in csv.DictReader(link_path.open(encoding='utf-8-sig'))}
    methods = [biochemistry_bundle(root), text_bundle(root)]
    methods += [image_bundle(root, *parameters, linkage) for parameters in [
        ('ct', 'ctclip_top20_20261005_v1', 'ct', 'CT-CLIP · 512-D'),
        ('mri', '3dino_mri_top20_study_20261004_v2', 'mri', '3DINO · 1024-D'),
        ('xray', 'xray_medsiglip_top20_20261004_v1', 'xray', 'MedSigLIP–PhoBERT fine-tuned · 768-D'),
    ]]
    plans = []
    for method in methods:
        pairs = validate(method)
        samples = method['items'][::max(1,len(method['items'])//100)]
        projected = len(encoded(samples))/len(samples)*len(method['items'])
        projected += len(encoded(method.get('reports',{}))) + len(encoded(method.get('features',[])))
        plans.append(dict(id=method['id'], items=len(method['items']), queries=sum(bool(x['neighbors']) for x in method['items']), pairs=pairs, estimated_bytes=math.ceil(projected*1.25)))
    planned = sum(p['estimated_bytes'] for p in plans)
    print(json.dumps({'planned_bytes': planned, 'budget_bytes': BUDGET, 'methods': plans}), flush=True)
    assert planned <= BUDGET, 'Redesign oversized bundle before exporting'
    args.output.mkdir(parents=True)
    manifest = dict(schema_version=1, host=socket.gethostname(), created_at=datetime.now(timezone.utc).isoformat(), raw_input={'path':str(raw),'sha256':RAW_SHA}, pipeline='modality_review_bundle_v1', inputs={str(link_path):sha(link_path),str(lm_path):sha(lm_path)}, methods=[], planned_bytes=planned, budget_bytes=BUDGET)
    actual = 0
    for method, plan in zip(methods,plans):
        filename = method['id']+'.json'
        payload = encoded(method)
        actual += len(payload)
        assert actual <= BUDGET
        path = args.output/filename
        path.write_bytes(payload)
        loaded = json.loads(path.read_text())
        assert loaded == method and validate(loaded) == plan['pairs']
        manifest['methods'].append({key: method[key] for key in ['id','label','model','unit','metric','description']} | plan | {'file':filename,'sha256':sha(path)})
    assert sha(raw) == RAW_SHA
    manifest['actual_bytes'] = actual
    manifest['verification'] = dict(passed=True, all_rows_readback_equal=True, all_rankings_preserved=True, no_same_patient_hits=True, finite_scores=True)
    manifest['code_sha256'] = sha(Path(__file__))
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'bytes':actual,'passed':True}),flush=True)


if __name__ == '__main__':
    main()
