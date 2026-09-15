import json
import os
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, panel INTEGER, state TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, kind TEXT NOT NULL, opening INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, kind TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL CHECK(kind IN ('income','expense','transfer')), amount INTEGER NOT NULL CHECK(amount>0), account INTEGER NOT NULL REFERENCES accounts(id), target INTEGER REFERENCES accounts(id), category INTEGER REFERENCES categories(id), day TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', source INTEGER, UNIQUE(user,source));
CREATE INDEX IF NOT EXISTS entries_user_day ON entries(user,day);
CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, target INTEGER NOT NULL CHECK(target>0), account INTEGER NOT NULL UNIQUE REFERENCES accounts(id), deadline TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budgets(user INTEGER NOT NULL REFERENCES users(id), category INTEGER NOT NULL REFERENCES categories(id), month TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), PRIMARY KEY(user,category,month));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ui_panels(user INTEGER PRIMARY KEY REFERENCES users(id), revision TEXT NOT NULL, routes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handled_updates(user INTEGER PRIMARY KEY REFERENCES users(id), last_update INTEGER NOT NULL);
'''


def is_remote_database(path):
    return str(path).startswith('libsql://')


def database_from_env(environ=None):
    """Create the persistent store selected by environment variables."""
    environ = os.environ if environ is None else environ
    remote = environ.get('TURSO_DATABASE_URL', '').strip()
    if remote:
        return Ledger(remote, environ.get('TURSO_AUTH_TOKEN', '').strip())
    return Ledger(environ.get('DATABASE_PATH', 'data/expense.db'))


def money(value):
    try:
        amount = Decimal(value.replace(' ', '').replace(',', '.'))
        if not amount.is_finite() or amount <= 0 or amount > 10**12 or amount * 100 != (amount * 100).to_integral_value():
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError('Введите сумму больше нуля, максимум с двумя знаками после запятой.')


def rub(amount):
    return f'{amount / 100:,.2f}'.replace(',', ' ').replace('.', ',') + ' ₽'


def period(key, today):
    if key == 'week':
        start = today - timedelta(days=today.weekday())
    elif key == 'month':
        start = today.replace(day=1)
    else:
        start = today - timedelta(days=29)
    return start, today


def growth(current, previous):
    if not previous:
        return 'нет базы сравнения' if current else '0%'
    return f'{(current - previous) / abs(previous) * 100:+.1f}%'


class Ledger:
    def __init__(self, path='data/expense.db', auth_token=''):
        self.remote = is_remote_database(path)
        if '://' in str(path) and not self.remote:
            raise ValueError('Поддерживается только адрес Turso формата libsql://...')
        if self.remote:
            if not auth_token:
                raise ValueError('Для Turso требуется TURSO_AUTH_TOKEN.')
            try:
                import libsql
            except ImportError:
                raise RuntimeError('Установите зависимости из requirements.txt для подключения к Turso.') from None
            self.db = libsql.connect(database=path, auth_token=auth_token)
        else:
            if path != ':memory:':
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        if not self.remote:
            self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)
        self.db.commit()
        # Базы, созданные до появления начального остатка, не имеют этой
        # колонки.  Делаем миграцию на лету, сохраняя существующие счета.
        account_columns = {row['name'] for row in self.rows('PRAGMA table_info(accounts)')}
        if 'opening' not in account_columns:
            with self.db:
                self.db.execute('ALTER TABLE accounts ADD COLUMN opening INTEGER NOT NULL DEFAULT 0')

    def rows(self, sql, args=()):
        cursor = self.db.execute(sql, args)
        names = [column[0] for column in (cursor.description or ())]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def user(self, uid):
        if not self.rows('SELECT id FROM users WHERE id=?', (uid,)):
            with self.db:
                self.db.execute('INSERT INTO users(id) VALUES(?)', (uid,))
                self.db.execute("INSERT INTO accounts(user,name,kind) VALUES(?, 'Основной', 'Обычный')", (uid,))
                for kind, names in [('expense', ['Продукты', 'Кафе', 'Транспорт', 'Дом', 'Здоровье', 'Покупки', 'Другое']), ('income', ['Зарплата', 'Подработка', 'Проценты', 'Другое'])]:
                    self.db.executemany('INSERT INTO categories(user,name,kind) VALUES(?,?,?)', [(uid, name, kind) for name in names])
        return self.rows('SELECT * FROM users WHERE id=?', (uid,))[0]

    def state(self, uid, state):
        with self.db:
            self.db.execute('UPDATE users SET state=? WHERE id=?', (json.dumps(state, ensure_ascii=False), uid))

    def owned(self, table, uid, ident):
        if table not in ('accounts', 'categories', 'entries', 'goals'):
            raise ValueError('Неизвестный объект.')
        found = self.rows(f'SELECT * FROM {table} WHERE id=? AND user=?', (int(ident), uid))
        if not found:
            raise ValueError('Запись не найдена. Откройте раздел заново.')
        return found[0]

    def accounts(self, uid):
        items = self.rows('SELECT * FROM accounts WHERE user=? ORDER BY id', (uid,))
        for item in items:
            item['balance'] = self.balance(uid, item['id'])
        return items

    def balance(self, uid, account, through='9999-12-31'):
        item = self.owned('accounts', uid, account)
        total = self.rows('''SELECT COALESCE(SUM(CASE WHEN target=? THEN amount WHEN kind='income' THEN amount ELSE -amount END),0) total FROM entries WHERE user=? AND day<=? AND (account=? OR target=?)''', (account, uid, through, account, account))[0]['total']
        return item['opening'] + total

    def categories(self, uid, kind):
        return self.rows('SELECT * FROM categories WHERE user=? AND kind=? AND archived=0 ORDER BY id', (uid, kind))

    def save_entry(self, uid, item, source=None, edit=None):
        amount = int(item['amount'])
        if amount <= 0 or amount > 10**14:
            raise ValueError('Некорректная сумма.')
        self.owned('accounts', uid, item['account'])
        if item['kind'] == 'transfer':
            self.owned('accounts', uid, item['target'])
            if item['account'] == item['target']:
                raise ValueError('Выберите разные счета.')
            target, category_id = item['target'], None
        elif item['kind'] in ('income', 'expense'):
            category = self.owned('categories', uid, item['category'])
            if category['kind'] != item['kind'] or category['archived']:
                raise ValueError('Выберите действующую категорию нужного типа.')
            target, category_id = None, item['category']
        else:
            raise ValueError('Неизвестный тип операции.')
        date.fromisoformat(item['day'])
        values = (item['kind'], amount, item['account'], target, category_id, item['day'], item.get('note', '')[:200])
        with self.db:
            if edit:
                self.owned('entries', uid, edit)
                self.db.execute('UPDATE entries SET kind=?,amount=?,account=?,target=?,category=?,day=?,note=? WHERE id=? AND user=?', (*values, edit, uid))
                return int(edit)
            else:
                cursor = self.db.execute('INSERT INTO entries(kind,amount,account,target,category,day,note,user,source) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user,source) DO NOTHING', (*values, uid, source))
                if source is not None:
                    return self.rows('SELECT id FROM entries WHERE user=? AND source=?', (uid,source))[0]['id']
                return cursor.lastrowid

    def stats(self, uid, start, end, account=None):
        if start > end or (end-start).days > 3660:
            raise ValueError('Период должен быть от 1 дня до 10 лет.')
        length = (end-start).days + 1
        previous_start, previous_end = start-timedelta(days=length), start-timedelta(days=1)
        clause, args = (' AND account=?', (account,)) if account else ('', ())
        if account:
            self.owned('accounts', uid, account)
        def totals(a, b):
            rows = self.rows('SELECT kind,SUM(amount) total FROM entries WHERE user=? AND day BETWEEN ? AND ?' + clause + ' GROUP BY kind', (uid, a.isoformat(), b.isoformat(), *args))
            values = {r['kind']: r['total'] for r in rows}
            return {k: values.get(k, 0) for k in ('income', 'expense')}
        result = totals(start, end)
        result['previous'] = totals(previous_start, previous_end)
        result['previous_start'], result['previous_end'] = previous_start.isoformat(), previous_end.isoformat()
        result['net'] = result['income'] - result['expense']
        result['daily_average'] = result['expense'] // length
        result['savings_rate'] = round(result['net']/result['income']*100, 1) if result['income'] else None
        result['categories'] = self.rows('''SELECT c.name,e.kind,SUM(e.amount) total,COUNT(*) count FROM entries e JOIN categories c ON c.id=e.category WHERE e.user=? AND e.day BETWEEN ? AND ?''' + (' AND e.account=?' if account else '') + ' GROUP BY c.id,e.kind ORDER BY total DESC', (uid, start.isoformat(), end.isoformat(), *args))
        result['daily'] = self.rows("SELECT day,SUM(CASE WHEN kind='income' THEN amount WHEN kind='expense' THEN -amount ELSE 0 END) net FROM entries WHERE user=? AND day BETWEEN ? AND ?" + clause + ' GROUP BY day ORDER BY day', (uid, start.isoformat(), end.isoformat(), *args))
        if account:
            result['opening'] = self.balance(uid, account, previous_end.isoformat())
            result['closing'] = self.balance(uid, account, end.isoformat())
            result['movement'] = result['closing'] - result['opening']
            result['balance_history'] = [{'day': r['day'], 'balance': self.balance(uid, account, r['day'])} for r in self.rows('SELECT DISTINCT day FROM entries WHERE user=? AND day BETWEEN ? AND ? AND (account=? OR target=?) ORDER BY day', (uid,start.isoformat(),end.isoformat(),account,account))]
        return result

    def delete(self, table, uid, ident):
        self.owned(table, uid, ident)
        with self.db:
            if table == 'categories':
                self.db.execute('UPDATE categories SET archived=1 WHERE id=? AND user=?', (ident, uid))
            elif table == 'accounts':
                if len(self.accounts(uid)) <= 1:
                    raise ValueError('Нужно оставить хотя бы один счёт.')
                if self.rows('SELECT id FROM entries WHERE user=? AND (account=? OR target=?)', (uid,ident,ident)) or self.rows('SELECT id FROM goals WHERE account=?', (ident,)):
                    raise ValueError('Счёт используется в операциях или цели. Сначала измените их.')
                self.db.execute('DELETE FROM accounts WHERE id=? AND user=?', (ident,uid))
            else:
                self.db.execute(f'DELETE FROM {table} WHERE id=? AND user=?', (ident,uid))
