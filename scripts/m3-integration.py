"""Real HTTP M3 smoke + non-destructive demo rerun/host-edit proof. No auth data logged."""
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import runpy
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from uuid import NAMESPACE_URL, uuid5

base_call = runpy.run_path('scripts/listings-persistence.py')['call']


def call(path, body=None, token=None, method=None):
    if method != 'DELETE':
        return base_call(path, body, token, method)
    headers={'Origin':'http://localhost:5173','Authorization':'Bearer '+token}
    request=urllib.request.Request('http://localhost:5173/api/v1'+path,headers=headers,method='DELETE')
    with urllib.request.urlopen(request,timeout=20) as response:
        assert response.status==204
    return None


def main():
    config = dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    token = call('/auth/login', {'email':config['SEED_HOST_EMAIL'],'password':config['SEED_HOST_PASSWORD']})['access_token']
    manifest = json.loads(Path('demo/assets/manifest.json').read_text())
    ids = {item['demo_key']:str(uuid5(NAMESPACE_URL,'stayhub:demo:'+item['demo_key'])) for item in manifest['listings']}
    before = {key:call('/host/listings/'+value,token=token)['listing'] for key,value in ids.items()}
    assert len(before)==6 and all(len(row['photos'])==5 and row['status']=='published' for row in before.values())
    changed = before['kyoto-room-v1']
    title = 'Fictional Kyoto city room · host-edited review'
    if changed['title']!=title:
        changed = call('/host/listings/'+changed['id'],{'version':changed['version'],'title':title},token,'PATCH')['listing']
    expected = {**before, 'kyoto-room-v1':changed}
    run = subprocess.run(['make','seed-content'],capture_output=True,text=True,check=True)
    Path('evidence/m3/seed-after-host-edit.log').write_text(run.stdout)
    after = {key:call('/host/listings/'+value,token=token)['listing'] for key,value in ids.items()}
    assert after == expected
    proof = {'listing_ids':ids,'photo_ids':{key:[p['id'] for p in value['photos']] for key,value in after.items()},'host_edit_preserved':True,'all_other_fields_versions_and_photo_ids_preserved':True}
    Path('evidence/m3/seed-preservation.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS: six demo listings and30verifiedphotoidentities stable; third seed preserves intentional host title edit and all versions/photos.')
    public = call('/listings?limit=100')['items']
    assert set(ids.values()).issubset({row['id'] for row in public})
    forbidden = {'address','email','owner_id','password_hash','staging_key','final_key','object_key','created_at','updated_at','status'}
    def privacy(value):
        if isinstance(value,dict):
            assert not forbidden.intersection(value)
            for item in value.values():privacy(item)
        elif isinstance(value,list):
            for item in value:privacy(item)
    for listing_id in ids.values():
        detail = call('/listings/'+listing_id)['listing'];privacy(detail)
        assert 'version' not in detail and len(detail['photos'])==5 and detail['demo_label']
        with urllib.request.urlopen(detail['photos'][0]['url'],timeout=15) as response:
            assert response.status==200 and response.headers.get_content_type()=='image/jpeg'
    print('PASS: all six public stays have five real stored photos; allowlisted detail excludes private fields, signed cover reads work.')
    target = ids['lisbon-loft-v1'];path='/host/listings/'+target
    start=datetime.now(UTC).date()+timedelta(days=90);end=start+timedelta(days=5)
    fields={'listing_id':target,'check_in':str(start),'check_out':str(end),'guests':2}
    quote=call('/booking-quotes',fields)['quote']
    assert quote['nights']==5 and quote['nights_minor']==64000 and quote['subtotal_minor']==67500 and quote['guest_fee_minor']==9450 and quote['total_minor']==76950
    query=urllib.parse.urlencode({'destination':'LISBON','check_in':str(start),'check_out':str(end),'guests':2})
    results=call('/listings?'+query)['items'];row=next(row for row in results if row['id']==target)
    assert row['stay_price']['total_minor']==quote['total_minor']
    print('PASS: five nights128EUR +35EUR cleaning =>675EUR subtotal +94.50EUR guest fee =769.50EUR; dated search and quote agree.')
    block=call(path+'/blocks',{'check_in':str(start),'check_out':str(end)},token)['block']
    try:
        assert target not in {row['id'] for row in call('/listings?'+query)['items']}
        try:call('/booking-quotes',fields)
        except urllib.error.HTTPError as error:assert error.code==409
        else:raise AssertionError('Blocked quote accepted')
        availability=call('/listings/'+target+'/availability?'+urllib.parse.urlencode({'start':str(start),'end':str(end)}))
        assert availability['unavailable']==[{'check_in':str(start),'check_out':str(end)}]
    finally:
        call(path+'/blocks/'+block['id'],token=token,method='DELETE')
    assert target in {row['id'] for row in call('/listings?'+query)['items']}
    print('PASS: host block excludes public full-range search/quote; availability hides reason/ID; unblock restores inclusion. Only the check-created block removed.')
    print('M3 independent checks complete; original user data/uploads retained.')


if __name__=='__main__':main()
