"""Offline checks of the unapplied bot proposal; all Telegram methods are mocked."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as Object
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]/'tests'))
import test_shared_rules as fixtures
from backend import db
from backend.drafts import draft_data
from backend.security import create_challenge

class BotProposalTests(unittest.TestCase):
    setUp=fixtures.SharedRulesTests.setUp
    tearDown=fixtures.SharedRulesTests.tearDown
    user=fixtures.SharedRulesTests.user
    create=fixtures.SharedRulesTests.create
    execute=fixtures.SharedRulesTests.execute
    image=fixtures.SharedRulesTests.image

    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('bot_proposal',Path(__file__).parent/'proposals/bot_main.py')
        cls.module=importlib.util.module_from_spec(spec)
        with patch.object(db,'get_db',side_effect=AssertionError('DB at import')):
            spec.loader.exec_module(cls.module)
        cls.module.get_db=db.get_db

    def test_login_needs_code_and_restores_existing_draft(self):
        conn=db.get_db();token,code=create_challenge(conn.cursor(),'browser');conn.commit();conn.close()
        user=Object(id=6000000001,username='audit',first_name='Audit',last_name=None)
        message=Object(from_user=user,chat=Object(id=user.id),text='/start web_'+token)
        with draft_data(user.id,user.id) as data:data.update(flow_step='price',price=900000)
        with patch.object(self.module.bot,'reply_to'):
            self.module.send_welcome(message)
            self.assertIsNone(self.execute('SELECT approved_at FROM web_login_tokens')[0][0])
            message.text=code
            self.module.route_text_by_flow_step(message)
        self.assertIsNotNone(self.execute('SELECT approved_at FROM web_login_tokens')[0][0])
        with draft_data(user.id,user.id) as data:self.assertEqual((data['flow_step'],data['price']),('price',900000))

    def test_matching_search_also_saves_gender_preferences(self):
        listing=self.create()
        seeker=6000000002;self.user(seeker)
        with draft_data(seeker,seeker) as data:data.update(s_gender='female',s_preferred_gender='male',s_price_min=0,s_price_max=1000000,s_amenities=[],s_district='Yunusobod')
        with patch.object(self.module.bot,'send_message') as send:self.module.run_search_and_reply(seeker,seeker)
        self.assertGreaterEqual(send.call_count,2)
        row=self.execute('SELECT * FROM search_preferences WHERE telegram_user_id=?',(seeker,))[0]
        self.assertEqual((row['seeker_gender'],row['preferred_gender']),('female','male'))

    def test_held_publication_is_not_announced_as_published(self):
        call=Object(id='callback',data='confirm_yes',from_user=Object(id=6000000001,username='audit'),message=Object(chat=Object(id=6000000001),message_id=7))
        with patch.object(self.module.bot,'answer_callback_query'),patch.object(self.module.bot,'edit_message_text') as edit,patch.object(self.module,'save_listing_to_db',return_value={'listing_id':1,'status':'hidden_pending_review'}):
            self.module.handle_confirm(call)
        self.assertIn('tekshiruvga',edit.call_args.args[0])

    def test_bot_publication_uses_shared_coordinates_and_duplicate_rules(self):
        self.create(photos=[self.image()])
        user_id=6000000002;self.user(user_id)
        with draft_data(user_id,user_id) as data:
            data.update(self.payload,needed=1,phone=None,photos=['synthetic-photo'],amenities=[])
        with patch.object(self.module,'UPLOAD_DIR',self.directory.name),patch.object(self.module.bot,'get_file',return_value=Object(file_size=1000,file_path='fixture')),patch.object(self.module.bot,'download_file',return_value=self.image()):
            created=self.module.save_listing_to_db(user_id,user_id)
        self.assertEqual(created['status'],'hidden_pending_review')
        self.assertNotEqual(created['listing']['lat'],self.payload['lat'])

if __name__=='__main__':unittest.main()
