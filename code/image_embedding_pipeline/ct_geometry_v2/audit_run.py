#!/usr/bin/env python3
"""Finalize source/output lineage and compare new/old CT embedding geometry."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from geometry import sha256
from run import write_json


def describe(x):
    x=np.asarray(x,dtype=np.float64)
    z=x/np.linalg.norm(x,axis=1,keepdims=True)
    rng=np.random.default_rng(20260905)
    sample=z[rng.choice(len(z),min(512,len(z)),replace=False)]
    centered=sample-sample.mean(0)
    ev=np.maximum(np.linalg.eigvalsh(centered@centered.T),0)
    p=ev[ev>1e-14]/ev.sum() if ev.sum()>0 else np.array([])
    a=rng.integers(len(x),size=20000);b=rng.integers(len(x)-1,size=20000);b+=b>=a
    similarities=np.einsum('ij,ij->i',z[a],z[b])
    return {'rows':len(x),'mean_direction_norm':float(np.linalg.norm(z.mean(0))),
            'centered_effective_rank_sample512':float(np.exp(-(p*np.log(p)).sum())) if len(p) else 0.,
            'random_pair_cosine_p01_median_p99':np.quantile(similarities,[.01,.5,.99]).tolist()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_root',type=Path)
    args=parser.parse_args();root=args.output_root
    config=json.loads((root/'config.json').read_text())
    records=[json.loads(p.read_text()) for p in (root/'records').glob('*.json')]
    inv=pd.read_parquet(root/'source_inventory.parquet').set_index('item_id')
    assert set(inv.index)=={r['item_id'] for r in records}
    archives={}
    for r in records:
        row=inv.loc[r['item_id']]
        for key in ['patient_id','visit_id','source_archive','series_uid','study_uid','join_status']:
            assert str(r[key])==str(row[key]),(r['item_id'],key)
        assert len(r['source_archive_sha256'])==64
        prior=archives.setdefault(r['source_archive'],r['source_archive_sha256'])
        assert prior==r['source_archive_sha256']
    # Hashes were calculated by the streaming encoder; preserve original archive
    # path/digest in a dedicated file without rereading all archives a second time.
    write_json(root/'raw_archive_manifest.json',archives)
    tab=pd.read_parquet(root/'ct_embedding_manifest.parquet')
    new=np.stack([np.load(p) for p in tab.embedding_path])
    old=np.stack([np.load(p) for p in tab.legacy_embedding_path])
    if len(new)>1:
        comparison={'new':describe(new),'old_same_source_rows':describe(old)}
    else:
        comparison={'rows':len(new),'reason':'too_few_rows_for_pairwise_comparison'}
    comparison['scope']='same successful source rows; engineering statistics, not clinical retrieval validation'
    comparison['skipped_reason_counts']=pd.Series([r.get('reason','') for r in records if r['status']=='skipped']).value_counts().to_dict()
    comparison['padding_fraction_quantiles']=np.quantile(tab.padding_fraction,[0,.5,.95,1]).tolist()
    comparison['ambiguous_or_unmatched_success_rows']=int(tab.join_status.ne('matched').sum())
    comparison['duplicate_groups_with_different_hu_inputs']=sum(g.hu_geometry_sha256.nunique()>1 for _,g in tab.groupby('vector_sha256') if len(g)>1)
    comparison['max_peak_allocated_bytes']=max(r.get('peak_allocated_bytes',0) for r in records)
    comparison['max_peak_reserved_bytes']=max(r.get('peak_reserved_bytes',0) for r in records)
    write_json(root/'quality_comparison.json',comparison)
    manifest={'config':config,'model':json.loads((root/'model_manifest.json').read_text()),
              'status':'verified' if json.loads((root/'verification.json').read_text())['verification_passed'] else 'failed',
              'source_archives':len(archives), 'source_records':len(records),
              'output_sha256':{p.name:sha256(p) for p in root.iterdir() if p.is_file() and p.suffix in ('.json','.parquet') and p.name!='run_manifest.json'},
              'individual_records_sha256':{p.name:sha256(p) for p in (root/'records').glob('*.json')}}
    write_json(root/'run_manifest.json',manifest)
    print(json.dumps(comparison),flush=True)


if __name__=='__main__':main()
