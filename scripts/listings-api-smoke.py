"""Independent M2 real HTTP+object-storage adversarial checks. No secrets printed."""
import json
import runpy
import secrets
import urllib.error
import urllib.request

helpers = runpy.run_path('scripts/listings-persistence.py')
call, png = helpers['call'], helpers['png']


def rejected(status, path, token=None, body=None, method=None):
    try:
        call(path, body, token, method)
    except urllib.error.HTTPError as error:
        assert error.code == status, (path, error.code)
        data = json.load(error)
        assert data['error']['request_id']
        print('PASS: expected', status, path.split('/photos')[0].replace(path.split('/')[3] if path.startswith('/host/listings/') else '~', '<listing>'))
    else:
        raise AssertionError('Expected rejection')


def account(host):
    email = 'm2-api-'+secrets.token_hex(8)+'@example.com'
    password = secrets.token_urlsafe(24)
    call('/auth/register', {'name':'M2 isolated check','email':email,'password':password})
    token = call('/auth/login', {'email':email,'password':password})['access_token']
    if host:
        call('/me/host-role', token=token, method='POST')
    return token


def main():
    host, other, guest = account(True), account(True), account(False)
    listing = call('/host/listings', {}, host)['listing']
    path = '/host/listings/'+listing['id']
    rejected(401,path)
    rejected(403,path,guest)
    rejected(404,path,other)
    rejected(404,path,other,{'version':1,'title':'attack'},'PATCH')
    rejected(422,path,host,{'version':1,'owner_id':'00000000-0000-0000-0000-000000000000'},'PATCH')
    policy = call('/host/cancellation-policies',token=host)['items'][0]['id']
    fields = {'property_type':'house','address':'1 Test Street','destination':'Lisbon','timezone':'Europe/Lisbon','capacity':2,'bedrooms':1,'beds':1,'baths':1,'title':'Independent M2 check','description':'A real isolated listing for verification.','amenities':['Wifi'],'house_rules':['No smoking'],'nightly_minor':12500,'cleaning_minor':0,'policy_id':policy,'booking_mode':'instant','check_in_time':'15:00','check_out_time':'11:00'}
    listing = call(path,{'version':listing['version'],**fields},host,'PATCH')['listing']
    rejected(409,path,host,{'version':1,'title':'stale'},'PATCH')
    rejected(422,path+'/photos/upload-intents',host,{'content_type':'image/png','bytes':10485761})
    intent = call(path+'/photos/upload-intents',{'content_type':'image/png','bytes':3},host)
    rejected(404,path+'/photos/'+intent['photo_id']+'/complete',other,{})
    rejected(422,path+'/photos/'+intent['photo_id']+'/complete',host,{})
    rejected(404,path+'/photos/'+intent['photo_id']+'/read',host)
    with urllib.request.urlopen(urllib.request.Request(intent['upload']['url'],data=b'bad',headers=intent['upload']['headers'],method='PUT')):
        pass
    rejected(422,path+'/photos/'+intent['photo_id']+'/complete',host,{})
    image = png()
    for index in range(5):
        intent = call(path+'/photos/upload-intents', {'content_type':'image/png','bytes':len(image)},host)
        with urllib.request.urlopen(urllib.request.Request(intent['upload']['url'],data=image,headers=intent['upload']['headers'],method='PUT')):
            pass
        completed = call(path+'/photos/'+intent['photo_id']+'/complete',{},host)
        repeated = call(path+'/photos/'+intent['photo_id']+'/complete',{},host)
        assert completed == repeated
        listing = completed['listing']
        if index==3:
            rejected(422,path+'/publish',host,{'version':listing['version']})
    assert len(listing['photos']) == 5
    photo_path = path+'/photos/'+listing['photos'][0]['id']
    rejected(404,photo_path+'/read',other)
    rejected(404,photo_path,other,method='DELETE')
    listing = call(path+'/publish',{'version':listing['version']},host)['listing']
    rejected(422,path,host,{'version':listing['version'],'title':None},'PATCH')
    assert call(path,token=host)['listing'] == listing
    rejected(409,photo_path,host,method='DELETE')
    listing = call(path+'/unlist',{'version':listing['version']},host)['listing']
    assert listing['status']=='unlisted' and len(listing['photos'])==5
    print('PASS: five real verified photos publish; invalid published edit rolls back; deletion guarded; unlisting preserves metadata/photos; complete replay is idempotent.')
    print('Independent M2 HTTP/storage checks passed. Unique records retained; no user data deleted.')


if __name__ == '__main__':
    main()
