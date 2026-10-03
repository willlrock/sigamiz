import asyncio
import io
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_shared_rules as fixtures
from backend import db, storage, notifications, migrate_photos
from backend.drafts import draft_data
from backend.request_limits import BodyLimit
from backend.migrations import init_db
from backend.migrate_drafts import migrate as migrate_drafts


class InfrastructureTests(unittest.TestCase):
    setUp = fixtures.SharedRulesTests.setUp
    tearDown = fixtures.SharedRulesTests.tearDown
    user = fixtures.SharedRulesTests.user
    create = fixtures.SharedRulesTests.create
    execute = fixtures.SharedRulesTests.execute
    image = fixtures.SharedRulesTests.image

    def test_drafts_serialize_and_do_not_commit_failed_changes(self):
        errors=[]
        def increment():
            try:
                for _ in range(10):
                    with draft_data(6000000001,6000000001) as data:
                        data['count']=data.get('count',0)+1
            except Exception as error:
                errors.append(error)
        threads=[threading.Thread(target=increment) for _ in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10)
        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        with self.assertRaises(ValueError):
            with draft_data(6000000001,6000000001) as data:
                self.assertEqual(data['count'],40)
                data['count']=0
                raise ValueError('abort')
        with draft_data(6000000001,6000000001) as data:self.assertEqual(data['count'],40)

    def test_outbox_failure_retries_and_success_is_not_sent_twice(self):
        conn=db.get_db()
        notifications.enqueue(conn.cursor(),'event',6000000001,'Test')
        notifications.enqueue(conn.cursor(),'event',6000000001,'Test')
        conn.commit();conn.close()
        response=Mock(ok=False)
        with patch.dict(os.environ,{'BOT_TOKEN':'0:TEST'}), patch.object(notifications.requests,'post',return_value=response) as send:
            notifications.deliver_batch();notifications.deliver_batch()
            self.assertEqual(send.call_count,1)
            self.assertEqual(self.execute('SELECT attempts FROM notification_outbox')[0][0],1)
            self.execute("UPDATE notification_outbox SET next_attempt_at='2000-01-01'")
            response.ok=True;response.json.return_value={'ok':True}
            notifications.deliver_batch();notifications.deliver_batch()
            self.assertEqual(send.call_count,2)
            self.assertIsNotNone(self.execute('SELECT delivered_at FROM notification_outbox')[0][0])

    def test_legacy_drafts_are_retained_and_current_drafts_not_overwritten(self):
        source=Path(self.directory.name)/'legacy.json'
        source.write_text('{"6000000001:6000000001":{"price":900000,"web_login_token":"old"}}')
        self.assertEqual(migrate_drafts(source),1)
        self.assertEqual(migrate_drafts(source,apply=True),1)
        with draft_data(6000000001,6000000001) as data:
            self.assertEqual(data['price'],900000);self.assertNotIn('web_login_token',data)
            data['price']=800000
        self.assertEqual(migrate_drafts(source,apply=True),0)
        with draft_data(6000000001,6000000001) as data:self.assertEqual(data['price'],800000)

    def test_s3_keys_and_public_urls_do_not_include_local_paths(self):
        client=Mock()
        with patch.dict(os.environ,{'S3_BUCKET':'test-bucket','PHOTO_PUBLIC_URL':'https://images.example.test'}),patch.object(storage,'s3_client',return_value=client):
            key=storage.store_photo(b'jpeg')
            self.assertTrue(key.startswith('photos/'))
            self.assertEqual(client.put_object.call_args.kwargs['ContentType'],'image/jpeg')
            self.assertEqual(storage.photo_url(key),'https://images.example.test/'+key)
            storage.delete_photo(key)
            client.delete_object.assert_called_once_with(Bucket='test-bucket',Key=key)

    def test_legacy_photo_migration_reencodes_and_retains_original(self):
        from PIL import Image
        listing=self.create()['listing_id']
        source=Path(self.directory.name)/'old.png'
        Image.new('RGBA',(20,20),(50,100,150,200)).save(source)
        self.execute('INSERT INTO listing_photos (listing_id,file_path) VALUES (?,?)',(listing,str(source)))
        stored=[]
        with patch.object(migrate_photos,'UPLOAD_DIR',self.directory.name),patch.object(migrate_photos,'store_photo',side_effect=lambda data:stored.append(data) or 'photos/new.jpg'):
            self.assertEqual(migrate_photos.migrate(),(1,0));self.assertEqual(stored,[])
            self.assertEqual(migrate_photos.migrate(apply=True),(1,0))
            self.assertEqual(migrate_photos.migrate(apply=True),(0,0))
        self.assertTrue(source.exists())
        self.assertEqual(Image.open(io.BytesIO(stored[0])).format,'JPEG')

    def test_migration_preserves_moderation_when_reconciling_owners(self):
        listing=self.create()['listing_id']
        self.execute('DROP INDEX idx_one_live_listing_per_owner')
        self.execute("UPDATE listings SET status='hidden_pending_review' WHERE id=?",(listing,))
        conn=db.get_db()
        columns=[row[1] for row in conn.execute('PRAGMA table_info(listings)') if row[1]!='id']
        conn.execute('INSERT INTO listings ('+','.join(columns)+') SELECT '+','.join(columns)+' FROM listings WHERE id=?',(listing,))
        conn.execute('DELETE FROM schema_migrations');conn.commit();conn.close()
        init_db();init_db()
        statuses=[row[0] for row in self.execute('SELECT status FROM listings ORDER BY id')]
        self.assertEqual(statuses,['archived_pending_review','hidden_pending_review'])
        self.assertEqual(len(self.execute('SELECT * FROM schema_migrations')),2)

    def test_postgres_translation_keeps_external_ids_bigint_and_expiry_comparison(self):
        schema=db._postgres_schema(Path(db.SCHEMA_PATH).read_text())
        self.assertIn('telegram_user_id BIGINT',schema)
        self.assertIn('reporter_telegram_id BIGINT',schema)
        query=db._translate_postgres_sql("SELECT id FROM listings WHERE datetime(expires_at)>datetime('now') AND telegram_user_id=?")
        self.assertIn('expires_at>CURRENT_TIMESTAMP',query)
        self.assertIn('telegram_user_id=%s',query)

    def test_chunked_body_limit_rejects_before_route(self):
        async def check():
            called=[];sent=[]
            async def app(scope,receive,send):called.append(True)
            messages=iter([{'type':'http.request','body':b'abc','more_body':True},{'type':'http.request','body':b'def','more_body':False}])
            async def receive():return next(messages)
            async def send(message):sent.append(message)
            await BodyLimit(app,limit=5)({'type':'http'},receive,send)
            self.assertEqual(called,[]);self.assertEqual(sent[0]['status'],413)
        asyncio.run(check())
