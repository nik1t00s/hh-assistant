import unittest
from unittest.mock import Mock
import requests
from main import HHClient, HHAccessRestriction


class AccessTests(unittest.TestCase):
    def response(self, status, url, headers=None):
        response = requests.Response()
        response.status_code = status
        response.url = url
        response.headers.update(headers or {})
        response._content = b"synthetic"
        client = HHClient(lambda _: None)
        client.session.get = Mock(return_value=response)
        return client

    def test_distinct_restrictions_and_no_retry(self):
        for status, url, expected in [
            (403, 'https://hh.ru/vacancy/1', 'доступ запрещён'),
            (429, 'https://hh.ru/vacancy/1', 'слишком много запросов'),
            (200, 'https://hh.ru/captcha?token=SECRET', 'страница капчи'),
        ]:
            with self.subTest(status=status):
                client = self.response(status, url)
                with self.assertRaises(HHAccessRestriction) as caught:
                    client._get('https://hh.ru/vacancy/1')
                self.assertIn(expected, str(caught.exception))
                self.assertIn(f'HTTP {status}', caught.exception.summary)
                self.assertNotIn('SECRET', str(caught.exception))
                client.session.get.assert_called_once()

    def test_retry_after_only_safe_numeric_value(self):
        for value, expected in [('120', True), ('secret-token', False)]:
            client = self.response(429, 'https://hh.ru/vacancy/1', {'Retry-After': value})
            with self.assertRaises(HHAccessRestriction) as caught:
                client._get('unused')
            self.assertEqual('Retry-After:' in str(caught.exception), expected)
            self.assertNotIn('secret-token', str(caught.exception))

    def test_query_word_is_not_captcha_and_other_errors_stay_http_errors(self):
        client = self.response(200, 'https://hh.ru/search/vacancy?text=captcha')
        self.assertEqual(client._get('unused').status_code, 200)
        client = self.response(404, 'https://hh.ru/vacancy/1')
        with self.assertRaises(requests.HTTPError):
            client._get('unused')

    def test_login_does_not_claim_expired_cookies(self):
        client = self.response(200, 'https://hh.ru/account/login?token=SECRET')
        with self.assertRaises(RuntimeError) as caught:
            client._get('unused')
        self.assertNotIsInstance(caught.exception, HHAccessRestriction)
        self.assertIn('не доказывает', str(caught.exception))
        self.assertNotIn('SECRET', str(caught.exception))

    def test_cookies_scoped_to_https_hh_and_preserve_equals(self):
        client = HHClient(lambda _: None, cookie='session=synthetic==; other=value')
        for url, expected in [('https://hh.ru/vacancy/1', True),
                              ('https://spb.hh.ru/vacancy/1', True),
                              ('https://example.org/', False),
                              ('https://hh.ru.example.org/', False),
                              ('http://hh.ru/', False)]:
            request = client.session.prepare_request(requests.Request('GET', url))
            self.assertEqual('session=synthetic==' in request.headers.get('Cookie', ''), expected)
