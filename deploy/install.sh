#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/install.sh"
  exit 1
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${project_dir}/run.py" || ! -d "${project_dir}/expense" ]]; then
  echo "Project files were not found."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3
fi

if ! id expensebot >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/expense-bot --shell /usr/sbin/nologin expensebot
fi

install -d -o root -g root -m 0755 /opt/expense-bot /opt/expense-bot/expense
install -o root -g root -m 0644 "${project_dir}/run.py" /opt/expense-bot/run.py
find "${project_dir}/expense" -maxdepth 1 -type f -name '*.py' -exec install -o root -g root -m 0644 '{}' /opt/expense-bot/expense/ \;
install -o root -g root -m 0644 "${project_dir}/deploy/expense-bot.service" /etc/systemd/system/expense-bot.service

if [[ ! -f /etc/expense-bot.env ]]; then
  install -o root -g root -m 0600 "${project_dir}/deploy/server.env.example" /etc/expense-bot.env
  echo "Created /etc/expense-bot.env. Add the Telegram token before starting."
fi

systemctl daemon-reload

if grep -q '^TELEGRAM_BOT_TOKEN=PASTE_TOKEN_HERE$' /etc/expense-bot.env; then
  echo "Installation complete. Next: sudo nano /etc/expense-bot.env"
  echo "Then run: sudo systemctl enable --now expense-bot"
  exit 0
fi

systemctl enable --now expense-bot
systemctl --no-pager --full status expense-bot
