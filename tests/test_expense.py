import asyncio
import json
import unittest
from datetime import date

from expense.core import Ledger, growth, money
from expense.ui import UI
from expense.bot import Bot


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.s=Ledger(':memory:'); self.s.user(1); self.s.user(2)
        self.a=self.s.accounts(1)[0]['id']
        with self.s.db:
            self.b=self.s.db.execute("INSERT INTO accounts(user,name,kind) VALUES(1,'Копилка','Накопительный')").lastrowid
        self.ui=UI(self.s,lambda:date(2026,9,10))

    def tearDown(self): self.s.db.close()

    def entry(self,kind,amount,day='2026-09-10',**kw):
        item=dict(kind=kind,amount=amount,account=self.a,day=day)
        if kind=='transfer': item['target']=self.b
        else: item['category']=self.s.categories(1,kind)[0]['id']
        item.update(kw)
        return item

    def test_money_exact_validation(self):
        self.assertEqual(money('1 250,51'),125051)
        for value in ['0','-1','NaN','Infinity','1.001','abc','1e99']:
            with self.assertRaises(ValueError): money(value)

    def test_transfer_does_not_inflate_income(self):
        self.s.save_entry(1,self.entry('income',10000))
        self.s.save_entry(1,self.entry('transfer',4000))
        self.assertEqual(self.s.balance(1,self.a),6000)
        self.assertEqual(self.s.balance(1,self.b),4000)
        st=self.s.stats(1,date(2026,9,1),date(2026,9,10))
        self.assertEqual((st['income'],st['expense'],st['net']),(10000,0,10000))
        account=self.s.stats(1,date(2026,9,1),date(2026,9,10),self.b)
        self.assertEqual(account['closing'],4000)
        self.assertEqual(account['balance_history'][0]['balance'],4000)

    def test_edit_delete_recompute(self):
        self.s.save_entry(1,self.entry('expense',1000),source=99)
        ident=self.s.rows('SELECT id FROM entries')[0]['id']
        self.s.save_entry(1,self.entry('income',2000),edit=ident)
        self.assertEqual(self.s.balance(1,self.a),2000)
        self.s.delete('entries',1,ident)
        self.assertEqual(self.s.balance(1,self.a),0)

    def test_tenant_isolation(self):
        other=self.s.accounts(2)[0]['id']
        with self.assertRaises(ValueError): self.s.save_entry(1,self.entry('expense',100,account=other))
        with self.assertRaises(ValueError): self.s.owned('accounts',2,self.a)
        with self.assertRaises(ValueError): self.s.save_entry(1,self.entry('transfer',100,target=other))

    def test_idempotent_insert(self):
        self.s.save_entry(1,self.entry('income',2000),source=44)
        self.s.save_entry(1,self.entry('income',2000),source=44)
        self.assertEqual(self.s.balance(1,self.a),2000)

    def test_category_archive_preserves_history(self):
        item=self.entry('expense',1200); self.s.save_entry(1,item)
        self.s.delete('categories',1,item['category'])
        st=self.s.stats(1,date(2026,9,1),date(2026,9,10))
        self.assertEqual(st['categories'][0]['total'],1200)
        with self.assertRaises(ValueError): self.s.save_entry(1,item)

    def test_comparison_equal_length(self):
        self.s.save_entry(1,self.entry('income',10000,'2026-08-30'))
        self.s.save_entry(1,self.entry('income',15000))
        st=self.s.stats(1,date(2026,9,1),date(2026,9,10))
        self.assertEqual(st['previous_start'],'2026-08-22')
        self.assertEqual(growth(st['income'],st['previous']['income']),'+50.0%')
        self.assertEqual(growth(100,0),'нет базы сравнения')

    def test_full_entry_flow_and_duplicate_save(self):
        self.ui.render(1,'new:expense'); self.ui.text(1,'500,25',123)
        self.ui.render(1,f'pick:account:{self.a}')
        self.ui.render(1,f'pick:category:{self.s.categories(1,"expense")[0]["id"]}')
        self.ui.text(1,'09.09.2026 Кофе <3',124)
        self.ui.render(1,'save'); self.ui.render(1,'save')
        self.assertEqual(self.s.balance(1,self.a),-50025)
        self.assertEqual(len(self.s.rows('SELECT * FROM entries')),1)

    def test_goal_and_account_forms(self):
        self.ui.render(1,'form:goal')
        self.ui.text(1,f'Отпуск; 100000; 01.06.2027; {self.b}',50)
        self.ui.render(1,'form:goal')
        with self.assertRaises(ValueError): self.ui.text(1,f'Авто; 200000; 01.06.2027; {self.b}',51)
        goal=self.s.rows('SELECT id FROM goals')[0]['id']
        text,_=self.ui.render(1,f'goal:{goal}')
        self.assertIn('0%',text)
        with self.assertRaises(ValueError): self.s.delete('accounts',1,self.b)

    def test_account_opening_balance_is_not_an_income(self):
        self.ui.render(1, 'form:account')
        self.ui.text(1, 'Копилка; Накопительный; 15000', 77)
        account = self.s.accounts(1)[-1]
        self.assertEqual(account['opening'], 1500000)
        self.assertEqual(self.s.balance(1, account['id']), 1500000)
        self.assertEqual(self.s.rows('SELECT * FROM entries WHERE user=?', (1,)), [])
        self.assertEqual(self.s.stats(1, date(2026, 9, 1), date(2026, 9, 10))['income'], 0)

    def test_delete_requires_matching_confirmation(self):
        self.s.save_entry(1,self.entry('income',100))
        ident=self.s.rows('SELECT id FROM entries')[0]['id']
        with self.assertRaises(ValueError): self.ui.render(1,f'confirm:entries:{ident}')
        self.ui.render(1,f'delete:entries:{ident}')
        self.ui.render(1,f'confirm:entries:{ident}')
        self.assertEqual(self.s.balance(1,self.a),0)

    def test_income_category_forms_return_to_income_list(self):
        self.ui.render(1,'form:category:income'); text,rows=self.ui.text(1,'Премия',90)
        self.assertIn('Доходы\n',text)
        ident=self.s.rows("SELECT id FROM categories WHERE name='Премия'")[0]['id']
        self.assertIn(f'category:{ident}',[b['callback_data'] for row in rows for b in row])
        self.ui.render(1,f'form:rename:{ident}'); text,_=self.ui.text(1,'Бонус',91)
        self.assertIn('Доходы\n',text)
        _,rows=self.ui.render(1,f'delete:categories:{ident}')
        self.assertEqual(rows[0][1]['callback_data'],'categories:income')
        text,_=self.ui.render(1,f'confirm:categories:{ident}')
        self.assertIn('Доходы\n',text)

    def test_all_primary_screens(self):
        for route in ['home','help','accounts',f'account:{self.a}','categories','categories:income','history:0','goals','analytics:week','analytics:month',f'analytics:30:{self.b}','ai','insights']:
            text,rows=self.ui.render(1,route)
            self.assertLess(len(text),4096)
            self.assertTrue(rows)
            for row in rows:
                for b in row:self.assertLessEqual(len(b['callback_data'].encode()),64)

    def test_budget_remaining_and_overspend(self):
        category=self.s.categories(1,'expense')[0]['id']
        self.ui.render(1,f'form:budget:{category}')
        self.ui.text(1,'1000',80)
        self.s.save_entry(1,self.entry('expense',30000))
        text,_=self.ui.render(1,f'category:{category}')
        self.assertIn('Не потрачено · 700,00',text)
        self.s.save_entry(1,self.entry('expense',80000))
        text,_=self.ui.render(1,f'category:{category}')
        self.assertIn('Перерасход · 100,00',text)
        self.ui.render(1,f'form:budget:{category}'); self.ui.text(1,'0',81)
        self.assertFalse(self.s.rows('SELECT * FROM budgets'))

    def test_failed_transfer_is_atomic(self):
        with self.assertRaises(ValueError): self.s.save_entry(1,self.entry('transfer',500,target=self.a))
        self.assertEqual(self.s.balance(1,self.a),0)
        self.assertFalse(self.s.rows('SELECT * FROM entries'))

    def test_invalid_date_keeps_form(self):
        self.ui.render(1,'new:expense'); self.ui.text(1,'10',90)
        self.ui.render(1,f'pick:account:{self.a}')
        self.ui.render(1,f'pick:category:{self.s.categories(1,"expense")[0]["id"]}')
        with self.assertRaises(ValueError): self.ui.text(1,'31.02.2026',91)
        with self.assertRaises(ValueError): self.ui.text(1,'11.09.2026',92)
        self.assertEqual(json.loads(self.s.user(1)['state'])['step'],'details')


class FakeAPI:
    def __init__(self): self.calls=[]
    async def call(self,method,**kwargs):
        self.calls.append((method,kwargs)); return {'message_id':100}


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_contains_incoming_transfer_and_escapes_formula(self):
        s=Ledger(':memory:'); s.user(1); api=FakeAPI(); bot=Bot(s,api)
        a=s.accounts(1)[0]['id']
        with s.db: b=s.db.execute("INSERT INTO accounts(user,name,kind) VALUES(1,'Накопления','Накопительный')").lastrowid
        s.save_entry(1,dict(kind='transfer',amount=1000,account=a,target=b,day='2026-09-10',note='=DANGEROUS()'))
        bot.ui.analytics(1,date(2026,9,1),date(2026,9,10),b)
        await bot.export(1)
        document=api.calls[-1][1]['document'].decode('utf-8-sig')
        self.assertIn('transfer',document)
        self.assertIn("'=DANGEROUS()",document)
        s.db.close()

    async def test_navigation_edits_panel_and_cancels_input(self):
        s=Ledger(':memory:'); api=FakeAPI(); bot=Bot(s,api)
        await bot.handle({'update_id':1,'message':{'message_id':1,'chat':{'id':1,'type':'private'},'text':'/start'}})
        def cb(data,ident):
            revision=s.rows('SELECT revision FROM ui_panels WHERE user=1')[0]['revision']
            return {'update_id':ident,'callback_query':{'id':str(ident),'from':{'id':1},'message':{'message_id':100,'chat':{'id':1,'type':'private'}},'data':revision+'|'+data}}
        await bot.handle(cb('new:expense',2)); await bot.handle(cb('cancel',3))
        self.assertEqual(json.loads(s.user(1)['state']),{})
        self.assertEqual(sum(m=='sendMessage' for m,_ in api.calls),1)
        self.assertEqual(sum(m=='editMessageText' for m,_ in api.calls),2)
        s.db.close()

    async def test_start_moves_panel_to_bottom_of_chat(self):
        s=Ledger(':memory:'); api=FakeAPI(); bot=Bot(s,api)
        start=lambda ident:{'update_id':ident,'message':{'message_id':ident,'chat':{'id':1,'type':'private'},'text':'/start'}}
        await bot.handle(start(1)); await bot.handle(start(2))
        methods=[m for m,_ in api.calls]
        self.assertEqual(methods.count('sendMessage'),2)
        self.assertNotIn('editMessageText',methods)
        self.assertIn(('deleteMessage',{'chat_id':1,'message_id':100}),api.calls)
        await bot.handle({'update_id':3,'message':{'message_id':3,'chat':{'id':1,'type':'private'},'text':'/help'}})
        self.assertEqual([m for m,_ in api.calls].count('editMessageText'),1)
        s.db.close()


if __name__=='__main__': unittest.main()
