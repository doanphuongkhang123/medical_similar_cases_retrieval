#!/usr/bin/env python3
"""Verify the owned transfer and complete dataset checks exactly once."""
import datetime
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path
root = Path('/data/khangdp/scr/verify_web')
status = root/'transfers/compressed/status.json'
output = root/'logs/deployment_verification.json'
lock = (root/'logs/finalize.lock').open('w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
if output.exists() and json.loads(output.read_text()).get('stage') == 'verified':
    raise SystemExit('Dataset already verified; refusing to duplicate the finalizer')
state = {'pid': os.getpid(), 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
def update(stage, **fields):
    state.update(stage=stage, **fields, updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    temp = output.with_suffix('.tmp'); temp.write_text(json.dumps(state, indent=2)+'\n'); temp.replace(output)
    print(json.dumps(state), flush=True)
try:
    while True:
        transfer = json.loads(status.read_text())
        if transfer['stage'] == 'copied' and transfer.get('exit_code') == 0: break
        if transfer['stage'] == 'failed': raise RuntimeError('Transfer failed; see compressed/rsync.log')
        command = Path(f"/proc/{transfer['pid']}/cmdline")
        if not command.exists() or b'transfer_compressed.py' not in command.read_bytes():
            raise RuntimeError('Transfer handle stopped without a successful terminal result')
        update('waiting_for_verified_live_transfer', transfer_pid=transfer['pid'])
        time.sleep(60)
    source = root/'transfers/source_manifest.json'
    if not source.is_file(): raise RuntimeError('Source SHA-256 manifest is not available')
    update('verifying_sha256')
    subprocess.run(['python3', str(root/'code/scripts/inventory.py'), str(root/'raw'), str(source), '--verify'], check=True)
    update('auditing_dataset')
    environment = dict(os.environ, WEB_DATA_ROOT=str(root), CUDA_VISIBLE_DEVICES='')
    subprocess.run(['docker', 'compose', '-p', 'scr-verify-h100', 'exec', '-T', 'backend', 'node', 'verification/audit.mjs'], cwd=root/'code', env=environment, check=True)
    update('verified', exit_code=0, transfer=json.loads((root/'transfers/transfer_verified.json').read_text()), dataset=json.loads((root/'runtime/dataset_audit.json').read_text()))
except Exception as error:
    update('failed', exit_code=1, error=str(error))
    raise
