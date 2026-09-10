"""User journeys with an in-memory ledger and a fake Telegram transport."""
import json
import unittest
from datetime import date

from expense.bot import APIError, Bot
from expense.core import Ledger


class RecordingAPI:
    def __init__(self):
        self.calls = []
        self.next_message = 100
        self.rows = {}

    async def call(self, method, **payload):
        self.calls.append((method, payload))
        if method in ('sendMessage', 'editMessageText'):
            self.rows[payload['chat_id']] = payload['reply_markup']['inline_keyboard']
        if method == 'sendMessage':
            self.next_message += 1
            return {'message_id': self.next_message}
        return {'message_id': payload.get('message_id', self.next_message)}


class UserScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Ledger(':memory:')
        self.api = RecordingAPI()
        self.bot = Bot(self.store, self.api, lambda: date(2026, 9, 10))
        self.sequence = 0
        await self.message('/start')
        self.account = self.store.accounts(1)[0]['id']

    async def asyncTearDown(self):
        self.store.db.close()

    async def message(self, value, uid=1):
        self.sequence += 1
        await self.bot.handle({'update_id': self.sequence, 'message': {
            'message_id': self.sequence, 'chat': {'id': uid, 'type': 'private'},
            'text': value}})

    def route(self, prefix, uid=1):
        for row in self.api.rows[uid]:
            for item in row:
                route = item['callback_data']
                plain = route.split('|', 1)[-1]
                if plain == prefix or plain.startswith(prefix + ':'):
                    return route
        self.fail(f'No visible route {prefix!r}: {self.api.rows[uid]!r}')

    async def callback(self, route, uid=1, panel=None, sender=None):
        if '|' not in route:
            for row in self.api.rows.get(uid, []):
                for item in row:
                    if '|' in item['callback_data']:
                        route = item['callback_data'].split('|', 1)[0] + '|' + route
                        break
                if '|' in route:
                    break
        self.sequence += 1
        await self.bot.handle({'update_id': self.sequence, 'callback_query': {
            'id': str(self.sequence), 'from': {'id': uid if sender is None else sender},
            'message': {'message_id': panel if panel is not None else self.store.user(uid)['panel'],
                        'chat': {'id': uid, 'type': 'private'}}, 'data': route}})

    async def click(self, prefix, uid=1):
        await self.callback(self.route(prefix, uid), uid)

    async def open_screen(self, route, uid=1):
        """Render a starting screen; all subsequent interactions use actual buttons."""
        await self.bot.panel(uid, *self.bot.ui.render(uid, route))

    def state(self, uid=1):
        return json.loads(self.store.user(uid)['state'])

    def entries(self, uid=1):
        return self.store.rows('SELECT * FROM entries WHERE user=? ORDER BY id', (uid,))

    def seed(self, kind='income', amount=10000):
        return self.store.save_entry(1, dict(kind=kind, amount=amount,
            account=self.account, category=self.store.categories(1, kind)[0]['id'],
            day='2026-09-09', note='Original'))

    async def draft(self, kind='income', edit=None, steps=4, uid=1):
        await self.open_screen(f'entry:{edit}' if edit else 'home', uid)
        await self.click(f'edit:{edit}' if edit else f'new:{kind}', uid)
        if steps >= 1:
            await self.message('250,50', uid)
        if steps >= 2:
            await self.click('pick:account', uid)
        if steps >= 3:
            await self.click('pick:category', uid)
        if steps >= 4:
            await self.message('10.09.2026 Changed', uid)

    async def test_cancel_creation_at_every_step_for_both_kinds(self):
        for kind in ('income', 'expense'):
            for step in range(5):
                with self.subTest(kind=kind, step=step):
                    await self.draft(kind, steps=step)
                    await self.message('/cancel')
                    self.assertFalse(self.entries())
                    self.assertFalse(self.state())
                    self.assertEqual(self.store.balance(1, self.account), 0)

    async def test_cancel_edit_at_every_step_preserves_original(self):
        for kind in ('income', 'expense'):
            ident = self.seed(kind)
            before = dict(self.store.owned('entries', 1, ident))
            for step in range(5):
                with self.subTest(kind=kind, step=step):
                    await self.draft(kind, edit=ident, steps=step)
                    await self.message('/cancel')
                    self.assertEqual(dict(self.store.owned('entries', 1, ident)), before)
                    self.assertFalse(self.state())

    async def test_navigation_discards_unsaved_draft(self):
        for route in ('home', 'accounts', 'history:0', 'categories', 'goals', 'analytics:month', 'help'):
            with self.subTest(route=route):
                await self.draft()
                await self.open_screen(route)
                await self.callback('save')
                self.assertFalse(self.entries())
                self.assertNotEqual(self.state().get('flow'), 'entry')

    async def test_cancel_button_discards_draft(self):
        await self.draft()
        cancel = next(b['callback_data'] for row in self.api.rows[1] for b in row if 'Отмена' in b['text'])
        await self.callback(cancel)
        await self.message('999')
        self.assertFalse(self.entries())
        self.assertFalse(self.state())

    async def test_save_edit_changes_original_without_duplicate(self):
        ident = self.seed()
        await self.draft(edit=ident)
        save = self.route('save')
        await self.callback(save)
        await self.callback(save)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.entries()[0]['id'], ident)
        self.assertEqual(self.entries()[0]['amount'], 25050)
        self.assertEqual(self.entries()[0]['note'], 'Changed')
        self.assertEqual(self.store.balance(1, self.account), 25050)

    async def test_duplicate_save_does_not_duplicate_income(self):
        await self.draft()
        save = self.route('save')
        await self.callback(save)
        await self.callback(save)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.store.balance(1, self.account), 25050)

    async def test_save_from_previous_draft_cannot_save_new_draft(self):
        await self.draft()
        stale_save = self.route('save')
        await self.message('/cancel')
        await self.draft('expense')
        await self.callback(stale_save)
        self.assertFalse(self.entries(), 'A stale income Save must not commit a later expense draft')

    async def test_old_message_callback_does_not_change_draft(self):
        await self.draft(steps=1)
        before = self.state()
        await self.callback('home', panel=self.store.user(1)['panel'] - 1)
        self.assertEqual(self.state(), before)

    async def test_duplicate_account_selection_does_not_skip_category(self):
        await self.draft(steps=1)
        pick = self.route('pick:account')
        await self.callback(pick)
        await self.callback(pick)
        self.assertEqual(self.state()['step'], 'category')
        self.assertFalse(self.entries())

    async def test_wrong_category_kind_rejected_without_losing_draft(self):
        await self.draft(steps=2)
        category = self.store.categories(1, 'expense')[0]['id']
        await self.callback(f'pick:category:{category}')
        self.assertEqual(self.state()['step'], 'category')
        self.assertFalse(self.entries())

    async def test_invalid_amounts_can_be_corrected(self):
        await self.draft(steps=0)
        for value in ('0', '-10', 'NaN', '1.001', 'abc'):
            await self.message(value)
            self.assertEqual(self.state()['step'], 'amount')
            self.assertFalse(self.entries())
        await self.message('10,25')
        self.assertEqual(self.state()['amount'], 1025)

    async def test_invalid_dates_can_be_corrected(self):
        await self.draft(steps=3)
        for value in ('31.02.2026', '11.09.2026', 'nonsense'):
            await self.message(value)
            self.assertEqual(self.state()['step'], 'details')
            self.assertFalse(self.entries())
        await self.message('09.09.2026 valid')
        await self.click('save')
        self.assertEqual(self.entries()[0]['day'], '2026-09-09')

    async def test_today_remains_available_after_invalid_date(self):
        await self.draft(steps=3)
        await self.message('31.02.2026')
        await self.click('today')
        await self.click('save')
        self.assertEqual(self.entries()[0]['day'], '2026-09-10')

    async def test_replayed_text_cannot_fill_a_new_draft(self):
        await self.draft(steps=0)
        self.sequence += 1
        update = {'update_id': self.sequence, 'message': {
            'message_id': self.sequence, 'chat': {'id': 1, 'type': 'private'}, 'text': '200'}}
        await self.bot.handle(update)
        await self.message('/cancel')
        await self.draft('expense', steps=0)
        before = self.state()
        await self.bot.handle(update)
        self.assertEqual(self.state(), before, 'Replay must not set amount in an unrelated draft')
        self.assertFalse(self.entries())

    async def test_stale_account_selection_cannot_fill_new_draft(self):
        await self.draft(steps=1)
        old_pick = self.route('pick:account')
        await self.message('/cancel')
        await self.draft('expense', steps=1)
        before = self.state()
        await self.callback(old_pick)
        self.assertEqual(self.state(), before)

    async def test_restart_does_not_revalidate_previous_screen_buttons(self):
        await self.draft()
        old_save = self.route('save')
        await self.message('/cancel')
        await self.draft('expense')
        self.bot = Bot(self.store, self.api, lambda: date(2026, 9, 10))
        await self.callback(old_save)
        self.assertFalse(self.entries())
        await self.click('save')
        self.assertEqual(self.entries()[0]['kind'], 'expense')

    async def test_cancel_transfer_at_each_step_changes_neither_account(self):
        with self.store.db:
            target = self.store.db.execute(
                "INSERT INTO accounts(user,name,kind) VALUES(1,'Savings','Накопительный')").lastrowid
        for step in range(5):
            with self.subTest(step=step):
                await self.open_screen('home')
                await self.click('new:transfer')
                if step >= 1:
                    await self.message('100')
                if step >= 2:
                    await self.click(f'pick:account:{self.account}')
                if step >= 3:
                    await self.click(f'pick:target:{target}')
                if step >= 4:
                    await self.click('today')
                await self.message('/cancel')
                self.assertFalse(self.entries())
                self.assertEqual(self.store.balance(1, self.account), 0)
                self.assertEqual(self.store.balance(1, target), 0)

    async def test_delete_transfer_restores_both_balances(self):
        with self.store.db:
            target = self.store.db.execute(
                "INSERT INTO accounts(user,name,kind) VALUES(1,'Savings','Накопительный')").lastrowid
        ident = self.store.save_entry(1, dict(kind='transfer', amount=7000,
            account=self.account, target=target, day='2026-09-10'))
        await self.open_screen(f'entry:{ident}')
        await self.click('delete:entries')
        await self.click('confirm')
        self.assertEqual(self.store.balance(1, self.account), 0)
        self.assertEqual(self.store.balance(1, target), 0)
        self.assertFalse(self.entries())

    async def test_cancel_delete_invalidates_confirmation(self):
        ident = self.seed()
        await self.open_screen(f'entry:{ident}')
        await self.click(f'delete:entries:{ident}')
        confirm = self.route('confirm')
        cancel = next(b['callback_data'] for row in self.api.rows[1] for b in row if 'Отмена' in b['text'])
        await self.callback(cancel)
        await self.callback(confirm)
        self.assertEqual(len(self.entries()), 1)

    async def test_confirm_delete_is_idempotent_and_recomputes_balance(self):
        for kind in ('income', 'expense'):
            ident = self.seed(kind)
            await self.open_screen(f'entry:{ident}')
            await self.click(f'delete:entries:{ident}')
            confirm = self.route('confirm')
            await self.callback(confirm)
            await self.callback(confirm)
            self.assertFalse(self.entries())
            self.assertEqual(self.store.balance(1, self.account), 0)

    async def test_confirmation_for_another_entry_is_rejected(self):
        first, second = self.seed(), self.seed('expense')
        await self.open_screen(f'entry:{first}')
        await self.click(f'delete:entries:{first}')
        await self.callback(f'confirm:entries:{second}')
        self.assertEqual(len(self.entries()), 2)

    async def test_restart_keeps_draft_but_never_autosaves(self):
        await self.draft()
        before = self.state()
        self.bot = Bot(self.store, self.api, lambda: date(2026, 9, 10))
        self.assertFalse(self.entries())
        self.assertEqual(self.state(), before)
        await self.message('/cancel')
        self.assertFalse(self.entries())

    async def test_users_have_independent_drafts_and_balances(self):
        await self.message('/start', uid=2)
        await self.draft(uid=1)
        first = self.state(1)
        await self.draft('expense', uid=2)
        self.assertEqual(self.state(1), first)
        await self.click('save', uid=2)
        self.assertFalse(self.entries(1))
        self.assertEqual(len(self.entries(2)), 1)
        await self.click('save', uid=1)
        self.assertEqual(len(self.entries(1)), 1)

    async def test_foreign_sender_and_foreign_entry_cannot_mutate(self):
        ident = self.seed()
        await self.message('/start', uid=2)
        await self.callback(f'edit:{ident}', uid=2)
        await self.callback(f'delete:entries:{ident}', uid=2)
        await self.callback(f'confirm:entries:{ident}', uid=2)
        await self.draft(steps=1)
        before = self.state()
        await self.callback('home', sender=2)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.entries()[0]['amount'], 10000)

    async def test_empty_transfer_does_not_leave_unusable_form(self):
        await self.callback('new:transfer')
        await self.message('100')
        await self.click('pick:account')
        self.assertFalse(self.state())
        self.assertFalse(self.entries())
        self.assertTrue(any('form:account' in b['callback_data'] for row in self.api.rows[1] for b in row))

    async def test_cancel_account_category_goal_and_budget_forms(self):
        category = self.store.categories(1, 'expense')[0]['id']
        for route in ('form:account', 'form:category:expense', 'form:goal',
                      f'form:account:{self.account}', f'form:rename:{category}', f'form:budget:{category}'):
            with self.subTest(route=route):
                before = {table: [dict(r) for r in self.store.rows(f'SELECT * FROM {table}')]
                          for table in ('accounts', 'categories', 'goals', 'budgets')}
                await self.open_screen(route)
                await self.message('/cancel')
                await self.message('Unintended text')
                after = {table: [dict(r) for r in self.store.rows(f'SELECT * FROM {table}')]
                         for table in before}
                self.assertEqual(after, before)
                self.assertFalse(self.state())

    async def test_revise_then_cancel_discards_changes_for_new_and_existing_entry(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                ident = self.seed() if existing else None
                before = [dict(r) for r in self.entries()]
                await self.draft(edit=ident)
                await self.click('revise')
                await self.message('123,45')
                await self.message('/cancel')
                self.assertEqual(self.entries(), before)
                self.assertFalse(self.state())

    async def test_unsupported_early_date_keeps_draft_and_supported_boundary_saves(self):
        await self.draft(steps=3)
        for value in ('01.01.0001', '31.12.1899'):
            await self.message(value)
            self.assertEqual(self.state()['step'], 'details')
            self.assertFalse(self.entries())
        await self.message('01.01.1900 Historical')
        await self.click('save')
        self.assertEqual(self.entries()[0]['day'], '1900-01-01')

    async def test_account_picker_pagination_preserves_amount_and_reaches_every_account(self):
        with self.store.db:
            for index in range(19):
                self.store.db.execute("INSERT INTO accounts(user,name,kind) VALUES(1,?,'Обычный')",
                                      (f'Account {index:02}',))
        await self.draft(steps=1)
        expected = {a['id'] for a in self.store.accounts(1)}
        seen = set()
        for page in range(3):
            rows = self.api.rows[1]
            for row in rows:
                for item in row:
                    route = item['callback_data'].split('|', 1)[-1]
                    self.assertLessEqual(len(item['callback_data'].encode()), 64)
                    if route.startswith('pick:account:'):
                        seen.add(int(route.split(':')[2]))
            self.assertEqual(self.state()['amount'], 25050)
            self.assertEqual(self.state()['step'], 'account')
            if page < 2:
                await self.click(f'pickpage:{page + 1}')
        self.assertEqual(seen, expected)
        await self.click('pick:account')
        self.assertEqual(self.state()['step'], 'category')
        self.assertFalse(self.entries())

    async def test_edit_button_for_deleted_record_does_not_recreate_it(self):
        ident = self.seed()
        await self.open_screen(f'entry:{ident}')
        edit = self.route('edit')
        self.store.delete('entries', 1, ident)
        await self.callback(edit)
        self.assertFalse(self.entries())
        self.assertNotEqual(self.state().get('flow'), 'entry')
        await self.message('/start')
        await self.click('new:income')
        self.assertEqual(self.state()['step'], 'amount')

    async def test_missing_telegram_panel_is_replaced_and_old_buttons_rejected(self):
        old_panel = self.store.user(1)['panel']
        old_button = self.route('new:income')
        original = self.api.call
        failed = False

        async def missing_once(method, **payload):
            nonlocal failed
            if method == 'editMessageText' and not failed:
                failed = True
                raise APIError(400, 'message to edit not found')
            return await original(method, **payload)

        self.api.call = missing_once
        await self.click('new:expense')
        self.assertNotEqual(self.store.user(1)['panel'], old_panel)
        before = self.state()
        await self.callback(old_button, panel=old_panel)
        self.assertEqual(self.state(), before)
        await self.message('123')
        self.assertEqual(self.state()['amount'], 12300)

    async def test_transport_failure_after_save_cannot_duplicate_entry_on_retry(self):
        await self.draft()
        save = self.route('save')
        original = self.api.call

        async def unavailable(method, **payload):
            if method == 'editMessageText':
                raise APIError(500, 'Temporary server failure')
            return await original(method, **payload)

        self.api.call = unavailable
        with self.assertRaises(APIError):
            await self.callback(save)
        self.assertEqual(len(self.entries()), 1)
        self.api.call = original
        await self.callback(save)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.store.balance(1, self.account), 25050)


if __name__ == '__main__':
    unittest.main()
