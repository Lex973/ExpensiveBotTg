# Бесплатный запуск на Vercel и Turso

Эта конфигурация предназначена для личного некоммерческого бота. Vercel Hobby
не разрешает коммерческое использование. Бот работает через Telegram webhook:
Vercel запускает функцию только при новом сообщении, а финансовые данные хранятся
в отдельной SQLite-совместимой базе Turso.

## 1. Создание базы Turso

1. Зарегистрируйтесь на <https://turso.tech/> и создайте базу. Можно оставить
   автоматически выбранный ближайший регион; для Vercel `fra1` подходит европейский регион Turso.
2. В разделе подключения скопируйте URL вида `libsql://...turso.io` и создайте
   токен базы.
3. Установите зависимости локально:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Добавьте в локальный `.env` полученные значения:

   ```text
   TURSO_DATABASE_URL=libsql://ИМЯ-БАЗЫ-ОРГАНИЗАЦИЯ.turso.io
   TURSO_AUTH_TOKEN=ТОКЕН_БАЗЫ
   ```

Токен Telegram, токен Turso и содержимое `.env` нельзя добавлять в Git.

## 2. Перенос существующих операций

Остановите локального бота. Новая база Turso должна быть пустой, затем выполните:

```powershell
python -m scripts.migrate_to_turso data/expense.db
```

Скрипт сохраняет ID пользователей, счетов, категорий, операций, целей, бюджетов
и текущих экранов. Если в Turso уже есть строки, перенос остановится, ничего не
перезаписывая. Локальная база остаётся резервной копией.

Если переносить нечего, этот шаг можно пропустить: схема создастся при первом
сообщении.

## 3. Секрет webhook

Создайте секрет:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Скопируйте результат в локальный `.env`:

```text
TELEGRAM_WEBHOOK_SECRET=СЛУЧАЙНЫЙ_СЕКРЕТ
```

## 4. Развёртывание Vercel

1. Загрузите проект в личный приватный репозиторий GitHub. Файл `.env` и папка
   `data` уже исключены из загрузки.
2. В <https://vercel.com/new> импортируйте репозиторий.
3. Framework Preset оставьте `Other`, Root Directory — корень репозитория.
4. В Environment Variables добавьте для Production:

   ```text
   TELEGRAM_BOT_TOKEN
   TURSO_DATABASE_URL
   TURSO_AUTH_TOKEN
   TELEGRAM_WEBHOOK_SECRET
   UTC_OFFSET_HOURS=5
   ```

   `AI_ENDPOINT` и `AI_API_KEY` добавляются только при использовании внешнего
   ИИ-адаптера. `DATABASE_PATH` на Vercel не нужен.
5. Нажмите Deploy. Адрес `https://ИМЯ-ПРОЕКТА.vercel.app/api/webhook` должен
   возвращать JSON `{"ok": true, ...}` при открытии в браузере.

## 5. Подключение Telegram

Локальный процесс бота должен быть остановлен. Зарегистрируйте production URL:

```powershell
python -m scripts.configure_webhook https://ИМЯ-ПРОЕКТА.vercel.app
```

Скрипт передаёт Telegram секрет, разрешает только сообщения и callback-кнопки,
а также ставит `max_connections=1`. Это сохраняет порядок пошагового ввода даже
при serverless-запуске. После сообщения об успехе отправьте боту `/start`.

## Обновление

После push в основную ветку Vercel создаст новое production-развёртывание.
Повторно регистрировать webhook не требуется, если домен не изменился. Переменные
окружения меняются в Settings → Environment Variables; после изменения нужен
Redeploy.

## Возврат к локальному запуску

Сначала удалите webhook:

```powershell
python -m scripts.configure_webhook --delete
```

После этого удалите или очистите `TURSO_DATABASE_URL` в локальном `.env`, если
нужно вернуться именно к файлу `data/expense.db`, и запустите `python run.py`.

## Диагностика

- `403` в логах Vercel: различается `TELEGRAM_WEBHOOK_SECRET` в Telegram и Vercel;
- `500` с упоминанием переменных: не добавлен один из четырёх обязательных секретов;
- бот не отвечает после успешного deploy: проверьте Runtime Logs и повторите
  `scripts.configure_webhook` с production-доменом;
- две одновременно работающие копии не допускаются: webhook и polling на одном
  токене нельзя использовать вместе.

У бесплатных тарифов нет SLA. Не удаляйте исходную SQLite и периодически
экспортируйте данные из Turso.
