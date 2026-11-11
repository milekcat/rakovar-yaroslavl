import json
import os
import hashlib
import hmac
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse, quote

import max_client
from max_auth import validate_init_data, MaxInitDataError
from catalog_seed import CATALOG_PRODUCTS


class CatalogTests(unittest.TestCase):
    def test_catalog_is_unique_and_unverified(self):
        ids = [item['id'] for item in CATALOG_PRODUCTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(CATALOG_PRODUCTS), 60)
        self.assertTrue(all(item['price_verified'] == 0 for item in CATALOG_PRODUCTS))
        self.assertTrue(all(item['stock_confirmed'] == 0 for item in CATALOG_PRODUCTS))
        inquiry_items = [item for item in CATALOG_PRODUCTS if item['price_on_request']]
        self.assertTrue(inquiry_items)
        self.assertTrue(all(item['price'] == 0 for item in inquiry_items))
        self.assertTrue(all(item['unit'] == 'по запросу' for item in inquiry_items))



class MaxAuthTests(unittest.TestCase):
    def signed(self, token='test-token', user_id=12345, auth_date=None):
        values={
            'auth_date':str(auth_date if auth_date is not None else int(time.time())),
            'user':json.dumps({'id':user_id,'first_name':'MAX Preview'},ensure_ascii=False,separators=(',',':')),
            'start_param':'shop',
        }
        check='\n'.join(f'{key}={values[key]}' for key in sorted(values))
        secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
        values['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        return '&'.join(f'{key}={quote(value,safe="")}' for key,value in values.items())

    def test_valid_init_data_and_small_max_user_id(self):
        result=validate_init_data(self.signed(user_id=12345),'test-token')
        self.assertEqual(result['user_id'],12345)
        self.assertEqual(result['start_param'],'shop')

    def test_wrapped_webappdata_is_supported(self):
        inner=self.signed(token='test-token', user_id=987654321)
        wrapper='WebAppData='+quote(inner,safe='')+'&WebAppPlatform=android&WebAppVersion=1.0'
        result=validate_init_data(wrapper,'test-token')
        self.assertEqual(result['user_id'],987654321)

    def test_non_positive_user_id_is_rejected(self):
        with self.assertRaises(MaxInitDataError) as caught:
            validate_init_data(self.signed(user_id=0),'test-token')
        self.assertEqual(caught.exception.code,'invalid_max_user_id')

    def test_bad_signature_and_expired_init_data_are_rejected(self):
        bad=self.signed()
        bad=bad.rsplit('hash=',1)[0]+'hash='+'0'*64
        with self.assertRaises(MaxInitDataError):
            validate_init_data(bad,'test-token')
        old=int(time.time())-7200
        with self.assertRaises(MaxInitDataError) as caught:
            validate_init_data(self.signed(auth_date=old),'test-token')
        self.assertEqual(caught.exception.code,'expired_max_init_data')


class MaxClientTests(unittest.TestCase):
    def setUp(self):
        self.old_token = os.environ.get('MAX_BOT_TOKEN')
        os.environ['MAX_BOT_TOKEN'] = 'unit-test-token-not-real'

    def tearDown(self):
        if self.old_token is None:
            os.environ.pop('MAX_BOT_TOKEN', None)
        else:
            os.environ['MAX_BOT_TOKEN'] = self.old_token

    def test_api_uses_authorization_header_and_official_host(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit): return b'{"ok":true}'
        captured = {}
        def fake_urlopen(req, timeout, context):
            captured['url'] = req.full_url
            captured['authorization'] = req.get_header('Authorization')
            captured['timeout'] = timeout
            return FakeResponse()
        with patch.object(max_client, 'urlopen', fake_urlopen):
            result = max_client.api_request('GET', '/me')
        self.assertEqual(result, {'ok': True})
        self.assertEqual(urlparse(captured['url']).netloc, 'platform-api2.max.ru')
        self.assertEqual(captured['authorization'], 'unit-test-token-not-real')
        self.assertNotIn('token', captured['url'].lower())

    def test_send_message_encodes_text_and_keyboard(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit): return b'{"message_id":"test"}'
        captured = {}
        def fake_urlopen(req, timeout, context):
            captured['url'] = req.full_url
            captured['body'] = json.loads(req.data.decode())
            return FakeResponse()
        with patch.object(max_client, 'urlopen', fake_urlopen):
            result = max_client.send_message(user_id=123456789, text='Привет', buttons=[[{'type':'link','text':'Открыть','url':'https://max.ru/example'}]])
        self.assertEqual(result['message_id'], 'test')
        self.assertEqual(parse_qs(urlparse(captured['url']).query)['user_id'], ['123456789'])
        self.assertEqual(captured['body']['text'], 'Привет')
        self.assertEqual(captured['body']['attachments'][0]['type'], 'inline_keyboard')


if __name__ == '__main__':
    unittest.main()
