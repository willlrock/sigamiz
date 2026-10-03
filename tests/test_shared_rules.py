import base64
import io
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.update(BOT_TOKEN='', DATABASE_URL='', SITE_URL='http://testserver', DISABLE_BACKGROUND_WORKER='true')

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from backend import db
from backend.migrations import init_db
from backend.security import upsert_user, make_session_cookie, read_session_cookie, approve_challenge, digest
from backend.listing_service import create_offer_listing, ListingServiceError
from backend.lifecycle import expire_listings, manage_listing
from backend.search import search_clause, save_preferences
from backend import main

class SharedRulesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch_db = patch.object(db, 'SQLITE_DB_PATH', os.path.join(self.directory.name,'test.db'))
        self.patch_db.start()
        self.patch_upload = patch.object(main, 'UPLOAD_DIR', self.directory.name)
        self.patch_upload.start()
        init_db()
        self.user(6_000_000_001)
        self.payload = dict(district='Yunusobod',university='TATU',housing_type='Kvartira',author_gender='male',preferred_gender='female',lat=41.365123,lng=69.285987,price=900000,people_needed=1,room_count=2)

    def tearDown(self):
        self.patch_upload.stop()
        self.patch_db.stop()
        self.directory.cleanup()

    def user(self, user_id, username='audit'):
        conn=db.get_db()
        upsert_user(conn.cursor(),user_id,username=username,bot_started=True)
        conn.commit();conn.close()

    def create(self, user_id=6_000_000_001, payload=None, photos=None):
        conn=db.get_db()
        try:
            cursor=conn.cursor()
            user=cursor.execute('SELECT * FROM users WHERE telegram_user_id=?',(user_id,)).fetchone()
            result=create_offer_listing(cursor,user,payload or self.payload,photos or [],self.directory.name,'file_path')
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self,sql,params=()):
        conn=db.get_db()
        try:
            rows=conn.execute(sql,params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def image(self, plain=False):
        image=Image.new('RGB',(240,360),'white')
        if not plain:
            draw=ImageDraw.Draw(image)
            draw.rectangle((10,20,80,350),fill='black')
            draw.rectangle((110,90,235,200),fill='green')
        stream=io.BytesIO();image.save(stream,'PNG');return stream.getvalue()

    def test_ban_applies_to_common_publication(self):
        self.execute('INSERT INTO banned_users (telegram_user_id) VALUES (?)',(6_000_000_001,))
        with self.assertRaises(ListingServiceError) as error:self.create()
        self.assertEqual(error.exception.status_code,403)
        self.assertEqual(self.execute('SELECT COUNT(*) FROM listings')[0][0],0)

    def test_public_coordinates_are_stable_and_approximate(self):
        row=self.create()['listing']
        self.assertNotEqual((row['lat'],row['lng']),(self.payload['lat'],self.payload['lng']))
        init_db();init_db()
        saved=self.execute('SELECT lat,lng FROM listings')[0]
        self.assertEqual((row['lat'],row['lng']),tuple(saved))

    def test_repeated_own_photo_is_deduplicated(self):
        result=self.create(photos=[self.image(),self.image()])
        self.assertEqual(result['status'],'active')
        self.assertEqual(result['duplicate_matches'],[])
        self.assertEqual(self.execute('SELECT COUNT(*) FROM listing_photos')[0][0],1)

    def test_other_listing_photo_enters_review(self):
        first=self.create(photos=[self.image()])
        self.user(6_000_000_002)
        second=self.create(6_000_000_002,photos=[self.image()])
        self.assertEqual(second['status'],'hidden_pending_review')
        self.assertEqual(second['duplicate_matches'][0]['listing_id'],first['listing_id'])

    def test_plain_photos_do_not_imply_duplicate_apartment(self):
        self.create(photos=[self.image(True)])
        self.user(6_000_000_002)
        self.assertEqual(self.create(6_000_000_002,photos=[self.image(True)])['status'],'active')

    def test_invalid_input_and_image_leave_no_record_or_file(self):
        for payload in ({**self.payload,'lat':'NaN'},{**self.payload,'district':{}},{**self.payload,'room_count':2.5},{**self.payload,'has_wifi':[]}):
            with self.assertRaises(ListingServiceError):self.create(payload=payload)
        with self.assertRaises(ListingServiceError):self.create(photos=[b'not an image'])
        self.assertEqual(self.execute('SELECT COUNT(*) FROM listings')[0][0],0)
        self.assertFalse(os.path.exists(os.path.join(self.directory.name,'photos')))

    def test_failure_after_saving_photo_rolls_back_and_removes_file(self):
        with patch('backend.notifications.enqueue_publication',side_effect=RuntimeError('fixture queue failure')):
            with self.assertRaises(RuntimeError):self.create(photos=[self.image()])
        self.assertEqual(self.execute('SELECT COUNT(*) FROM listings')[0][0],0)
        from pathlib import Path
        self.assertEqual(list(Path(self.directory.name).rglob('*.jpg')),[])

    def test_old_bot_confirmation_cannot_bypass_code(self):
        with TestClient(main.app) as browser:
            challenge=browser.post('/api/auth/telegram/start').json()
            self.execute('UPDATE web_login_tokens SET telegram_user_id=? WHERE token=?',(6_000_000_001,challenge['token']))
            self.assertTrue(browser.post('/api/auth/telegram/complete',json={'token':challenge['token']}).json()['pending'])

    def test_login_guess_limit(self):
        with TestClient(main.app) as browser:
            challenge=browser.post('/api/auth/telegram/start').json()
            conn=db.get_db();cursor=conn.cursor()
            for _ in range(5):self.assertFalse(approve_challenge(cursor,challenge['token'],'wrong',6_000_000_001))
            self.assertFalse(approve_challenge(cursor,challenge['token'],challenge['code'],6_000_000_001))
            conn.commit();conn.close()

    def test_expiry_preserves_removed_and_review_hold(self):
        listing=self.create()['listing_id']
        for status,expected in [('removed','removed'),('hidden_pending_review','hidden_pending_review'),('active','expired')]:
            self.execute("UPDATE listings SET status=?,expires_at='2000-01-01' WHERE id=?",(status,listing))
            conn=db.get_db();expire_listings(conn.cursor());conn.commit();conn.close()
            self.assertEqual(self.execute('SELECT status FROM listings')[0][0],expected)
        conn=db.get_db();self.assertEqual(manage_listing(conn.cursor(),listing,6_000_000_001,'extend'),'active');conn.commit();conn.close()

    def test_concurrent_publication_keeps_one_listing(self):
        statuses=[]
        def publish():
            try:self.create();statuses.append(200)
            except ListingServiceError as exc:statuses.append(exc.status_code)
        threads=[threading.Thread(target=publish) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10)
        self.assertCountEqual(statuses,[200,409])
        self.assertEqual(self.execute('SELECT COUNT(*) FROM listings')[0][0],1)

    def test_search_and_notifications_use_same_gender_contract(self):
        listing=self.create()['listing_id']
        self.user(6_000_000_002)
        conn=db.get_db();cursor=conn.cursor()
        save_preferences(cursor,6_000_000_002,dict(seeker_gender='male',preferred_gender='male'))
        from backend.notifications import enqueue_publication
        enqueue_publication(cursor,listing)
        self.assertEqual(cursor.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0],0)
        filters=dict(seeker_gender='female',preferred_gender='male')
        clause,params=search_clause(filters)
        self.assertEqual(len(cursor.execute('SELECT * FROM listings WHERE '+clause,params).fetchall()),1)
        save_preferences(cursor,6_000_000_002,filters)
        enqueue_publication(cursor,listing);enqueue_publication(cursor,listing)
        self.assertEqual(cursor.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0],1)
        conn.commit();conn.close()

    def test_contact_required_without_username(self):
        self.user(6_000_000_001,username=None)
        with self.assertRaises(ListingServiceError):self.create()
        self.assertEqual(self.create(payload={**self.payload,'phone_number':'+998 90 123 45 67'})['status'],'active')

    def test_session_expiry_and_logout_revoke_cookie(self):
        token=make_session_cookie(6_000_000_001)
        self.assertEqual(read_session_cookie(token),6_000_000_001)
        with TestClient(main.app) as client:
            client.cookies.set('sigamiz_session',token)
            self.assertEqual(client.get('/api/me').json()['user']['telegram_user_id'],6_000_000_001)
            self.assertEqual(client.post('/api/logout').status_code,200)
        self.assertIsNone(read_session_cookie(token))
        token=make_session_cookie(6_000_000_001)
        self.execute("UPDATE web_sessions SET expires_at='2000-01-01' WHERE token_hash=?",(digest(token),))
        self.assertIsNone(read_session_cookie(token))

    def test_login_requires_code_browser_binding_and_single_use(self):
        with TestClient(main.app) as browser, TestClient(main.app) as stranger:
            challenge=browser.post('/api/auth/telegram/start').json()
            payload={'token':challenge['token']}
            self.assertEqual(stranger.post('/api/auth/telegram/complete',json=payload).status_code,400)
            self.assertTrue(browser.post('/api/auth/telegram/complete',json=payload).json()['pending'])
            conn=db.get_db();cursor=conn.cursor()
            self.assertFalse(approve_challenge(cursor,challenge['token'],'wrong',6_000_000_001))
            self.assertTrue(approve_challenge(cursor,challenge['token'],challenge['code'],6_000_000_001))
            self.assertFalse(approve_challenge(cursor,challenge['token'],challenge['code'],6_000_000_002))
            conn.commit();conn.close()
            self.assertTrue(browser.post('/api/auth/telegram/complete',json=payload).json()['ok'])
            self.assertEqual(browser.post('/api/auth/telegram/complete',json=payload).status_code,404)

    def test_expired_listing_is_unavailable_in_all_public_routes(self):
        listing=self.create()['listing_id']
        self.execute("UPDATE listings SET expires_at='2000-01-01' WHERE id=?",(listing,))
        with TestClient(main.app) as client:
            self.assertEqual(client.get('/api/listings').json(),[])
            self.assertEqual(client.get(f'/api/listings/{listing}').status_code,404)
            self.assertEqual(client.get('/api/stats').json()['active_listings'],0)

    def test_iso_date_expiry_same_day_is_checked_as_time(self):
        from datetime import datetime, timedelta, timezone
        listing=self.create()['listing_id']
        expired=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        self.execute('UPDATE listings SET expires_at=? WHERE id=?',(expired,listing))
        with TestClient(main.app) as client:
            self.assertEqual(client.get('/api/listings').json(),[])
            self.assertEqual(client.get(f'/api/listings/{listing}').status_code,404)

if __name__=='__main__':unittest.main()
