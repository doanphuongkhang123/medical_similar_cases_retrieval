#!/usr/bin/env python3
"""Keep the active free HTTPS URL alongside the service log."""
import datetime
import json
import re
import subprocess
from pathlib import Path
root = Path('/data/khangdp/scr/verify_web')
command = [str(root/'bin/cloudflared'), 'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', 'http://127.0.0.1:5178']
child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
for line in child.stdout:
    print(line, end='', flush=True)
    found = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
    if found:
        (root/'logs/public_url.txt').write_text(found.group(0)+'\n')
        (root/'logs/public_tunnel.json').write_text(json.dumps({
            'url': found.group(0), 'pid': child.pid, 'origin': 'http://127.0.0.1:5178',
            'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'command': command,
        }, indent=2)+'\n')
raise SystemExit(child.wait())
