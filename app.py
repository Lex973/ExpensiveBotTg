"""Vercel entry point: routes every request to the Telegram webhook WSGI app."""
from expense.webhook import application

app = application
