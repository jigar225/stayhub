"""Explicit bounded downloads for the curated licensed M3 manifest only.

No arbitrary URLs accepted. Existing checksum-matching files are retained.
A changed remote asset is refused once a checksum has been recorded.
"""
import hashlib
import json
import ssl
from pathlib import Path
import urllib.parse
import urllib.request

path = Path('demo/assets/manifest.json')
manifest = json.loads(path.read_text())
for asset in manifest['assets']:
    target = path.parent / asset['file']
    assert target.parent.resolve() == path.parent.resolve()
    url = urllib.parse.urlsplit(asset['image_url'])
    assert url.scheme == 'https' and url.hostname == 'images.pexels.com' and not url.username
    expected = asset['sha256']
    if target.exists() and expected and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        print('Retained verified local asset:', asset['id'])
        continue
    with urllib.request.urlopen(urllib.request.Request(asset['image_url'],headers={'User-Agent':'StayHub-licensed-demo-import/1.0'}),timeout=30, context=ssl.create_default_context(cafile='/etc/ssl/cert.pem') if Path('/etc/ssl/cert.pem').exists() else None) as response:
        assert response.headers.get_content_type() == 'image/jpeg'
        assert urllib.parse.urlsplit(response.url).hostname == 'images.pexels.com'
        content = response.read(10*1024*1024+1)
    assert 0 < len(content) <= 10*1024*1024
    digest = hashlib.sha256(content).hexdigest()
    if expected and digest != expected:
        raise RuntimeError('Remote asset checksum changed; review source/licensing before updating manifest')
    target.write_bytes(content)
    asset['sha256'], asset['bytes'] = digest, len(content)
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('Downloaded licensed asset:',asset['id'],'bytes',len(content),'sha256',digest)
print('All curated assets available locally. Storage import is a separate explicit seed-content step.')
