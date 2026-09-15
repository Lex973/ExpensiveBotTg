"""Stateless Telegram webhook adapter for Vercel Functions."""
import asyncio
import hmac
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from .bot import Bot, Telegram
from .core import Ledger


SECRET_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,256}$')
WEBHOOK_PATH = '/api/webhook'
MAX_BODY = 1_000_000

log = logging.getLogger('expense.webhook')


class WebhookError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def validate_settings(environ):
    required = ('TELEGRAM_BOT_TOKEN', 'TURSO_DATABASE_URL',
                'TURSO_AUTH_TOKEN', 'TELEGRAM_WEBHOOK_SECRET')
    missing = [name for name in required if not environ.get(name, '').strip()]
    if missing:
        raise WebhookError(500, 'Не заданы переменные окружения: ' + ', '.join(missing))
    secret = environ['TELEGRAM_WEBHOOK_SECRET'].strip()
    if not SECRET_PATTERN.fullmatch(secret):
        raise WebhookError(500, 'TELEGRAM_WEBHOOK_SECRET имеет недопустимый формат.')
    if not environ['TURSO_DATABASE_URL'].startswith('libsql://'):
        raise WebhookError(500, 'TURSO_DATABASE_URL должен начинаться с libsql://.')
    try:
        offset = int(environ.get('UTC_OFFSET_HOURS', '5'))
    except ValueError:
        raise WebhookError(500, 'UTC_OFFSET_HOURS должен быть целым числом.') from None
    if not -23 <= offset <= 23:
        raise WebhookError(500, 'UTC_OFFSET_HOURS должен быть от -23 до 23.')
    return secret, offset


def parse_update(body):
    if len(body) > 1_000_000:
        raise WebhookError(413, 'Слишком большой запрос.')
    try:
        update = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WebhookError(400, 'Некорректный JSON.') from None
    if not isinstance(update, dict) or not isinstance(update.get('update_id'), int):
        raise WebhookError(400, 'Некорректное обновление Telegram.')
    return update


def process_update(body, provided_secret, environ=None):
    """Validate and synchronously process one Telegram webhook delivery."""
    environ = os.environ if environ is None else environ
    expected_secret, offset = validate_settings(environ)
    if not hmac.compare_digest(provided_secret or '', expected_secret):
        raise WebhookError(403, 'Неверный секрет webhook.')
    update = parse_update(body)
    store = Ledger(environ['TURSO_DATABASE_URL'].strip(),
                   environ['TURSO_AUTH_TOKEN'].strip())
    tz = timezone(timedelta(hours=offset))
    bot = Bot(store, Telegram(environ['TELEGRAM_BOT_TOKEN'].strip()),
              lambda: datetime.now(tz).date(),
              environ.get('AI_ENDPOINT', '').strip(),
              environ.get('AI_API_KEY', '').strip())
    try:
        asyncio.run(bot.handle(update))
    finally:
        store.db.close()


def _json_response(start_response, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    start_response(status, [('Content-Type', 'application/json; charset=utf-8'),
                            ('Content-Length', str(len(body))),
                            ('Cache-Control', 'no-store')])
    return [body]


def application(environ, start_response):
    """Dependency-free WSGI entry point loaded by Vercel from app.py."""
    if environ.get('PATH_INFO', '').rstrip('/') != WEBHOOK_PATH:
        return _json_response(start_response, '404 Not Found',
                              {'ok': False, 'error': 'Не найдено.'})
    method = environ.get('REQUEST_METHOD', 'GET')
    if method in ('GET', 'HEAD'):
        return _json_response(start_response, '200 OK',
                              {'ok': True, 'service': 'expense-bot-webhook'})
    if method != 'POST':
        start_response('405 Method Not Allowed', [('Allow', 'GET, HEAD, POST'),
                                                  ('Content-Length', '0')])
        return [b'']
    try:
        length = int(environ.get('CONTENT_LENGTH') or '0')
    except ValueError:
        return _json_response(start_response, '400 Bad Request',
                              {'ok': False, 'error': 'Некорректная длина запроса.'})
    if length <= 0 or length > MAX_BODY:
        status = '413 Payload Too Large' if length > MAX_BODY else '400 Bad Request'
        return _json_response(start_response, status,
                              {'ok': False, 'error': 'Некорректный размер запроса.'})
    body = environ['wsgi.input'].read(length)
    try:
        process_update(body, environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'))
    except WebhookError as error:
        return _json_response(start_response, f'{error.status} Error',
                              {'ok': False, 'error': str(error)})
    except Exception:
        log.exception('Webhook update failed')
        return _json_response(start_response, '500 Internal Server Error',
                              {'ok': False, 'error': 'Внутренняя ошибка.'})
    return _json_response(start_response, '200 OK', {'ok': True})
