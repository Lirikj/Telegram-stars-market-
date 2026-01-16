
import config
from config import *
from baza import *
from telebot.types import *



def main_menu_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("⭐ Купить звезды", callback_data='buy_stars'),
        InlineKeyboardButton("💰 Пополнить баланс", callback_data='deposit')
    )
    keyboard.row(
        InlineKeyboardButton("👤 Профиль", callback_data='profile'),
        InlineKeyboardButton("🔗 Рефералы", callback_data='referrals_menu') 
    )
    keyboard.row(
        InlineKeyboardButton("✨Telegram premium", callback_data='TelegramPremium'),
        InlineKeyboardButton("⭐️Anonka premium", url="https://t.me/Nurlatanonim_bot?start=premium")
    )
    keyboard.row(
        InlineKeyboardButton("🆘 Поддержка", url = "https://t.me/JonsonP" ),
        InlineKeyboardButton('📑Оферта', url="https://example.com/offer")
        )
    return keyboard


def buy_stars_options_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("👤Себе", callback_data='buy_stars_self'),
        InlineKeyboardButton("🫂Другу", callback_data='buy_stars_friend')
    )
    keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='main_menu'))
    return keyboard


def buy_stars_quantity_keyboard(user_data):
    keyboard = InlineKeyboardMarkup()
    star_price = config.STAR_PRICE

    options = [
        (50, f"50 звезд - {star_price * 50:.2f} руб"),
        (100, f"100 звезд - {star_price * 100:.2f} руб"),
        (500, f"500 звезд - {star_price * 500:.2f} руб"),
        (1000, f"1000 звезд - {star_price * 1000:.2f} руб")
    ]

    for stars, text in options:
        keyboard.row(InlineKeyboardButton(text, callback_data=f'buy_{stars}'))
    keyboard.row(InlineKeyboardButton("✍️ Другое количество", callback_data='buy_custom'))
    keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='main_menu'))
    return keyboard


def deposit_keyboard(user_data):
    keyboard = InlineKeyboardMarkup()

    amounts = [50, 100, 500, 1000]
    for amount in amounts:
        keyboard.row(InlineKeyboardButton(f"{amount} руб", callback_data=f'deposit_{amount}'))
    keyboard.row(InlineKeyboardButton("✍️ Другая сумма", callback_data='deposit_custom'))
    keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='main_menu'))
    return keyboard


def back_to_main_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='main_menu'))
    return keyboard

