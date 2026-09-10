#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash deploy/update.sh"
  exit 1
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install -d -o root -g root -m 0755 /opt/expense-bot /opt/expense-bot/expense
install -o root -g root -m 0644 "${project_dir}/run.py" /opt/expense-bot/run.py
find "${project_dir}/expense" -maxdepth 1 -type f -name '*.py' -exec install -o root -g root -m 0644 '{}' /opt/expense-bot/expense/ \;
install -o root -g root -m 0644 "${project_dir}/deploy/expense-bot.service" /etc/systemd/system/expense-bot.service
systemctl daemon-reload
systemctl restart expense-bot
systemctl --no-pager --full status expense-bot
