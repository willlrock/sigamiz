"""Local disposable fixtures for browser checks; no production DB or Telegram calls."""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.append(str(ROOT/'.venv/Lib/site-packages'))
folder=tempfile.TemporaryDirectory(prefix='sigamiz-ui-')
os.environ.update(SIGAMIZ_DB_PATH=os.path.join(folder.name,'test.db'),UPLOAD_DIR=os.path.join(folder.name,'uploads'),DATABASE_URL='',BOT_TOKEN='',ADMIN_CHAT_ID='',SITE_URL='http://127.0.0.1:8017',DISABLE_BACKGROUND_WORKER='true',YANDEX_MAPS_JS_KEY='',YANDEX_JAVA='',Yandex_java='',YANDEX_GEOCODER_KEY='',YANDEX_GEOCODER='',Yandex_geocoder='')
from PIL import Image
from backend.migrations import init_db
from backend.security import upsert_user,make_session_cookie
from backend.db import get_db
from backend.listing_service import create_offer_listing
init_db()
for index in range(8):
    conn=get_db();cursor=conn.cursor();uid=1000001+index
    upsert_user(cursor,uid,username=f'sigamiz_test_{index}',first_name='Test '+('Long Name '*8 if index==0 else str(index)),bot_started=True);conn.commit()
    user=cursor.execute('SELECT * FROM users WHERE telegram_user_id=?',(uid,)).fetchone()
    images=[]
    for color in ('#91b3a0','#acbea1','#a5b2bd'):
        stream=io.BytesIO();Image.new('RGB',(800,600),color).save(stream,'JPEG');images.append(stream.getvalue())
    payload=dict(district='Yunusobod',university='TATU',housing_type='Kvartira',author_gender='male',preferred_gender='any',lat=41.365+index*.008,lng=69.285+index*.008,price=900000+index*100000,people_needed=2,room_count=3,description='Sinov e‘loni: yorug‘ xona, universitetga yaqin.',phone_number='+998901234567',has_wifi=True,near_metro=True)
    create_offer_listing(cursor,user,payload,images,os.environ['UPLOAD_DIR'],'file_path');conn.commit();conn.close()
from backend.main import app
from fastapi.responses import RedirectResponse,JSONResponse
failure=False
@app.middleware('http')
async def fixture_middleware(request,call_next):
    if failure and request.url.path=='/api/listings' and request.method=='GET':return JSONResponse({'detail':'Fixture unavailable'},status_code=503)
    if request.url.path=='/api/geocode':return JSONResponse({'lat':41.365123,'lng':69.285987,'label':'Test manzil'})
    return await call_next(request)
@app.get('/audit/login')
def login():
    response=RedirectResponse('/publish');response.set_cookie('sigamiz_session',make_session_cookie(1000001),httponly=True);return response
@app.get('/audit/failure')
def fail():
    global failure
    failure=True;return RedirectResponse('/xarita')
@app.get('/audit/reset')
def reset():
    global failure
    failure=False;return RedirectResponse('/xarita')
if __name__=='__main__':
    import uvicorn
    try:uvicorn.run(app,host='127.0.0.1',port=8017)
    finally:folder.cleanup()
