#!/usr/bin/env python3
"""Create or verify a file-level SHA-256 manifest without reading clinical text."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('root', type=Path)
parser.add_argument('manifest', type=Path)
parser.add_argument('--verify', action='store_true')
args = parser.parse_args()
root = args.root.resolve()
paths = sorted(p for p in root.rglob('*') if p.is_file())
if any(p.is_symlink() for p in paths):
    raise SystemExit('Unexpected symlink in transfer dataset')
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
if args.verify:
    source = json.loads(args.manifest.read_text())
    expected = {row['path']: row for row in source['files']}
    actual = {str(p.relative_to(root)) for p in paths}
    if actual != expected.keys():
        raise SystemExit(f'File-set mismatch: missing={len(expected.keys()-actual)}, extra={len(actual-expected.keys())}')
    for index, p in enumerate(paths, 1):
        row = expected[str(p.relative_to(root))]
        if p.stat().st_size != row['bytes'] or digest(p) != row['sha256']:
            raise SystemExit('Size or SHA-256 mismatch: '+row['path'])
        if index % 250 == 0: print(f'verified {index}/{len(paths)}', flush=True)
    result = {'destination_host': os.uname().nodename, 'destination_path': str(root),
              'source_path': source['source_path'], 'source_manifest_sha256': digest(args.manifest),
              'files': len(paths), 'bytes': sum(p.stat().st_size for p in paths),
              'sha256_mismatches': 0, 'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    args.manifest.with_name('transfer_verified.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
else:
    rows = []
    for index, p in enumerate(paths, 1):
        rows.append({'path': str(p.relative_to(root)), 'bytes': p.stat().st_size, 'sha256': digest(p)})
        if index % 250 == 0: print(f'hashed {index}/{len(paths)}', flush=True)
    result = {'source_host': os.uname().nodename, 'source_path': str(root),
              'file_count': len(rows), 'bytes': sum(row['bytes'] for row in rows),
              'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'files': rows}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    temp = args.manifest.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    temp.replace(args.manifest)
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}), flush=True)
