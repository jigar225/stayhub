"""Prove a fresh HTTP account survives a normal Compose service restart."""
import json
import secrets
import subprocess
import time
import urllib.request

BASE = 'http://localhost:5173'
password = secrets.token_urlsafe(24)
email = 'restart-' + secrets.token_hex(8) + '@example.com'


def post(path, body):
    req = urllib.request.Request(
        BASE + '/api/v1' + path,
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Origin': BASE},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


before = post('/auth/register', {'name': 'Persistence check', 'email': email, 'password': password})
subprocess.run(['docker', 'compose', 'restart', 'db', 'api', 'frontend'], check=True)
for attempt in range(60):
    try:
        with urllib.request.urlopen('http://localhost:8000/ready', timeout=2) as response:
            if response.status == 200:
                break
    except (OSError, urllib.error.URLError):
        pass
    time.sleep(1)
else:
    raise RuntimeError('Database readiness did not recover')
for attempt in range(30):
    try:
        after = post('/auth/login', {'email': email, 'password': password})
        assert before['user']['id'] == after['user']['id']
        print('PASS: account identity and password persisted across db/api/frontend restart; readiness recovered')
        break
    except urllib.error.URLError:
        time.sleep(1)
else:
    raise RuntimeError('Frontend proxy did not recover')
