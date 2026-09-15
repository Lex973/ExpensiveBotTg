import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from expense.webhook import WebhookError, parse_update, process_update, validate_settings


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


if __name__ == '__main__':
    unittest.main()
