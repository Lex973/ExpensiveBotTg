"""Vercel entry point for Telegram webhook deliveries."""
import json
import logging
from http.server import BaseHTTPRequestHandler

from expense.webhook import WebhookError, process_update


log = logging.getLogger('expense.webhook')


class handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_json(200, {'ok': True, 'service': 'expense-bot-webhook'})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_json(400, {'ok': False, 'error': 'Некорректная длина запроса.'})
            return
        if length <= 0 or length > 1_000_000:
            status = 413 if length > 1_000_000 else 400
            self.send_json(status, {'ok': False, 'error': 'Некорректный размер запроса.'})
            return
        body = self.rfile.read(length)
        try:
            process_update(body, self.headers.get('X-Telegram-Bot-Api-Secret-Token'))
        except WebhookError as error:
            self.send_json(error.status, {'ok': False, 'error': str(error)})
            return
        except Exception:
            log.exception('Webhook update failed')
            self.send_json(500, {'ok': False, 'error': 'Внутренняя ошибка.'})
            return
        self.send_json(200, {'ok': True})
