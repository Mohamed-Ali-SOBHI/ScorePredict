import json
import unittest
from unittest.mock import Mock, patch

import requests
from data_pipeline import http_retry
from production import paper_source_runtime_v3 as runtime

URL = 'https://understat.com/getLeagueData/Bundesliga/2026'


class SourceRetryTests(unittest.TestCase):
    def response(self, status=200):
        response = requests.Response()
        response.status_code = status
        response._content = b'{"dates":[]}'
        response._content_consumed = True
        response.url = URL
        return response

    @patch('data_pipeline.http_retry.time.sleep')
    def test_dns_failure_then_success_keeps_request_and_live_response(self, sleep):
        response = self.response()
        get = Mock(side_effect=[requests.ConnectionError('getaddrinfo failed'), response])
        self.assertIs(http_retry.get(URL, request=get, timeout=30, headers={'X-Requested-With': 'XMLHttpRequest'}), response)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0], get.call_args_list[1])
        sleep.assert_called_once_with(3)

    @patch('data_pipeline.http_retry.time.sleep')
    def test_outage_remains_blocking_after_bounded_attempts(self, sleep):
        get = Mock(side_effect=requests.ConnectionError('DNS unavailable'))
        with self.assertRaises(requests.ConnectionError):
            http_retry.get(URL, request=get, timeout=30)
        self.assertEqual(get.call_count, 4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [3, 10, 30])

    @patch('data_pipeline.http_retry.time.sleep')
    def test_transient_status_and_timeout_are_retried(self, sleep):
        for failure in [self.response(503), self.response(429), requests.Timeout('timeout')]:
            response = self.response()
            get = Mock(side_effect=[failure, response])
            self.assertIs(http_retry.get(URL, request=get, timeout=30), response)
            self.assertEqual(get.call_count, 2)

    @patch('data_pipeline.http_retry.time.sleep')
    def test_permanent_status_and_tls_errors_are_not_retried(self, sleep):
        for status in [400, 401, 403, 404]:
            get = Mock(return_value=self.response(status))
            with self.assertRaises(requests.HTTPError):
                http_retry.get(URL, request=get, timeout=30)
            self.assertEqual(get.call_count, 1)
        with self.assertRaises(requests.exceptions.SSLError):
            http_retry.get(URL, request=Mock(side_effect=requests.exceptions.SSLError('certificate')), timeout=30)
        sleep.assert_not_called()

    @patch('data_pipeline.http_retry.time.sleep')
    def test_unrelated_store_is_not_retried(self, sleep):
        get = Mock(side_effect=requests.ConnectionError('store down'))
        with self.assertRaises(requests.ConnectionError):
            http_retry.get('https://example.supabase.co/rest/v1/ledger', request=get)
        get.assert_called_once()
        sleep.assert_not_called()

    def test_invalid_payload_is_not_replaced_or_retried(self):
        response = self.response()
        response._content = b'not JSON'
        get = Mock(return_value=response)
        with self.assertRaises(ValueError):
            http_retry.get(URL, request=get).json()
        get.assert_called_once()

    @patch('data_pipeline.http_retry.time.sleep')
    def test_frozen_collector_transport_is_restored_even_on_failure(self, sleep):
        response = self.response()
        with patch('requests.get', side_effect=[requests.ConnectionError('DNS'), response]) as get:
            with self.assertRaisesRegex(ValueError, 'collector error'):
                with runtime.source_retries():
                    self.assertIs(requests.get(URL, timeout=40), response)
                    raise ValueError('collector error')
            self.assertIs(requests.get, get)
            self.assertEqual(get.call_count, 2)

    def test_transport_and_parent_amendments_are_intact(self):
        runtime.verify_amendment()
        for name in ['paper_simulation', 'paper_positive15']:
            registration = json.loads((runtime.v2.v1.ROOT / name / 'registration.json').read_text(encoding='utf8'))
            runtime.v2.verify_amendment(name, registration)

    def test_changed_helper_is_rejected(self):
        with patch.object(runtime.http_retry, '__file__', __file__):
            with self.assertRaisesRegex(ValueError, 'register a new version'):
                runtime.verify_amendment()


if __name__ == '__main__':
    unittest.main()
