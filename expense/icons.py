"""Native Telegram emoji: no network requests or image loading on navigation."""

CATEGORY_ICONS = {
    'продукты': '🛒', 'кафе': '☕', 'транспорт': '🚕', 'дом': '🏠',
    'здоровье': '💊', 'покупки': '🛍️', 'зарплата': '💼',
    'подработка': '💻', 'проценты': '📈', 'другое': '📦',
    'путешествия': '✈️', 'отпуск': '🏖️', 'образование': '🎓',
    'подписки': '🔁', 'развлечения': '🎮', 'спорт': '🏋️',
    'подарки': '🎁', 'связь': '📱', 'одежда': '👕', 'авто': '🚗',
}
ACCOUNT_ICONS = {'Обычный': '💳', 'Накопительный': '🏦', 'Инвестиционный': '📈'}


def category_icon(name):
    return CATEGORY_ICONS.get(name.strip().casefold(), '🏷️')


def account_icon(kind):
    return ACCOUNT_ICONS.get(kind, '💳')
