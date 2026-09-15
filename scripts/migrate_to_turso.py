"""Copy an existing local Expense Bot SQLite database into an empty Turso DB."""
import argparse
import os
from pathlib import Path

from expense.bot import load_env
from expense.core import Ledger


TABLES = ('users', 'accounts', 'categories', 'entries', 'goals', 'budgets',
          'meta', 'ui_panels', 'handled_updates')


def copy_database(source_path):
    load_env()
    url = os.getenv('TURSO_DATABASE_URL', '').strip()
    token = os.getenv('TURSO_AUTH_TOKEN', '').strip()
    if not url or not token:
        raise SystemExit('Добавьте TURSO_DATABASE_URL и TURSO_AUTH_TOKEN в .env.')
    if not Path(source_path).is_file():
        raise SystemExit(f'Локальная база не найдена: {source_path}')
    source = Ledger(source_path)
    target = Ledger(url, token)
    try:
        occupied = [table for table in TABLES if target.rows(f'SELECT 1 FROM {table} LIMIT 1')]
        if occupied:
            raise SystemExit('Turso должна быть пустой. Уже заполнены таблицы: ' + ', '.join(occupied))
        with target.db:
            for table in TABLES:
                columns = [row['name'] for row in source.rows(f'PRAGMA table_info({table})')]
                rows = source.db.execute(f'SELECT * FROM {table}').fetchall()
                if not rows:
                    continue
                names = ','.join(columns)
                placeholders = ','.join('?' for _ in columns)
                target.db.executemany(
                    f'INSERT INTO {table} ({names}) VALUES ({placeholders})',
                    [tuple(row) for row in rows])
        print('Перенос завершён. Скопировано строк:', sum(
            len(source.rows(f'SELECT * FROM {table}')) for table in TABLES))
    finally:
        source.db.close()
        target.db.close()


def main():
    parser = argparse.ArgumentParser(description='Перенести локальную SQLite в пустую Turso.')
    parser.add_argument('source', nargs='?', default='data/expense.db')
    args = parser.parse_args()
    copy_database(args.source)


if __name__ == '__main__':
    main()
