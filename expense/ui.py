"""Russian Telegram screens. All navigation replaces one persistent panel."""
import html
import json
import sqlite3
from datetime import date, timedelta

from .core import growth, money, period, rub
from .icons import account_icon, category_icon


def esc(value):
    return html.escape(str(value))


def button(label, route):
    result = {'text': label, 'callback_data': route}
    if route == 'save':
        result['style'] = 'success'
    elif route.startswith('confirm:'):
        result['style'] = 'danger'
    elif route == 'new:income':
        result['style'] = 'success'
    elif route == 'new:expense':
        result['style'] = 'primary'
    return result


def bar(value, total, width=10):
    filled = min(width, max(0, round(value / total * width))) if total else 0
    return '▰' * filled + '▱' * (width-filled)


HOME = [[button('🏠 На главную', 'home'), button('💸 Расход', 'new:expense'), button('💵 Доход', 'new:income')]]
KINDS = {'income': 'Доход', 'expense': 'Расход', 'transfer': 'Перевод'}
TABLE_ROUTES = {'accounts': 'accounts', 'categories': 'categories', 'entries': 'history:0', 'goals': 'goals'}


class UI:
    def __init__(self, ledger, today=date.today, ai_enabled=False):
        self.store, self.today, self.ai_enabled = ledger, today, ai_enabled

    def render(self, uid, route='home'):
        s = self.store
        s.user(uid)
        bits = route.split(':')
        action = bits[0]
        if action == 'cancel':
            state=json.loads(s.user(uid)['state'])
            s.state(uid,{})
            if state.get('edit') and s.rows('SELECT id FROM entries WHERE user=? AND id=?',(uid,state['edit'])):
                text,rows=self.render(uid,f'entry:{state["edit"]}')
                return '↩️ <b>Редактирование отменено</b>\nИзменения не сохранены. Ниже — исходная операция.\n\n'+text,rows
            text,rows=self.render(uid,'home')
            return '↩️ <b>Ввод отменён</b>\nНовые данные не сохранены.\n\n'+text,rows
        if action not in ('pick','pickpage','today','save','confirm','revise'):
            s.state(uid,{})
        if action == 'home':
            accounts = s.accounts(uid)
            stats = s.stats(uid, *period('month', self.today()))
            total = sum(a['balance'] for a in accounts)
            month_names = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')
            text = f'💎 <b>EXPENSE BOT</b>\n<i>Личные финансы</i>\n\n<blockquote>Общий баланс\n<b>{rub(total)}</b>\nНа всех счетах · {len(accounts)}</blockquote>\n\n📅 <b>{month_names[self.today().month-1]} {self.today().year}</b>\n\n📈 Доходы    <b>{rub(stats["income"])}</b>\n📉 Расходы    <b>{rub(stats["expense"])}</b>\n\n<blockquote>💰 Остаток доходов\n<b>{rub(stats["net"])}</b></blockquote>\n\n<i>Выберите действие ↓</i>'
            rows = [[button('💸 Расход', 'new:expense'), button('💵 Доход', 'new:income')], [button('💳 Счета', 'accounts'), button('🔄 Перевод', 'new:transfer')], [button('📊 Аналитика', 'analytics:month'), button('🎯 Цели', 'goals')], [button('🧾 Операции', 'history:0'), button('🏷️ Категории', 'categories')], [button('✨ Персональный разбор', 'ai'), button('💬 Помощь', 'help')]]
            return text, rows
        if action == 'help':
            return ('<b>Ваш финансовый навигатор</b>\n\nДобавляйте доходы и расходы через кнопки. Суммы — в рублях, с точностью до копейки. Даты — ДД.ММ.ГГГГ.\n\n🔄 Переводы меняют балансы двух счетов и не увеличивают доходы или расходы.\n🎯 Одна цель использует один отдельный счёт: его баланс показывает накопления.\n📊 Сравнение — с предшествующим периодом той же длины. «Остаток доходов» — доходы минус расходы, это не бюджет категории.\n\nОценку инвестиций в первой версии ведём вручную: проценты — доход, комиссии — расход. Котировки не загружаются.\n\n/cancel — отменить ввод\n/start — вернуться к обзору', HOME)
        if action == 'accounts':
            accounts = s.accounts(uid)
            page=int(bits[1]) if len(bits)>1 else 0
            return '<b>💳 Мои счета</b>\n\nОбщие средства · ' + rub(sum(a['balance'] for a in accounts)) + '\nВыберите счёт, чтобы увидеть историю и динамику.', self.pages(accounts,lambda a:button(f'{account_icon(a["kind"])} {a["name"]} · {rub(a["balance"])}', f'account:{a["id"]}'),'accounts',page) + [[button('＋ Создать счёт', 'form:account')]] + HOME
        if action == 'account':
            a = s.owned('accounts', uid, bits[1])
            return f'<b>{account_icon(a["kind"])} {esc(a["name"])}</b>\n{esc(a["kind"])}\n\n<b>{rub(s.balance(uid,a["id"]))}</b>\nТекущий баланс\n\nНачальный остаток · {rub(a["opening"])}', [[button('📊 Динамика счёта', f'analytics:month:{a["id"]}')], [button('✏️ Изменить', f'form:account:{a["id"]}'), button('🗑️ Удалить', f'delete:accounts:{a["id"]}')], [button('‹ Счета', 'accounts')]] + HOME
        if action == 'categories':
            kind = bits[1] if len(bits)>1 else 'expense'
            page=int(bits[2]) if len(bits)>2 else 0
            return '<b>🏷️ Категории</b>\n\n' + ('Расходы' if kind=='expense' else 'Доходы') + '\nУдаление скрывает категорию из выбора, история сохраняется.', [[button('💸 Расходы', 'categories:expense'), button('💵 Доходы', 'categories:income')]] + self.pages(s.categories(uid,kind),lambda c:button(f'{category_icon(c["name"])} {c["name"]}', f'category:{c["id"]}'),f'categories:{kind}',page) + [[button('＋ Категория', f'form:category:{kind}')]] + HOME
        if action == 'category':
            c = s.owned('categories',uid,bits[1])
            month=self.today().strftime('%Y-%m')
            spent=s.rows('SELECT COALESCE(SUM(amount),0) total FROM entries WHERE user=? AND category=? AND substr(day,1,7)=?',(uid,c['id'],month))[0]['total']
            budget=s.rows('SELECT amount FROM budgets WHERE user=? AND category=? AND month=?',(uid,c['id'],month))
            text=f'<b>{category_icon(c["name"])} {esc(c["name"])}</b>\n{KINDS[c["kind"]]} · {month}\n\nЗа месяц · {rub(spent)}'
            if budget:
                left=budget[0]['amount']-spent
                text+=f'\nБюджет · {rub(budget[0]["amount"])}\n'+('Не потрачено' if left>=0 else 'Перерасход')+f' · {rub(abs(left))}'
            elif c['kind']=='expense': text+='\n\nЗадайте бюджет, чтобы видеть, сколько ещё можно потратить.'
            return text, ([[button('📊 Бюджет на месяц',f'form:budget:{c["id"]}')]] if c['kind']=='expense' else [])+[[button('✏️ Переименовать', f'form:rename:{c["id"]}'),button('🗑️ Удалить',f'delete:categories:{c["id"]}')],[button('‹ Категории',f'categories:{c["kind"]}')]] + HOME
        if action == 'history':
            page = max(0, int(bits[1]))
            items = s.rows('SELECT e.*,a.name account_name,c.name category_name FROM entries e JOIN accounts a ON a.id=e.account LEFT JOIN categories c ON c.id=e.category WHERE e.user=? ORDER BY e.day DESC,e.id DESC LIMIT 9 OFFSET ?', (uid,page*8))
            text = '<b>🧾 История операций</b>\n\n' + ('Пока пусто. Добавьте первую операцию.' if not items else 'Выберите запись, чтобы изменить или удалить.')
            rows = [[button(f'{r["day"][5:]} · {"−" if r["kind"]=="expense" else "+" if r["kind"]=="income" else "🔄"}{rub(r["amount"])} · {r["category_name"] or "Перевод"}',f'entry:{r["id"]}')] for r in items[:8]]
            nav = ([button('‹ Назад', f'history:{page-1}')] if page else []) + ([button('Далее ›',f'history:{page+1}')] if len(items)>8 else [])
            return text, rows + ([nav] if nav else []) + HOME
        if action == 'entry':
            r=s.owned('entries',uid,bits[1]); a=s.owned('accounts',uid,r['account'])
            detail = s.owned('accounts',uid,r['target'])['name'] if r['target'] else s.owned('categories',uid,r['category'])['name']
            return f'<b>{KINDS[r["kind"]]} · {rub(r["amount"])}</b>\n\n{esc(a["name"])} → {esc(detail)}\n{r["day"]}\n{esc(r["note"]) or "Без заметки"}', [[button('✏️ Изменить',f'edit:{r["id"]}'),button('🗑️ Удалить',f'delete:entries:{r["id"]}')],[button('🧾 История','history:0')]] + HOME
        if action == 'goals':
            goals=s.rows('SELECT * FROM goals WHERE user=? ORDER BY deadline,id',(uid,))
            page=int(bits[1]) if len(bits)>1 else 0
            return '<b>🎯 Цели</b>\n\nУ каждого плана — свой счёт и понятный прогресс.' + ('\n\nНачните с того, на что хочется накопить.' if not goals else ''), self.pages(goals,lambda g:button(f'🎯 {g["name"]}',f'goal:{g["id"]}'),'goals',page) + [[button('＋ Создать цель','form:goal')]] + HOME
        if action == 'goal':
            g=s.owned('goals',uid,bits[1]); balance=s.balance(uid,g['account']); remaining=max(0,g['target']-balance)
            days=max(1,(date.fromisoformat(g['deadline'])-self.today()).days)
            return f'<b>🎯 {esc(g["name"])}</b>\n\n{bar(balance,g["target"])} {max(0,balance/g["target"]*100):.0f}%\n<b>{rub(balance)}</b> из {rub(g["target"])}\n\nОсталось · {rub(remaining)}\nСрок · {g["deadline"]}\n' + (f'Темп до цели · {rub((remaining+days-1)//days)} / день' if g['deadline']>=self.today().isoformat() else 'Срок цели прошёл — обновите план.') + '\n\nПополняйте связанный счёт переводом.', [[button('🔄 Пополнить','new:transfer'),button('🏦 Счёт цели',f'account:{g["account"]}')],[button('✏️ Изменить',f'form:goal:{g["id"]}'),button('🗑️ Удалить',f'delete:goals:{g["id"]}')]] + HOME
        if action == 'analytics':
            key=bits[1]; account=int(bits[2]) if len(bits)>2 and bits[2] else None
            if key == 'custom':
                return self.prompt(uid,{'flow':'period','account':account},'Введите начало и конец периода через пробел.\nНапример: <code>01.08.2026 31.08.2026</code>')
            start,end=period(key,self.today())
            return self.analytics(uid,start,end,account)
        if action == 'ai':
            text='<b>✨ Персональный разбор</b>\n\nАнализ доходов, расходов по категориям и целей за последние 30 дней.'
            if self.ai_enabled:
                text+='\n\nПо нажатию кнопки внешнему ИИ-сервису будут отправлены суммы по категориям, балансы и названия целей. Заметки операций и Telegram ID не передаются.'
                return text,[[button('Разрешить и проанализировать','ai_run')]]+HOME
            return text+'\n\nИИ пока не подключён. Владелец бота может настроить AI_ENDPOINT и ключ в .env. Сейчас доступен локальный расчёт по вашим данным.',[[button('Посмотреть расчёт','insights')]]+HOME
        if action == 'insights':
            st=s.stats(uid,*period('30',self.today()))
            text='<b>✨ Разбор по цифрам</b>\nЭто локальный расчёт, без ИИ.\n\n'
            text+=f'За 30 дней остаток доходов: {rub(st["net"])}.\n'
            spending=[c for c in st['categories'] if c['kind']=='expense']
            if spending:
                top=spending[0]; text+=f'Самая крупная категория: {esc(top["name"])} — {rub(top["total"])}. Снижение на 10% освободит {rub(top["total"]//10)} за такой же период.\n'
            else:
                text+='Добавьте расходы, чтобы увидеть структуру трат.\n'
            for g in s.rows('SELECT * FROM goals WHERE user=? LIMIT 8',(uid,)):
                left=max(0,g['target']-s.balance(uid,g['account']))
                text+=f'\n🎯 {esc(g["name"])}: осталось {rub(left)}.'
            return text,HOME
        if action == 'delete':
            table,ident=bits[1],int(bits[2]); item=s.owned(table,uid,ident)
            s.state(uid,{'confirm_delete':[table,ident]})
            if table=='entries':
                account=s.owned('accounts',uid,item['account'])
                return f'<b>🗑️ Удалить операцию?</b>\n\n{KINDS[item["kind"]]} · <b>{rub(item["amount"])}</b>\n{esc(account["name"])} · {item["day"]}\n{esc(item["note"]) or "Без заметки"}\n\nБаланс и аналитика пересчитаются. Отменить удаление нельзя.', [[button('🗑️ Да, удалить',f'confirm:{table}:{ident}'),button('↩️ Отмена',f'entry:{ident}')]]
            return '<b>🗑️ Удалить запись?</b>\n\n' + ('Категория останется в истории.' if table=='categories' else 'Удаление цели не удаляет деньги со счёта.' if table=='goals' else 'Можно удалить только счёт без операций и целей.'), [[button('🗑️ Да, удалить',f'confirm:{table}:{ident}'),button('↩️ Отмена',TABLE_ROUTES[table])]]
        if action == 'confirm':
            state=json.loads(s.user(uid)['state']); target=[bits[1],int(bits[2])]
            if state.get('confirm_delete')!=target:
                raise ValueError('Подтверждение устарело. Откройте запись заново.')
            s.delete(target[0],uid,target[1]); s.state(uid,{})
            text,rows=self.render(uid,TABLE_ROUTES[target[0]])
            return '✅ <b>Запись удалена</b>\n\n'+text,rows
        if action in ('new','edit','revise'):
            if action=='edit':
                entry=s.owned('entries',uid,bits[1]); state={'flow':'entry','step':'amount','kind':entry['kind'],'edit':entry['id']}
            elif action=='revise':
                state=json.loads(s.user(uid)['state'])
                if state.get('flow')!='entry' or state.get('step')!='save': raise ValueError('Черновик уже закрыт. Начните операцию заново.')
                state['step']='amount'
            else:
                if bits[1] not in KINDS: raise ValueError('Неизвестный тип операции.')
                state={'flow':'entry','step':'amount','kind':bits[1]}
            heading='✏️ Редактирование' if state.get('edit') else '📝 Черновик'
            hint='Исходная операция изменится только после «Сохранить». Отмена оставит её без изменений.' if state.get('edit') else 'Операция появится в учёте только после «Сохранить».'
            return self.prompt(uid,state,f'<b>{heading} · {KINDS[state["kind"]]} · 1 / 5</b>\n\nВведите сумму в рублях.\nНапример: <code>1250,50</code>\n\n<i>{hint}</i>')
        if action == 'pickpage':
            state=json.loads(s.user(uid)['state'])
            if state.get('flow')!='entry' or state.get('step') not in ('account','category','target'):
                raise ValueError('Выбор уже закрыт. Начните операцию заново.')
            return self.choices(uid,state,int(bits[1]))
        if action == 'pick':
            state=json.loads(s.user(uid)['state']); field=bits[1]; ident=int(bits[2])
            if state.get('flow')!='entry' or state.get('step')!=field:
                raise ValueError('Эта кнопка устарела. Начните операцию заново.')
            item=s.owned('categories' if field=='category' else 'accounts',uid,ident)
            if field=='category' and (item['kind']!=state['kind'] or item['archived']): raise ValueError('Выберите доступную категорию.')
            if field=='target' and ident==state['account']: raise ValueError('Выберите другой счёт.')
            state[field]=ident
            if field=='account':
                state['step']='target' if state['kind']=='transfer' else 'category'
                return self.choices(uid,state)
            state['step']='details'
            return self.prompt(uid,state,'<b>Последний штрих · 4 / 5</b>\n\nВведите дату и заметку:\n<code>10.09.2026 Продукты на неделю</code>\n\nИли нажмите «Сегодня» без заметки.',[[button('📅 Сегодня','today')]])
        if action == 'today':
            state=json.loads(s.user(uid)['state'])
            if state.get('step')!='details': raise ValueError('Кнопка устарела.')
            state.update(day=self.today().isoformat(),note='',step='save')
            return self.review(uid,state)
        if action == 'save':
            state=json.loads(s.user(uid)['state'])
            if state.get('step')!='save': return self.render(uid,'home')
            ident=s.save_entry(uid,state,source=state.get('source'),edit=state.get('edit')); s.state(uid,{})
            text,rows=self.render(uid,f'entry:{ident}')
            return '✅ <b>Операция сохранена</b>\n\n'+text, rows
        if action == 'form':
            kind=bits[1]; extra=bits[2] if len(bits)>2 else None
            prompts={
                'account':'<b>Счёт</b>\n\nВведите: название; тип; начальный остаток\n<code>Накопления; Накопительный; 15000</code>\nТип: Обычный, Накопительный или Инвестиционный. Остаток может быть 0.',
                'category':'<b>Новая категория</b>\n\nВведите название (до 40 символов).',
                'rename':'<b>Название категории</b>\n\nВведите новое название (до 40 символов).',
                'budget':'<b>Бюджет категории</b>\n\nВведите лимит на текущий календарный месяц в рублях.\n<code>15000</code>\nВведите 0, чтобы убрать лимит.',
                'goal':'<b>Новая цель</b>\n\nВведите: название; сумма; срок; номер счёта\n<code>Отпуск; 150000; 01.06.2027; 2</code>\n\nСчета:\n'+'\n'.join(f'{a["id"]} · {esc(a["name"])}' for a in s.accounts(uid))+'\n\nДля каждой цели выберите отдельный счёт.'}
            if kind not in prompts: raise ValueError('Неизвестная форма.')
            state={'flow':kind,'extra':extra}
            if kind in ('account','goal') and extra:
                item=s.owned('accounts' if kind=='account' else 'goals',uid,extra)
                prompts[kind]+='\n\nТекущие данные:\n<code>'+esc(f'{item["name"]}; {item["kind"]}; {item["opening"]/100:.2f}' if kind=='account' else f'{item["name"]}; {item["target"]/100:.2f}; {date.fromisoformat(item["deadline"]).strftime("%d.%m.%Y")}; {item["account"]}')+'</code>'
            return self.prompt(uid,state,prompts[kind])
        raise ValueError('Раздел не найден. Используйте /start.')

    def prompt(self,uid,state,text,rows=None):
        self.store.state(uid,state)
        return text,(rows or [])+[[button('↩️ Отмена','cancel')]]

    @staticmethod
    def pages(items,make_button,route,page=0):
        page=max(0,min(page,max(0,(len(items)-1)//8)))
        rows=[[make_button(item)] for item in items[page*8:page*8+8]]
        nav=([button('‹ Назад',f'{route}:{page-1}')] if page else [])+([button('Далее ›',f'{route}:{page+1}')] if (page+1)*8<len(items) else [])
        return rows+([nav] if nav else [])

    def choices(self,uid,state,page=0):
        field=state['step']
        items=self.store.categories(uid,state['kind']) if field=='category' else self.store.accounts(uid)
        items=[i for i in items if field!='target' or i['id']!=state['account']]
        title={'account':'С какого счёта?' if state['kind']!='income' else 'На какой счёт?', 'target':'Куда перевести?', 'category':'Выберите категорию'}[field]
        if not items:
            self.store.state(uid,{})
            return '<b>🏷️ Нужна категория</b>\n\nСоздайте категорию, чтобы добавить операцию.' if field=='category' else '<b>💳 Нужен ещё один счёт</b>\n\nДля перевода нужны два разных счёта. Создайте счёт, на который хотите перевести деньги.', [[button('🏷️ Создать категорию' if field=='category' else '💳 Создать счёт',f'form:category:{state["kind"]}' if field=='category' else 'form:account')], [button('‹ Назад','home')]]
        return self.prompt(uid,state,f'<b>{title}</b>\n\nСумма · {rub(state["amount"])}',self.pages(items,lambda i:button(f'{category_icon(i["name"]) if field=="category" else account_icon(i["kind"])} {i["name"]}',f'pick:{field}:{i["id"]}'),'pickpage',page))

    def review(self,uid,state):
        a=self.store.owned('accounts',uid,state['account'])
        target=self.store.owned('accounts',uid,state['target'])['name'] if state.get('target') else self.store.owned('categories',uid,state['category'])['name']
        return self.prompt(uid,state,f'<b>Всё верно? · 5 / 5</b>\n\n{KINDS[state["kind"]]} · <b>{rub(state["amount"])}</b>\n{esc(a["name"])} → {esc(target)}\n{state["day"]}\n{esc(state["note"])}\n\n<i>Изменения ещё не сохранены.</i>',[[button('✅ Сохранить','save'),button('✏️ Исправить','revise')]])

    def analytics(self,uid,start,end,account=None):
        st=self.store.stats(uid,start,end,account)
        title='📊 Аналитика' if not account else '📊 '+self.store.owned('accounts',uid,account)['name']
        text=f'<b>{esc(title)}</b>\n{start:%d.%m.%Y} — {end:%d.%m.%Y}\n\n📈 Доходы · <b>{rub(st["income"])}</b>\n{growth(st["income"],st["previous"]["income"])} к прошлому периоду\n\n📉 Расходы · <b>{rub(st["expense"])}</b>\n{growth(st["expense"],st["previous"]["expense"])} к прошлому периоду\n\n💰 Остаток доходов · {rub(st["net"])}\nСредний расход / день · {rub(st["daily_average"])}\nДоля сохранённых доходов · '+(str(st['savings_rate'])+'%' if st['savings_rate'] is not None else 'нет доходов')
        if account:
            text+=f'\n\n<b>Баланс с учётом переводов</b>\nНачало · {rub(st["opening"])}\nКонец · {rub(st["closing"])}\nИзменение · {rub(st["movement"])} ({growth(st["closing"],st["opening"])})'
            for day in st['balance_history'][-7:]: text+=f'\n{day["day"]} · {rub(day["balance"])}'
        for kind in ('expense','income'):
            cats=[c for c in st['categories'] if c['kind']==kind]
            text+='\n\n<b>'+('Расходы' if kind=='expense' else 'Доходы')+' по категориям</b>'
            if not cats: text+='\nНет операций за период.'
            for c in cats[:8]:
                text+=f'\n{category_icon(c["name"])} {esc(c["name"])} · {rub(c["total"])}\n{bar(c["total"],st[kind],8)} {c["total"]/st[kind]*100:.0f}% · {c["count"]} оп.'
            if len(cats)>8: text+=f'\nЕщё категорий: {len(cats)-8}. Полные данные — в выгрузке.'
        if not account and start.day==1 and start.strftime('%Y-%m')==end.strftime('%Y-%m'):
            budgets=self.store.rows('SELECT b.amount,c.id,c.name FROM budgets b JOIN categories c ON c.id=b.category WHERE b.user=? AND b.month=? ORDER BY c.name LIMIT 8',(uid,start.strftime('%Y-%m')))
            if budgets: text+='\n\n<b>Остатки бюджетов на месяц</b>'
            for b in budgets:
                spent=self.store.rows('SELECT COALESCE(SUM(amount),0) total FROM entries WHERE user=? AND category=? AND day BETWEEN ? AND ?',(uid,b['id'],start.isoformat(),end.isoformat()))[0]['total']
                text+=f'\n{esc(b["name"])} · {rub(b["amount"]-spent)}'
        text+=f'\n\n<i>Сравнение: {st["previous_start"]} — {st["previous_end"]}. Переводы исключены из доходов и расходов.</i>'
        suffix=f':{account}' if account else ''
        self.store.state(uid,{'report':{'start':start.isoformat(),'end':end.isoformat(),'account':account}})
        return text,[[button('Неделя',f'analytics:week{suffix}'),button('Месяц',f'analytics:month{suffix}'),button('30 дней',f'analytics:30{suffix}')],[button('🗓️ Свой период',f'analytics:custom{suffix}'),button('📥 CSV','export')]]+HOME

    def text(self,uid,text,source):
        s=self.store; state=json.loads(s.user(uid)['state']); flow=state.get('flow')
        if not flow: return self.render(uid,'home')
        if flow=='entry':
            if state['step']=='amount':
                state.update(amount=money(text),step='account',source=source)
                return self.choices(uid,state)
            if state['step']=='details':
                parts=text.split(maxsplit=1)
                day=self.parse_date(parts[0])
                if day>self.today(): raise ValueError('Дата операции не может быть в будущем.')
                state.update(day=day.isoformat(),note=parts[1][:200] if len(parts)>1 else '',step='save')
                return self.review(uid,state)
            raise ValueError('Выберите вариант кнопкой под сообщением.')
        if flow=='period':
            parts=text.split()
            if len(parts)!=2: raise ValueError('Введите две даты через пробел.')
            return self.analytics(uid,self.parse_date(parts[0]),self.parse_date(parts[1]),state.get('account'))
        extra=state.get('extra')
        try:
            with s.db:
                if flow=='budget':
                    category=s.owned('categories',uid,extra)
                    if category['kind']!='expense': raise ValueError('Бюджет доступен для расходов.')
                    month=self.today().strftime('%Y-%m')
                    if text.strip()=='0': s.db.execute('DELETE FROM budgets WHERE user=? AND category=? AND month=?',(uid,extra,month))
                    else: s.db.execute('INSERT INTO budgets(user,category,month,amount) VALUES(?,?,?,?) ON CONFLICT(user,category,month) DO UPDATE SET amount=excluded.amount',(uid,extra,month,money(text)))
                    route=f'category:{extra}'
                elif flow in ('category','rename'):
                    name=self.name(text)
                    if flow=='category':
                        if extra not in ('expense','income'): raise ValueError('Неизвестный тип категории.')
                        s.db.execute('INSERT INTO categories(user,name,kind) VALUES(?,?,?)',(uid,name,extra))
                    else:
                        s.owned('categories',uid,extra)
                        s.db.execute('UPDATE categories SET name=? WHERE user=? AND id=?',(name,uid,extra))
                    route='categories'
                elif flow=='account':
                    parts=[p.strip() for p in text.split(';')]
                    if len(parts)!=3: raise ValueError('Нужны название; тип; начальный остаток.')
                    name=self.name(parts[0]); kind=parts[1].capitalize()
                    if kind not in ('Обычный','Накопительный','Инвестиционный'): raise ValueError('Тип: Обычный, Накопительный или Инвестиционный.')
                    opening=0 if parts[2].replace(',','.') in ('0','0.00','0.0') else money(parts[2])
                    if extra:
                        s.owned('accounts',uid,extra)
                        s.db.execute('UPDATE accounts SET name=?,kind=?,opening=? WHERE id=? AND user=?',(name,kind,opening,extra,uid))
                    else: s.db.execute('INSERT INTO accounts(user,name,kind,opening) VALUES(?,?,?,?)',(uid,name,kind,opening))
                    route='accounts'
                elif flow=='goal':
                    parts=[p.strip() for p in text.split(';')]
                    if len(parts)!=4: raise ValueError('Нужны название; сумма; срок; номер счёта.')
                    name=self.name(parts[0]); amount=money(parts[1]); deadline=self.parse_date(parts[2]); account=int(parts[3])
                    if deadline<self.today(): raise ValueError('Выберите срок сегодня или позднее.')
                    s.owned('accounts',uid,account)
                    if extra:
                        s.owned('goals',uid,extra)
                        s.db.execute('UPDATE goals SET name=?,target=?,deadline=?,account=? WHERE user=? AND id=?',(name,amount,deadline.isoformat(),account,uid,extra))
                    else: s.db.execute('INSERT INTO goals(user,name,target,deadline,account) VALUES(?,?,?,?,?)',(uid,name,amount,deadline.isoformat(),account))
                    route='goals'
                else: raise ValueError('Начните действие заново.')
        except Exception as error:
            # libsql exposes remote constraint errors through its common Error
            # class rather than sqlite3.IntegrityError.
            constraint = isinstance(error, sqlite3.IntegrityError) or 'constraint' in str(error).lower()
            if not constraint:
                raise
            raise ValueError('У этого счёта уже есть цель. Выберите отдельный счёт.') from None
        s.state(uid,{})
        content,rows=self.render(uid,route)
        return '✅ Сохранено\n\n'+content,rows

    @staticmethod
    def name(text):
        if not text.strip() or len(text.strip())>40: raise ValueError('Название должно содержать от 1 до 40 символов.')
        return text.strip()

    @staticmethod
    def parse_date(text):
        from datetime import datetime
        try:
            value=datetime.strptime(text,'%d.%m.%Y').date()
            if value.year<1900: raise ValueError()
            return value
        except ValueError: raise ValueError('Введите дату в формате ДД.ММ.ГГГГ.')
