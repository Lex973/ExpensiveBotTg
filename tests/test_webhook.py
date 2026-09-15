import io
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from expense.webhook import (WebhookError, application, parse_update,
                             process_update, validate_settings)


SETTINGS = {
    'TELEGRAM_BOT_TOKEN': '123:token',
    'TURSO_DATABASE_URL': 'libsql://expense-example.turso.io',
    'TURSO_AUTH_TOKEN': 'database-token',
    'TELEGRAM_WEBHOOK_SECRET': 'safe_test-secret',
    'UTC_OFFSET_HOURS': '5',
}


class WebhookTests(unittest.TestCase):
    def test_settings_require_remote_database_and_valid_secret(self):
        self.assertEqual(validate_settings(SETTINGS), ('safe_test-secret', 5))
        for changes in (
            {'TURSO_DATABASE_URL': ''},
            {'TURSO_DATABASE_URL': 'https://expense-example.turso.io'},
            {'TELEGRAM_WEBHOOK_SECRET': 'bad secret'},
            {'UTC_OFFSET_HOURS': '24'},
        ):
            with self.subTest(changes=changes), self.assertRaises(WebhookError):
                validate_settings({**SETTINGS, **changes})

    def test_invalid_secret_is_rejected_before_database_connection(self):
        with patch('expense.webhook.Ledger') as ledger, self.assertRaises(WebhookError) as caught:
            process_update(b'{"update_id": 1}', 'wrong', SETTINGS)
        self.assertEqual(caught.exception.status, 403)
        ledger.assert_not_called()

    def test_invalid_payload_is_rejected(self):
        for body in (b'not-json', b'[]', b'{"message": {}}'):
            with self.subTest(body=body), self.assertRaises(WebhookError) as caught:
                parse_update(body)
            self.assertEqual(caught.exception.status, 400)

    def test_valid_delivery_uses_turso_and_closes_connection(self):
        store = Mock()
        store.db = Mock()
        bot = Mock()
        bot.handle = AsyncMock()
        payload = {'update_id': 42, 'message': {'text': '/start'}}
        with patch('expense.webhook.Ledger', return_value=store) as ledger, \
                patch('expense.webhook.Telegram') as telegram, \
                patch('expense.webhook.Bot', return_value=bot):
            process_update(json.dumps(payload).encode(), 'safe_test-secret', SETTINGS)
        ledger.assert_called_once_with(SETTINGS['TURSO_DATABASE_URL'], SETTINGS['TURSO_AUTH_TOKEN'])
        telegram.assert_called_once_with(SETTINGS['TELEGRAM_BOT_TOKEN'])
        bot.handle.assert_awaited_once_with(payload)
        store.db.close.assert_called_once_with()


def call_wsgi(method, path, body=b'', secret=None):
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': path,
               'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
    if secret is not None:
        environ['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] = secret
    captured = {}

    def start_response(status, headers):
        captured['status'] = status
        captured['headers'] = dict(headers)

    payload = b''.join(application(environ, start_response))
    return captured['status'], captured['headers'], payload


class WsgiApplicationTests(unittest.TestCase):
    def test_app_module_exports_wsgi_entrypoint(self):
        import app
        self.assertIs(app.app, application)

    def test_get_reports_service_status_only_on_webhook_path(self):
        status, headers, body = call_wsgi('GET', '/api/webhook')
        self.assertEqual(status, '200 OK')
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(json.loads(body), {'ok': True, 'service': 'expense-bot-webhook'})
        self.assertEqual(call_wsgi('GET', '/')[0], '404 Not Found')
        self.assertEqual(call_wsgi('DELETE', '/api/webhook')[0], '405 Method Not Allowed')

    def test_post_validates_size_and_forwards_secret(self):
        self.assertEqual(call_wsgi('POST', '/api/webhook')[0], '400 Bad Request')
        with patch('expense.webhook.process_update') as process:
            status, _, body = call_wsgi('POST', '/api/webhook', b'{"update_id": 1}', 'secret')
        process.assert_called_once_with(b'{"update_id": 1}', 'secret')
        self.assertEqual((status, json.loads(body)), ('200 OK', {'ok': True}))

    def test_post_maps_webhook_errors_to_http_status(self):
        with patch('expense.webhook.process_update', side_effect=WebhookError(403, 'Нет')):
            status, _, body = call_wsgi('POST', '/api/webhook', b'{}', 'wrong')
        self.assertTrue(status.startswith('403'))
        self.assertEqual(json.loads(body), {'ok': False, 'error': 'Нет'})
        with patch('expense.webhook.process_update', side_effect=RuntimeError('boom')),                 self.assertLogs('expense.webhook', level='ERROR'):
            status, _, _ = call_wsgi('POST', '/api/webhook', b'{}', 'x')
        self.assertEqual(status, '500 Internal Server Error')


if __name__ == '__main__':
    unittest.main()
