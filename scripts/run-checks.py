"""Run requested Make targets, retaining exact exits and sanitized tool output."""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

out = Path('evidence/checks')
out.mkdir(parents=True, exist_ok=True)
results = []
for target in sys.argv[1:]:
    command = ['make', target]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out / (target + '.log')).write_text(result.stdout)
    results.append({'command': ' '.join(command), 'exit': result.returncode, 'log': str(out / (target + '.log')), 'recorded_at': datetime.now(timezone.utc).isoformat()})
    print(' '.join(command), 'exit', result.returncode, 'log', out / (target+'.log'), flush=True)
    if result.returncode:
        print(result.stdout[-6000:], flush=True)
(out / 'latest-results.json').write_text(json.dumps(results, indent=2)+'\n')
with (out / 'history.jsonl').open('a') as history:
    for item in results:
        history.write(json.dumps(item)+'\n')
raise SystemExit(any(item['exit'] for item in results))
