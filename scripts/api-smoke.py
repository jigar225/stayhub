"""Independent real-HTTP auth/security smoke; sanitized output only."""
import http.cookiejar
import json
import secrets
import urllib.error
import urllib.request

BASE = 'http://localhost:5173'
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(path, method='GET', body=None, token=None, csrf=None, origin=BASE):
    headers = {'Origin': origin}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if csrf:
        headers['X-CSRF-Token'] = csrf
    req = urllib.request.Request(BASE+'/api/v1'+path, method=method,
        data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        response = client.open(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    data = response.read()
    return response.status, json.loads(data) if data else None


def expect(status, result, name):
    assert result[0] == status, (name, result[0])
    print('PASS:', name, status)
    return result[1]


password = secrets.token_urlsafe(24)
body = {'name':'HTTP smoke', 'email':'http-'+secrets.token_hex(8)+'@example.com','password':password}
expect(422, call('/auth/register','POST',{**body,'roles':['admin']}), 'reject privileged signup fields')
user = expect(201,call('/auth/register','POST',body),'guest signup')['user']
assert user['roles'] == ['guest']
expect(409,call('/auth/register','POST',body),'duplicate email')
expect(401,call('/auth/login','POST',{'email':body['email'],'password':'incorrect-password'}),'invalid login')
auth = expect(200,call('/auth/login','POST',{'email':body['email'],'password':password}),'login')
token, csrf = auth['access_token'], auth['csrf_token']
assert expect(200,call('/auth/me',token=token),'own profile')['user']['id'] == user['id']
expect(401,call('/auth/me'),'missing auth')
expect(401,call('/auth/me',token=token+'tampered'),'forged token')
expect(403,call('/host/today',token=token),'guest denied host API')
expect(403,call('/admin/status',token=token),'guest denied admin API')
expect(403,call('/auth/refresh','POST',csrf=csrf,origin='https://untrusted.invalid'),'untrusted origin')
expect(403,call('/auth/refresh','POST'),'missing CSRF')
old_cookie = next(c.value for c in jar if c.name=='stayhub_refresh')
rotated = expect(200,call('/auth/refresh','POST',csrf=csrf),'refresh rotation')
assert next(c.value for c in jar if c.name=='stayhub_refresh') != old_cookie
host = expect(200,call('/me/host-role','POST',token=rotated['access_token']),'host enrollment')['user']
assert set(host['roles']) == {'guest','host'}
expect(200,call('/me/host-role','POST',token=token),'idempotent enrollment')
expect(200,call('/host/today',token=token),'current database roles apply to existing token')
expect(204,call('/auth/logout','POST',csrf=csrf),'logout')
expect(401,call('/auth/me',token=token),'logout revokes earlier access token')
expect(401,call('/auth/me',token=rotated['access_token']),'logout revokes rotated access token')
expect(204,call('/auth/logout','POST'),'logout already absent')
print('Independent HTTP smoke complete; no credentials or tokens emitted.')
