"""Financial reconciliation/restart check on the separate persisted review stack.

Advances ONLY localhost:5183 / Compose stayhub-m5-review. Retains review data.
Never reads/writes the main development clock or database.
"""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

BASE = "http://localhost:5183"
DC = ["docker", "compose", "-p", "stayhub-m5-review", "-f", "compose.yaml", "-f", "compose.m5-review.yaml"]
OUT = Path("evidence/m5")


def call(path, body=None, token=None, method=None, key=None, expected=200):
    headers = {"Origin": BASE}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(BASE + "/api/v1" + path, headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == expected, (path,response.status,expected)
            return json.load(response)
    except urllib.error.HTTPError as error:
        result = json.load(error)
        if error.code == 429 and expected != 429:
            time.sleep(min(60,max(1,int(error.headers.get("Retry-After","1")))))
            return call(path,body,token,method,key,expected)
        assert error.code == expected, (path,error.code,result.get("error",{}).get("code"))
        return result


def account(name, host=False):
    email = "m5-" + secrets.token_hex(10) + "@example.com"
    password = secrets.token_urlsafe(24)
    call("/auth/register",{"name":name,"email":email,"password":password},expected=201)
    auth=call("/auth/login",{"email":email,"password":password})
    token=auth["access_token"]
    if host:
        call("/me/host-role",token=token,method="POST")
    return token


def create_listing(token):
    listing=call("/host/listings",{},token,expected=201)["listing"]
    path="/host/listings/"+listing["id"]
    policies=call("/host/cancellation-policies",token=token)["items"]
    policy=next(r for r in policies if r["name"]=="Moderate")
    listing=call(path,{"version":listing["version"],"title":"Fictional M5 financial review stay",
        "description":"Isolated local review stay with licensed illustrative images.","destination":"M5 Review",
        "address":"Fictional review address","property_type":"apartment","timezone":"UTC",
        "capacity":2,"bedrooms":1,"beds":1,"baths":1,"amenities":["Kitchen"],"house_rules":["Quiet after 23:00"],
        "nightly_minor":12800,"cleaning_minor":3500,"policy_id":policy["id"],"booking_mode":"instant",
        "check_in_time":"15:00","check_out_time":"11:00"},token,"PATCH")["listing"]
    manifest=Path("demo/assets/manifest.json")
    for asset in json.loads(manifest.read_text())["assets"][:5]:
        image=(manifest.parent/asset["file"]).read_bytes()
        assert hashlib.sha256(image).hexdigest()==asset["sha256"]
        intent=call(path+"/photos/upload-intents",{"content_type":"image/jpeg","bytes":len(image)},token,expected=201)
        up=intent["upload"]
        with urllib.request.urlopen(urllib.request.Request(up["url"],data=image,headers=up["headers"],method=up["method"]),timeout=30) as response:
            assert response.status in (200,204)
        listing=call(path+"/photos/"+intent["photo_id"]+"/complete",{},token)["listing"]
    return call(path+"/publish",{"version":listing["version"]},token)["listing"]


def clock_advance(admin, seconds):
    before=call("/admin/demo/clock",token=admin)
    key=str(uuid4());body={"seconds":seconds}
    result=call("/admin/demo/advance",body,admin,key=key)
    replay=call("/admin/demo/advance",body,admin,key=key)
    assert result["clock"]==replay["clock"]
    after=call("/admin/demo/clock",token=admin)
    assert after["offset_seconds"]==before["offset_seconds"]+seconds
    return result


def snapshot(ids):
    code='''import json
from sqlalchemy import text
from app.db import get_engine
ids=%r
with get_engine().connect() as c:
    rows={}
    for table in ['reservations','payments','refunds','payouts','calendar_entries']:
        col='id' if table=='reservations' else 'reservation_id'
        rows[table]=sorted(c.execute(text('SELECT row_to_json(t) FROM '+table+' t WHERE '+col+'::text=ANY(:ids)'),{'ids':ids}).scalars().all(),key=lambda r:r['id'])
    targets=ids+[r['id'] for n in ['payments','refunds','payouts'] for r in rows[n]]
    rows['event_log']=sorted(c.execute(text('SELECT row_to_json(t) FROM event_log t WHERE target_id::text=ANY(:ids)'),{'ids':targets}).scalars().all(),key=lambda r:r['id'])
    rows['app_clock']=c.execute(text('SELECT row_to_json(t) FROM app_clock t')).scalars().all()
print(json.dumps(rows))
''' % ids
    run=subprocess.run(DC+["exec","-T","api","uv","run","--frozen","python","-c",code],check=True,capture_output=True,text=True)
    return json.loads(run.stdout)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    config=dict(line.split("=",1) for line in Path(".env").read_text().splitlines() if "=" in line and not line.startswith("#"))
    admin=call("/auth/login",{"email":config["SEED_ADMIN_EMAIL"].strip("'\""),"password":config["SEED_ADMIN_PASSWORD"].strip("'\"")})["access_token"]
    assert call("/admin/demo/clock",token=admin)["demo_mode"] is True
    baseline_clock=call("/admin/demo/clock",token=admin)
    host=account("M5 financial review Host",True);guest=account("M5 financial review Guest")
    listing=create_listing(host);path="/host/listings/"+listing["id"]
    now=datetime.fromisoformat(call("/business-time")["business_now"])
    day=now.date(); records={}
    def book(label,offset,nights=5):
        start=day+timedelta(days=offset);dates={"listing_id":listing["id"],"check_in":str(start),"check_out":str(start+timedelta(days=nights)),"guests":2}
        quote=call("/booking-quotes",dates)["quote"]
        r=call("/reservations",{"quote_token":quote["quote_token"]},guest,key=str(uuid4()),expected=201)["reservation"]
        records[label]=r;return r
    def cancel(label):
        r=records[label];p=call("/reservations/"+r["id"]+"/cancellation-quote",{},guest)["preview"]
        key=str(uuid4());body={"confirmation_token":p["confirmation_token"]}
        result=call("/reservations/"+r["id"]+"/cancel",body,guest,key=key)
        assert call("/reservations/"+r["id"]+"/cancel",body,guest,key=key)==result
        records[label]=result["reservation"];return p
    book("full",20)
    assert cancel("full")["total_refund_minor"]==76950
    book("half",3)
    assert cancel("half")["total_refund_minor"]==40225
    book("zero",2);book("one-night",10,1)
    # Advance to12h before zero-tier arrival; never changes the main app clock.
    arrival=datetime.fromisoformat(records["zero"]["scheduled_check_in"])
    current=datetime.fromisoformat(call("/business-time")["business_now"])
    clock_advance(admin,int((arrival-timedelta(hours=12)-current).total_seconds())+1)
    assert cancel("zero")["total_refund_minor"]==3500
    clock_advance(admin,20*86400)
    sweep=call("/admin/demo/sweep",{"batch_size":100},admin)["sweep"]
    for _ in range(20):
        if not sweep["has_more"]:break
        sweep=call("/admin/demo/sweep",{"batch_size":100},admin)["sweep"]
    current={k:call("/reservations/"+r["id"],token=guest)["reservation"] for k,r in records.items()}
    assert current["one-night"]["state"]=="completed"
    assert current["one-night"]["payout"]["status"]=="paid"
    ids=sorted(r["id"] for r in records.values());before=snapshot(ids)
    for r in current.values():
        refunded=r["refund"]["amount_minor"] if r["refund"] else 0
        assert r["payment"]["amount_minor"]-refunded==r["host_entitlement_minor"]+r["platform_entitlement_minor"]
        assert r["payout"]["net_minor"]==r["host_entitlement_minor"]
        if r["payout"]["status"]=="paid": assert r["payout"]["paid_at"]
    earnings=call("/host/earnings",token=host)
    assert earnings["totals"]["paid_minor"]==sum(r["host_entitlement_minor"] for r in current.values())
    offset=call("/admin/demo/clock",token=admin)["offset_seconds"]
    # Access issued before multi-day clock jumps still authenticates on real UTC.
    assert call("/auth/me",token=guest)["user"]
    subprocess.run(DC+["restart","db","storage","api","frontend","expiry-worker"],check=True)
    deadline=time.monotonic()+90
    while True:
        try:
            with urllib.request.urlopen("http://localhost:8010/ready",timeout=5) as response:
                if response.status==200:break
        except (OSError,urllib.error.URLError):pass
        if time.monotonic()>deadline:raise RuntimeError("Review stack did not recover")
        time.sleep(1)
    assert call("/admin/demo/clock",token=admin)["offset_seconds"]==offset
    after=snapshot(ids);assert before==after
    assert call("/host/earnings",token=host)==earnings
    # Authorized S3 URLs also continue to work after business-day advances.
    photos=call("/reservations/"+current["one-night"]["id"]+"/photos",token=guest)["items"]
    with urllib.request.urlopen(photos[0]["url"],timeout=20) as response:
        assert response.status==200 and len(response.read())>0
    (OUT/"reconciliation.json").write_text(json.dumps(after,indent=2)+'\n')
    result={"codes":{k:r["code"] for k,r in current.items()},"refunds_minor":{k:r["refund"]["amount_minor"] if r["refund"] else 0 for k,r in current.items()},"host_entitlements_minor":{k:r["host_entitlement_minor"] for k,r in current.items()},"earnings":earnings["totals"],"offset_seconds":offset,"clock_and_financial_restart_identical":True,"prejump_access_token_still_valid":True,"duplicate_advance_once":True,"main_development_clock_advanced":False,"review_baseline_offset_seconds":baseline_clock["offset_seconds"]}
    (OUT/"persistence.json").write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=="__main__":main()
