#!/usr/bin/env python3
"""Re-encode the current CT cohort directly from source ZIPs into a new run."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import numpy as np
import pandas as pd

from geometry import RejectedSeries, canonical_json, read_series, resample, sha256

VERSION = 'ct-dicom-physical-ras-full-ctclip-v2.1'
DATA = Path('/mnt/disk4/similar_cases_retrieval/data')
DEFAULT_MANIFEST = DATA/'experiments/patient_fusion/input_manifests_v1/image_embedding_manifest.parquet'
DEFAULT_VISITS = DATA/'ehr/ehr_preprocessed/ehr_preprocessed_full/visits.parquet'
DEFAULT_CHECKPOINT = Path('/mnt/disk1/khangdp/ckpt/encoders/ct_clip/models/CT-CLIP-Related/CT-CLIP_v2.pt')
DEFAULT_REPO = Path('/mnt/disk1/khangdp/third_party/CT-CLIP')


def write_json(path, obj):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False))
    os.replace(temp, path)


def write_array(path, a):
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as stream:
        np.save(stream, a)
    os.replace(temp, path)


def gpu_state():
    return subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,memory.total,memory.free,utilization.gpu',
                                    '--format=csv,noheader'], text=True).strip()


def build_inventory(manifest, visits_path):
    tab = pd.read_parquet(manifest)
    tab = tab[tab.modality.eq('CT')]
    visits = pd.read_parquet(visits_path, columns=['patient_id', 'visit_id', 'admission_time', 'discharge_time'])
    visits['patient_id'] = visits.patient_id.astype(str)
    visits['visit_id'] = visits.visit_id.astype(str)
    grouped = {k: v for k, v in visits.groupby('patient_id')}
    rows = []
    for r in tab.itertuples():
        path = Path(r.embedding_path).with_name('meta.json')
        meta = json.loads(path.read_text())
        patient = str(r.patient_id)
        study_date = pd.to_datetime(meta.get('StudyDate'), format='%Y%m%d', errors='coerce')
        candidates = []
        if patient in grouped and pd.notna(study_date):
            v = grouped[patient]
            selected = v[(pd.to_datetime(v.admission_time) <= study_date) & (pd.to_datetime(v.discharge_time) >= study_date)]
            candidates = sorted(set(selected.visit_id))
        key = hashlib.sha256(canonical_json([patient, str(r.visit_id), meta['source_zip'], meta['StudyInstanceUID'], meta['SeriesInstanceUID']]).encode()).hexdigest()[:24]
        rows.append({'item_id': key, 'patient_id': patient, 'visit_id': str(r.visit_id),
                     'source_archive': meta['source_zip'], 'study_uid': meta['StudyInstanceUID'],
                     'series_uid': meta['SeriesInstanceUID'], 'legacy_embedding_path': str(r.embedding_path),
                     'source_metadata_path': str(path), 'source_metadata_sha256': sha256(path),
                     'join_status': 'matched' if candidates == [str(r.visit_id)] else 'ambiguous_or_unmatched',
                     'candidate_visit_ids': canonical_json(candidates)})
    result = pd.DataFrame(rows)
    if result.empty or result.item_id.duplicated().any():
        raise ValueError('Empty or duplicate source inventory')
    return result


def verify(root):
    records = [json.loads(p.read_text()) for p in sorted((root/'records').glob('*.json'))]
    inv = pd.read_parquet(root/'source_inventory.parquet')
    expected = set(inv.item_id)
    actual = {r['item_id'] for r in records}
    if expected != actual:
        raise ValueError(f'Incomplete: expected {len(expected)}, recorded {len(actual)}')
    matrix, info, errors = [], [], []
    for r in records:
        if r['status'] == 'failed':
            errors.append(r['item_id'])
        if r['status'] != 'success':
            continue
        path = Path(r['embedding_path'])
        a = np.load(path)
        if a.shape != (512,) or a.dtype != np.float32 or not np.isfinite(a).all() or np.linalg.norm(a) == 0:
            raise ValueError(f'Invalid vector: {path}')
        if sha256(path) != r['embedding_sha256']:
            raise ValueError(f'Embedding hash mismatch: {path}')
        if not r.get('source_archive_sha256') or not r.get('input_sha256'):
            raise ValueError('Missing raw/input lineage')
        matrix.append(a); info.append(r)
    if not matrix:
        raise ValueError('No successful CT embeddings')
    x = np.stack(matrix).astype(np.float64)
    norms = np.linalg.norm(x, axis=1); z = x/norms[:, None]
    nearest = []
    if len(x) > 1:
        for start in range(0, len(x), 128):
            sim = z[start:start+128] @ z.T
            sim[np.arange(len(sim)), np.arange(start, start+len(sim))] = -np.inf
            nearest.extend(sim.max(1).tolist())
    hashes = [hashlib.sha256(v.astype(np.float32).tobytes()).hexdigest() for v in x]
    table = pd.DataFrame(info)
    table['vector_sha256'] = hashes
    table['embedding_norm'] = norms
    table.to_parquet(root/'ct_embedding_manifest.parquet', index=False)
    # Dedupe only within a visit and only after original HU + geometry agree.
    unique = table.drop_duplicates(['patient_id','visit_id','hu_geometry_sha256']).copy()
    unique = unique[unique.join_status.eq('matched')]
    unique.to_parquet(root/'ct_embedding_manifest_deduplicated.parquet', index=False)
    rng = np.random.default_rng(20260905)
    if len(x) > 1:
        a=rng.integers(len(x),size=20000);b=rng.integers(len(x)-1,size=20000);b+=b>=a
        random_cos = np.einsum('ij,ij->i', z[a], z[b])
        random_stats = dict(zip(['p01','median','p99'], np.quantile(random_cos,[.01,.5,.99]).tolist()))
    else:
        random_stats = None
    report = {'host': socket.gethostname(), 'expected_rows':len(inv), 'recorded_rows':len(records),
              'status_counts':pd.Series([r['status'] for r in records]).value_counts().to_dict(),
              'success_rows':len(info), 'deduplicated_matched_rows':len(unique), 'failed_items':errors,
              'shape':[len(x),512], 'finite':True, 'nonzero':True,
              'raw_projection_norm_min_median_max':np.quantile(norms,[0,.5,1]).tolist(),
              'unique_vectors':len(set(hashes)), 'random_pair_cosine':random_stats,
              'nearest_cosine_median':float(np.median(nearest)) if nearest else None,
              'verification_passed':not errors, 'clinical_quality_validated':False}
    write_json(root/'verification.json',report)
    print(json.dumps(report),flush=True)
    if errors:
        raise ValueError(f'{len(errors)} series failed; see individual records')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--source-manifest',type=Path,default=DEFAULT_MANIFEST)
    parser.add_argument('--visits',type=Path,default=DEFAULT_VISITS)
    parser.add_argument('--checkpoint',type=Path,default=DEFAULT_CHECKPOINT)
    parser.add_argument('--model-repo',type=Path,default=DEFAULT_REPO)
    parser.add_argument('--mode',choices=['inventory','run','verify'],default='run')
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--smoke-items',type=int,default=6)
    args=parser.parse_args()
    root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=True)
    lock=(root/'run.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.mode=='verify':
        verify(root);return
    config={'version':VERSION,'source_manifest':str(args.source_manifest.resolve()),
            'source_manifest_sha256':sha256(args.source_manifest),'visits_sha256':sha256(args.visits),
            'checkpoint_path':str(args.checkpoint.resolve()),'checkpoint_sha256':sha256(args.checkpoint),
            'script_sha256':{p.name:sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
            'smoke':args.smoke,'smoke_items':args.smoke_items if args.smoke else None,
            'geometry_policy':'physical slice sort; affine RAS; fixed centered grid; reject nonuniform/mixed stacks',
            'shape_zxy':[240,480,480],'spacing_xyz':[.75,.75,1.5],
            'hu_window':[-1000,1000],'normalized':False}
    if (root/'config.json').exists():
        if json.loads((root/'config.json').read_text()) != config:
            raise ValueError('Refusing resume after source/code/checkpoint/config change')
    else:
        write_json(root/'config.json',config)
    inventory_path=root/'source_inventory.parquet'
    if not inventory_path.exists():
        inv=build_inventory(args.source_manifest,args.visits)
        if args.smoke:
            # Cover distant rows in source order, deterministic and patient-diverse.
            pool=inv.drop_duplicates('patient_id').reset_index(drop=True)
            inv=pool.iloc[np.linspace(0,len(pool)-1,args.smoke_items,dtype=int)].copy()
        inv.to_parquet(inventory_path,index=False)
        write_json(root/'inventory_manifest.json',{'path':str(inventory_path),'sha256':sha256(inventory_path),'rows':len(inv)})
    inv=pd.read_parquet(inventory_path)
    if sha256(inventory_path)!=json.loads((root/'inventory_manifest.json').read_text())['sha256']:
        raise ValueError('Inventory changed')
    if args.mode=='inventory':
        print('INVENTORY',len(inv),str(root),flush=True);return
    import torch
    from encoder import Encoder
    torch.set_num_threads(2)
    torch.backends.cudnn.enabled=False
    torch.backends.cuda.matmul.allow_tf32=False
    print('GPU_BEFORE_MODEL',gpu_state(),flush=True)
    model=Encoder(args.checkpoint,args.model_repo)
    write_json(root/'model_manifest.json',model.manifest)
    (root/'records').mkdir(exist_ok=True);(root/'embeddings').mkdir(exist_ok=True)
    archive_hashes={};duplicates={};failures=0
    for record in sorted((root/'records').glob('*.json')):
        r=json.loads(record.read_text())
        if r['status']=='success':
            if sha256(Path(r['embedding_path'])) != r['embedding_sha256']:
                raise ValueError('Resume artifact hash mismatch')
            duplicates[r['input_sha256']]=r
    start=time.time()
    for i,item in enumerate(inv.to_dict('records'),1):
        destination=root/'records'/(item['item_id']+'.json')
        archive=Path(item['source_archive'])
        stat=archive.stat();signature=(stat.st_size,stat.st_mtime_ns)
        if archive not in archive_hashes:
            archive_hashes[archive]=(signature,sha256(archive))
        elif archive_hashes[archive][0]!=signature:
            raise RuntimeError('Raw archive changed while running')
        archive_digest=archive_hashes[archive][1]
        if destination.exists():
            previous=json.loads(destination.read_text())
            if previous['source_archive_sha256'] != archive_digest:
                raise RuntimeError('Raw archive changed since previous run')
            if previous['status']=='failed':
                raise RuntimeError('Refusing automatic retry of failed series; use new run after review')
            print(f'RESUME {i}/{len(inv)}',flush=True);continue
        record={**item,'source_archive_sha256':archive_digest,'code_version':VERSION,
                'checkpoint_sha256':config['checkpoint_sha256'],
                'created_utc':pd.Timestamp.now(tz='UTC').isoformat()}
        try:
            hu,affine,meta=read_series(archive,item['series_uid'],item['study_uid'])
            if meta['dicom_patient_id'] != item['patient_id']:
                raise RejectedSeries('dicom_patient_and_cohort_disagree')
            volume,pre=resample(hu,affine);del hu
            record.update(meta);record.update(pre)
            if pre['input_sha256'] in duplicates:
                other=duplicates[pre['input_sha256']]
                record.update(status='success',embedding_path=other['embedding_path'],
                              embedding_sha256=other['embedding_sha256'],embedding_dim=512,embedding_dtype='float32',
                              reuse_from_item=other['item_id'],embedding_norm=other['embedding_norm'])
            else:
                vector,diagnostics=model(volume,check_vq=args.smoke)
                path=root/'embeddings'/(item['item_id']+'.npy')
                write_array(path,vector)
                record.update(diagnostics)
                record.update(status='success',embedding_path=str(path),embedding_sha256=sha256(path),
                              embedding_dim=512,embedding_dtype='float32',reuse_from_item='')
                duplicates[pre['input_sha256']]=record
            del volume
        except RejectedSeries as e:
            record.update(status='skipped',reason=str(e))
        except Exception as e:
            record.update(status='failed',reason=type(e).__name__+':'+str(e))
            write_json(destination,record)
            # Never retry actual OOM. Nonzero exit is preserved by the launcher.
            if isinstance(e,torch.cuda.OutOfMemoryError):
                print('OOM',gpu_state(),flush=True);raise
            failures+=1
        write_json(destination,record)
        write_json(root/'progress.json',{'last_item':i,'total':len(inv),'elapsed_seconds':time.time()-start,
                                       'failed_this_process':failures,'last_status':record['status'],
                                       'updated_utc':pd.Timestamp.now(tz='UTC').isoformat()})
        print(f'ITEM {i}/{len(inv)} status={record["status"]} reason={record.get("reason", "")} elapsed={time.time()-start:.1f}',flush=True)
    verify(root)


if __name__=='__main__':
    main()
