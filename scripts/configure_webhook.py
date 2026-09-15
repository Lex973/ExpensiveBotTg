"""Register the production Vercel endpoint with Telegram."""
import argparse
import asyncio
import os
import re
from urllib.parse import urlsplit

from expense.bot import Telegram, load_env


SECRET_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,256}$')


def endpoint(value):
    value = value.rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('Укажите HTTPS-адрес production deployment без query и fragment.')
    if parsed.path in ('', '/'):
        value += '/api/webhook'
    return value


async def configure(url, drop_pending):
    load_env()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    secret = os.getenv('TELEGRAM_WEBHOOK_SECRET', '').strip()
    if not token:
        raise SystemExit('Добавьте TELEGRAM_BOT_TOKEN в .env.')
    if not SECRET_PATTERN.fullmatch(secret):
        raise SystemExit('Добавьте TELEGRAM_WEBHOOK_SECRET: 1–256 символов A-Z, a-z, 0-9, _ или -.')
    api = Telegram(token)
    await api.call('setWebhook', url=endpoint(url), secret_token=secret,
                   max_connections=1, allowed_updates=['message', 'callback_query'],
                   drop_pending_updates=drop_pending)
    await api.call('setMyCommands', commands=[
        {'command': 'start', 'description': 'Обзор финансов'},
        {'command': 'cancel', 'description': 'Отменить ввод'},
        {'command': 'help', 'description': 'Как пользоваться'},
    ])
    info = await api.call('getWebhookInfo')
    print('Webhook установлен:', endpoint(url))
    print('Сообщений в очереди Telegram:', info.get('pending_update_count', 0))


async def remove(drop_pending):
    load_env()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Добавьте TELEGRAM_BOT_TOKEN в .env.')
    await Telegram(token).call('deleteWebhook', drop_pending_updates=drop_pending)
    print('Webhook удалён. Теперь можно снова запускать локальный polling.')


def main():
    parser = argparse.ArgumentParser(description='Настроить Telegram webhook на Vercel.')
    parser.add_argument('url', nargs='?', help='Например: https://expense-bot.vercel.app')
    parser.add_argument('--delete', action='store_true', help='Удалить webhook и вернуться к polling.')
    parser.add_argument('--drop-pending-updates', action='store_true',
                        help='Удалить накопившиеся необработанные сообщения Telegram.')
    args = parser.parse_args()
    if args.delete:
        asyncio.run(remove(args.drop_pending_updates))
    elif args.url:
        asyncio.run(configure(args.url, args.drop_pending_updates))
    else:
        parser.error('укажите URL deployment или --delete')


if __name__ == '__main__':
    main()
