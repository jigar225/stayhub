"""Non-destructive M2 real HTTP/storage persistence check using unique records.

Retains its own test listing/photos; never deletes buckets, volumes or user data.
"""
import hashlib
import json
import secrets
import struct
import subprocess
import time
import urllib.error
import urllib.request
import zlib

BASE = 'http://localhost:5173'


def call(path, body=None, token=None, method=None):
    headers = {'Origin': BASE}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(BASE+'/api/v1'+path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ('POST' if body is not None else 'GET'))
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def png():
    def chunk(kind, data):
        return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',16,16,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes([30,110,90])*16)*16))+chunk(b'IEND',b'')


def main():
    email = 'm2-persist-'+secrets.token_hex(8)+'@example.com'
    password = secrets.token_urlsafe(24)
    call('/auth/register', {'name':'M2 persistence host','email':email,'password':password})
    auth = call('/auth/login', {'email':email,'password':password})
    token = auth['access_token']
    call('/me/host-role', token=token, method='POST')
    listing = call('/host/listings', {}, token)['listing']
    path = '/host/listings/'+listing['id']
    listing = call(path, {'version':listing['version'],'title':'M2 persistence verification','destination':'Lisbon'}, token, 'PATCH')['listing']
    image = png()
    for _ in range(5):
        intent = call(path+'/photos/upload-intents', {'content_type':'image/png','bytes':len(image)}, token)
        upload = intent['upload']
        request = urllib.request.Request(upload['url'],data=image,headers=upload['headers'],method=upload['method'])
        with urllib.request.urlopen(request,timeout=30) as response:
            assert response.status in (200,204)
        call(path+'/photos/'+intent['photo_id']+'/complete', {}, token)
    before = call(path,token=token)['listing']
    def image_hashes(record):
        result = []
        for photo in record['photos']:
            url = call(path+'/photos/'+photo['id']+'/read',token=token)['url']
            with urllib.request.urlopen(url,timeout=20) as response:
                result.append(hashlib.sha256(response.read()).hexdigest())
        return result
    hashes = image_hashes(before)
    subprocess.run(['docker','compose','restart','db','storage','api','frontend'],check=True)
    for _ in range(90):
        try:
            after = call(path,token=token)['listing']
            after_hashes = image_hashes(after)
            break
        except (OSError, urllib.error.URLError, ValueError):
            time.sleep(1)
    else:
        raise RuntimeError('Services did not recover')
    assert before == after
    assert hashes == after_hashes and len(hashes)==5
    print('PASS: unique draft metadata, version, five verified photo identities and image SHA256 bytes survive ordinary db/storage/api/frontend restart.')
    print('PASS: no volumes, buckets, listings or user uploads removed; isolated test records retained.')


if __name__ == '__main__':
    main()
