import asyncio
import json
import unittest

from expense.bot import Bot
from expense.core import Ledger


class SlowAcknowledgement:
    async def call(self,method,**kwargs):
        if method=='answerCallbackQuery':
            await asyncio.sleep(0.02)
        return {'message_id':100}


class OrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_amount_cannot_overtake_open_form_callback(self):
        store=Ledger(':memory:')
        self.addCleanup(store.db.close)
        bot=Bot(store,SlowAcknowledgement())
        await bot.handle({'update_id':1,'message':{'message_id':1,'chat':{'id':1,'type':'private'},'text':'/start'}})
        revision=store.rows('SELECT revision FROM ui_panels WHERE user=1')[0]['revision']
        click={'update_id':2,'callback_query':{'id':'2','from':{'id':1},'message':{'message_id':100,'chat':{'id':1,'type':'private'}},'data':revision+'|new:expense'}}
        amount={'update_id':3,'message':{'message_id':3,'chat':{'id':1,'type':'private'},'text':'250'}}
        await asyncio.gather(bot.handle(click),bot.handle(amount))
        state=json.loads(store.user(1)['state'])
        self.assertEqual(state['step'],'account')
        self.assertEqual(state['amount'],25000)
        self.assertFalse(store.rows('SELECT * FROM entries'))
