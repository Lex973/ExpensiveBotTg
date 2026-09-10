# Бесплатный круглосуточный запуск

Для текущей версии подходит Oracle Cloud Always Free VM: бот постоянно делает Telegram long polling и хранит SQLite на диске. Бесплатные web-хостинги, которые усыпляют процесс, для него не подходят.

## 1. Создать бесплатную VM

1. Зарегистрируйтесь в [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/). Обычно нужны телефон и банковская карта для проверки личности. Oracle указывает, что карта не списывается без ручного перехода на платный аккаунт.
2. Выберите домашний регион внимательно: Always Free VM создаётся только в нём.
3. В консоли откройте **Compute → Instances → Create instance**.
4. Образ: **Ubuntu 24.04**. Shape: **VM.Standard.A1.Flex**, обязательно с меткой **Always Free eligible**. Для бота достаточно 1 OCPU и 1 GB RAM. Если ARM недоступен, попробуйте Always Free `VM.Standard.E2.1.Micro`.
5. Добавьте свой публичный SSH-ключ или скачайте созданный приватный ключ. Не отправляйте приватный ключ и токен бота в чат.
6. Публичный IPv4 нужен только для первоначального SSH-доступа. Входящие порты для Telegram открывать не требуется: бот сам устанавливает исходящее HTTPS-соединение.

Oracle может показать `Out of host capacity`; официальная документация советует попробовать другой availability domain или повторить позже. Не выбирайте платный shape и не превышайте лимиты Always Free.

## 2. Загрузить подготовленный пакет

Из PowerShell на компьютере, подставив IP и путь к ключу:

```powershell
scp -i C:\path\to\ssh-key ExpenseBot-server.tar.gz ubuntu@SERVER_IP:/home/ubuntu/
ssh -i C:\path\to\ssh-key ubuntu@SERVER_IP
```

На сервере:

```bash
tar -xzf ExpenseBot-server.tar.gz
cd ExpenseBot-server
sudo bash deploy/install.sh
sudo nano /etc/expense-bot.env
```

В `/etc/expense-bot.env` замените `PASTE_TOKEN_HERE` на токен и сохраните файл. Затем:

```bash
sudo systemctl enable --now expense-bot
sudo systemctl status expense-bot
sudo journalctl -u expense-bot -f
```

Служба запускается после перезагрузки VM и автоматически перезапускается после ошибки. Код доступен только для чтения в `/opt/expense-bot`, база — в `/var/lib/expense-bot/expense.db`, токен — в `/etc/expense-bot.env` с правами `0600`.

## 3. Перенести текущие данные

Если нужно сохранить операции с компьютера, сначала остановите локальный бот и серверный бот. Передайте `data/expense.db` на сервер и установите правильные права:

```powershell
scp -i C:\path\to\ssh-key data\expense.db ubuntu@SERVER_IP:/home/ubuntu/expense.db
```

```bash
sudo systemctl stop expense-bot
sudo install -o expensebot -g expensebot -m 0600 /home/ubuntu/expense.db /var/lib/expense-bot/expense.db
sudo systemctl start expense-bot
```

Нельзя одновременно запускать локальный и серверный экземпляры с одним токеном: Telegram вернёт конфликт `getUpdates`. После успешного переноса остановите локальный процесс.

## Обновление

Загрузите и распакуйте новую версию, затем выполните `sudo bash deploy/update.sh`. Файл с токеном и база не перезаписываются.

## Резервная копия

```bash
sudo systemctl stop expense-bot
sudo cp /var/lib/expense-bot/expense.db /var/lib/expense-bot/expense-backup.db
sudo chown expensebot:expensebot /var/lib/expense-bot/expense-backup.db
sudo systemctl start expense-bot
```

Для серьёзного использования резервную копию нужно регулярно выгружать за пределы VM. Бесплатный сервер не даёт гарантии сохранности и доступности, поэтому единственная копия базы на VM недостаточна.
