import base64
import os
import json
import logging
import sqlite3
import uuid
import threading
import time
import asyncio
import requests
import random
import os
import telebot
from datetime import datetime
from dotenv import load_dotenv
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from excel_export import export_database_to_excel, cleanup_old_exports


try:
    from config import STAR_PRICE, MAIN_MENU_IMAGES, WELCOME_MES, logger, REFERRAL_REWARD, ADMIN_ID, DB_NAME
    from baza import (
        init_db, get_user, create_user, update_balance, add_transaction,
        get_pending_payment, update_payment_status,
        set_session_data, get_session_data, delete_session_data,
        get_setting, set_setting, get_referral_count, get_ton_rate_updated_at,
        set_ton_rate, set_ton_rate_updated_at, get_ton_rate  # ДОБАВЛЕН get_referral_count
)
    from fragment_api import load_fragment_token, authenticate_fragment, send_stars
    from yookassa import create_yookassa_payment, check_payment_status
    from keyboards import (
        main_menu_keyboard, buy_stars_options_keyboard, buy_stars_quantity_keyboard,
        back_to_main_keyboard
    )
except ImportError as e:

    class MockLogger:
        def info(self, msg): print(f"INFO: {msg}")

        def error(self, msg): print(f"ERROR: {msg}")

        def warning(self, msg): print(f"WARNING: {msg}")


load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')

TON_DEPOSIT_ADDRESS = os.getenv('TON_DEPOSIT_ADDRESS')  
TON_API_KEY = os.getenv('TON_API_KEY')  
TON_API_BASE_URL = 'https://toncenter.com'
TON_RATE_API = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=rub"

bot = telebot.TeleBot(BOT_TOKEN)

animation_running = False

def safe_edit_message_caption(bot, chat_id, message_id, new_caption, new_reply_markup=None, parse_mode=None):
    try:
        bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=new_caption, reply_markup=new_reply_markup, parse_mode=parse_mode)
        return True
    except Exception as e:
        if "message is not modified" in str(e):
            logger.debug("Сообщение не требует изменений")
            return True
        else:
            logger.error(f"Ошибка редактирования сообщения: {e}")
            raise e


def animate_caption(bot, call):
    global animation_running
    dots = 1
    while animation_running:
        caption = "🔄 Отправляю звезды" + "." * dots
        try:
            bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=caption, reply_markup=None)
        except Exception as e:
            if "message is not modified" not in str(e):
                logger.warning(f"Ошибка при обновлении сообщения анимации: {e}")
            break

        dots = (dots % 3) + 1
        time.sleep(1)


@bot.message_handler(commands=['start', 'menu'])
def start_or_menu(message: Message):
    user = message.from_user
    username = user.username if user.username else None

    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        payload = message.text.split()[1]
        if payload.startswith('r') and payload[1:].isdigit():
            possible_referrer_id = int(payload[1:])
            if possible_referrer_id != user.id:
                if get_user(possible_referrer_id):
                    referrer_id = possible_referrer_id
                    logger.info(f"Обнаружен реферер: {referrer_id} для нового пользователя: {user.id}")

    user_created = create_user(user.id, username, referrer_id)  # ПЕРЕДАЕМ referrer_id

    if user_created and referrer_id is not None:
        update_balance(referrer_id, REFERRAL_REWARD)
        add_transaction(
            user_id=referrer_id,
            amount=REFERRAL_REWARD,
            transaction_type='referral_reward',
            status='completed',
            target_user=str(user.id)
        )

        try:
            bot.send_message(referrer_id, f"✅ Награда за реферала!\n\n" f"Пользователь @{username or user.id} зарегистрировался по вашей ссылке. На ваш баланс зачислено **{REFERRAL_REWARD} руб**!", parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление рефереру {referrer_id}: {e}")

    image = random.choice(MAIN_MENU_IMAGES)
    if isinstance(image, str) and image.startswith("http"):
        bot.send_photo(message.chat.id, image, caption=WELCOME_MES, reply_markup=main_menu_keyboard())
    else:
        with open(image, "rb") as f:
            bot.send_photo(message.chat.id, f, caption=WELCOME_MES, reply_markup=main_menu_keyboard())

@bot.message_handler(commands=['export'])
def handle_export_command(message: Message):
    user_id = message.from_user.id

    if str(user_id) != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды.")
        return

    try:
        processing_msg = bot.reply_to(message, "🔄 Начинаю экспорт базы данных в Excel...")

        filename = export_database_to_excel()

        if filename and os.path.exists(filename):
            with open(filename, 'rb') as file:
                bot.send_document(chat_id=message.chat.id, document=file, caption=f"📊 Экспорт базы данных завершен\nФайл: {filename}", reply_to_message_id=message.message_id)

            try:
                os.remove(filename)
                logger.info(f"✅ Файл экспорта удален: {filename}")
            except Exception as delete_error:
                logger.error(f"❌ Ошибка удаления файла {filename}: {delete_error}")

            bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)

        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=processing_msg.message_id, text="❌ Не удалось создать файл экспорта.")

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /export: {e}")

        try:
            if 'filename' in locals() and filename and os.path.exists(filename):
                os.remove(filename)
                logger.info(f"✅ Файл экспорта удален после ошибки: {filename}")
        except Exception as delete_error:
            logger.error(f"❌ Ошибка удаления файла после ошибки отправки: {delete_error}")

        bot.reply_to(message, f"❌ Произошла ошибка при экспорте: {e}")


@bot.message_handler(commands=['stats'])
def handle_stats_command(message: Message):
    user_id = message.from_user.id

    if str(user_id) != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды.")
        return

    try:
        from baza import get_setting
        import sqlite3

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id IS NOT NULL")
        users_with_referrer = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(balance) FROM users")
        total_balance = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM transactions WHERE type = 'stars_purchase' AND status = 'completed'")
        stars_transactions = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'succeeded'")
        successful_payments = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'succeeded'")
        total_payments = cursor.fetchone()[0] or 0

        ton_rate = get_setting('ton_rub_rate', 'N/A')
        last_rate_update = get_setting('ton_rate_updated_at', 'N/A')

        conn.close()

        stats_message = (
            "📊 *Статистика бота*\n\n"
            f"👥 *Пользователи:*\n"
            f"• Всего: {total_users}\n"
            f"• С реферерами: {users_with_referrer}\n"
            f"• Общий баланс: {total_balance:.2f} руб\n\n"
            f"💫 *Звезды:*\n"
            f"• Покупок звезд: {stars_transactions}\n\n"
            f"💳 *Платежи:*\n"
            f"• Успешных: {successful_payments}\n"
            f"• Общая сумма: {total_payments:.2f} руб\n\n"
            f"🪙 *Курс TON:*\n"
            f"• Текущий: {ton_rate} RUB\n"
            f"• Обновлен: {last_rate_update[:16] if last_rate_update != 'N/A' else 'N/A'}"
        )

        bot.reply_to(message, stats_message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /stats: {e}")
        bot.reply_to(message, f"❌ Ошибка получения статистики: {e}")

@bot.callback_query_handler(func=lambda call: call.data == 'buy_stars')
def buy_stars_selection_menu(call: CallbackQuery):
    bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption="Выберите, кому вы хотите купить звёзды:", reply_markup=buy_stars_options_keyboard())


def deposit_keyboard(user_data):
    keyboard = InlineKeyboardMarkup()
    amounts = [50, 100, 500, 1000]
    for amount in amounts:
        keyboard.row(InlineKeyboardButton(f"{amount} руб (ЮKassa)", callback_data=f'deposit_{amount}'))

    keyboard.row(InlineKeyboardButton("🪙 Пополнить TON", callback_data='deposit_ton'))

    keyboard.row(InlineKeyboardButton("✍️ Другая сумма (ЮKassa)", callback_data='deposit_custom'))
    keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='main_menu'))
    return keyboard


@bot.callback_query_handler(func=lambda call: call.data == 'deposit')
def deposit_menu(call: CallbackQuery):
    user_id = call.from_user.id
    user_data = get_user(user_id)
    bot.edit_message_caption(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        caption="💳 Выберите способ пополнения и сумму:\n\n"
                f"💰 Текущий баланс: {user_data['balance']:.2f} руб",
        reply_markup=deposit_keyboard(user_data)
    )


@bot.callback_query_handler(func=lambda call: call.data == 'profile')
def show_profile(call: CallbackQuery):
    user_id = call.from_user.id
    user_data = get_user(user_id)
    bot.edit_message_caption(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        caption=f"👤 Ваш профиль:\n\n"
                f"🆔 ID: {user_data['user_id']}\n"
                f"👤 Username: @{user_data['username'] or 'Не указан'}\n"
                f"💰 Баланс: {user_data['balance']:.2f} руб\n",
        reply_markup=back_to_main_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == 'referrals_menu')
def show_referrals_menu(call: CallbackQuery):
    user_id = call.from_user.id

    bot_username = bot.get_me().username
    referral_link = f"https://t.me/{bot_username}?start=r{user_id}"

    referral_count = get_referral_count(user_id)

    referral_keyboard = InlineKeyboardMarkup()
    referral_keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='main_menu'))

    caption = (
        f"🔗 **Реферальная программа**\n\n"
        f"Приглашайте друзей и получайте вознаграждение!\n"
        f"🎁 За каждого приглашенного пользователя, который запустит бота, вы получаете **{REFERRAL_REWARD} руб** на баланс.\n\n"
        f"👤 Количество ваших рефералов: **{referral_count}**\n\n"
        f"**Ваша реферальная ссылка:**\n"
        f"`{referral_link}`"
    )

    bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=caption, reply_markup=referral_keyboard, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == 'main_menu')
def main_menu_callback(call: CallbackQuery):
    delete_session_data(call.from_user.id)  
    bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=WELCOME_MES, reply_markup=main_menu_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == 'buy_stars_self')
def buy_stars_self(call: CallbackQuery):
    user_id = call.from_user.id
    user_data = get_user(user_id)

    session_data = {
        'target_username': user_data['username'],
        'state': 'buying_stars',
        'message_id': call.message.message_id
    }
    set_session_data(user_id, session_data)

    bot.edit_message_caption(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        caption="🎯 Выберите количество звезд для покупки:\n\n"
        f"💰 Ваш баланс: {user_data['balance']:.2f} руб", reply_markup=buy_stars_quantity_keyboard(user_data))


@bot.callback_query_handler(func=lambda call: call.data == 'buy_stars_friend')
def buy_stars_friend(call: CallbackQuery):
    user_id = call.from_user.id

    session_data = {
        'state': 'waiting_for_username',
        'message_id': call.message.message_id,
        'target_username': None 
    }
    set_session_data(user_id, session_data)

    bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id,caption="Пожалуйста, введите @username друга (без @):", reply_markup=back_to_main_keyboard())
    bot.register_next_step_handler(call.message, process_friend_username)


def process_friend_username(message: Message):
    user_id = message.from_user.id
    username_input = message.text.strip().lstrip('@')

    state_data = get_session_data(user_id)
    target_message_id = state_data.get('message_id')

    if state_data.get('state') != 'waiting_for_username' or not target_message_id:
        return  

    try:
        if message.message_id != target_message_id:
            bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение: {e}")

    if not username_input:
        bot.edit_message_caption(chat_id=message.chat.id, message_id=target_message_id, caption="❌ Некорректный username. Попробуйте еще раз:", reply_markup=back_to_main_keyboard())
        bot.register_next_step_handler(message, process_friend_username)
        return

    session_data = {
        'target_username': username_input,
        'state': 'buying_stars',
        'message_id': target_message_id
    }
    set_session_data(user_id, session_data)

    user_data = get_user(user_id)

    escaped_username = username_input.replace('_', r'\_').replace('*', r'\*').replace('`', r'\`')

    bot.edit_message_caption(
        chat_id=message.chat.id,
        message_id=target_message_id,
        caption=f"Вы будете покупать звёзды для пользователя **@{escaped_username}**. Выберите количество:",
        reply_markup=buy_stars_quantity_keyboard(user_data),
        parse_mode='Markdown'
    )


@bot.callback_query_handler(func=lambda call: call.data == 'buy_custom')
def buy_stars_custom_quantity(call: CallbackQuery):
    bot.edit_message_caption(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        caption="Пожалуйста, введите желаемое количество звезд (минимум 50):",
        reply_markup=back_to_main_keyboard()
    )
    bot.register_next_step_handler(call.message, process_custom_star_quantity)


def process_custom_star_quantity(message: Message):
    try:
        user_id = message.from_user.id
        quantity_input = message.text.strip()

        state_data = get_session_data(user_id)
        target_message_id = state_data.get('message_id')

        if state_data.get('state') != 'buying_stars' or not target_message_id:
            return 

        quantity = int(quantity_input)
        if quantity < 50:
            raise ValueError("Количество меньше минимума")

        try:
            if message.message_id and message.message_id != target_message_id:
                bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение: {e}")

        call_mock = type('MockCall', (object,), {
            'id': None,
            'from_user': message.from_user,
            'message': type('MockMessage', (object,), {
                'chat': type('MockChat', (object,), {'id': message.chat.id})(),
                'message_id': target_message_id
            })()
        })()

        call_mock.data = f'buy_{quantity}'

        handle_star_purchase(call_mock)
    except ValueError:
        bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=target_message_id,
            caption="❌ Некорректное количество. Пожалуйста, введите число не менее 50:",
            reply_markup=back_to_main_keyboard()
        )
        bot.register_next_step_handler(message, process_custom_star_quantity)


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_star_purchase(call: CallbackQuery):
    stars = int(call.data.split('_')[1])
    user_id = call.from_user.id
    user_data = get_user(user_id)
    cost = stars * STAR_PRICE

    session_data = get_session_data(user_id)
    target_username = session_data.get('target_username')

    if not target_username:
        try:
            safe_edit_message_caption(
                bot,
                call.message.chat.id,
                call.message.message_id,
                "❌ Не удалось определить получателя. Пожалуйста, начните заново.",
                back_to_main_keyboard()
            )
        except Exception as e:
            logger.debug(f"Не удалось отредактировать сообщение при отсутствии получателя: {e}")
        main_menu_callback(call)
        return

    if user_data['balance'] < cost:
        try:
            safe_edit_message_caption(
                bot,
                call.message.chat.id,
                call.message.message_id,
                f"❌ Недостаточно средств на балансе. Нужно {cost:.2f} руб.",
                back_to_main_keyboard()
            )
        except Exception as e:
            logger.debug(f"Не удалось отредактировать сообщение при недостатке средств: {e}")
        return

    global animation_running
    animation_running = True
    animation_thread = threading.Thread(target=animate_caption, args=(bot, call))
    animation_thread.start()

    try:
        token = load_fragment_token() or authenticate_fragment()
        if not token:
            animation_running = False
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption="❌ Ошибка системы. Не удалось получить токен Fragment API. Попробуйте позже.",
                reply_markup=back_to_main_keyboard()
            )
            return

        success, message = send_stars(token, target_username, stars)

        animation_running = False
        animation_thread.join()

        if success:
            update_balance(user_data['user_id'], -cost)
            add_transaction(user_data['user_id'], stars, 'stars_purchase', target_user=target_username)
            user_data_new = get_user(user_id)

            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=f"✅ Успешно отправлено {stars} звезд пользователю **@{target_username}**!\n"
                        f"💰 Ваш новый баланс: {user_data_new['balance']:.2f} руб",
                reply_markup=back_to_main_keyboard(),
                parse_mode='Markdown'
            )
        else:
            if "not enough funds" in message.lower() or "баланс" in message.lower():
                error_message = "❌ У нас закончились звезды. Попробуйте позже."
            else:
                error_message = f"❌ Ошибка при отправке: {message}"

            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=error_message,
                reply_markup=back_to_main_keyboard()
            )
    finally:
        delete_session_data(user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'deposit_ton')
def handle_ton_deposit(call: CallbackQuery):
    user_id = call.from_user.id

    if not TON_DEPOSIT_ADDRESS:
        bot.answer_callback_query(call.id, "❌ Пополнение TON временно недоступно (адрес не указан).", show_alert=True)
        return

    ton_rub_rate = get_ton_rub_rate()
    rate_text = f"~{ton_rub_rate:.2f} руб" if ton_rub_rate else "курс недоступен"

    last_updated = get_ton_rate_updated_at()
    if last_updated:
        last_updated_dt = datetime.fromisoformat(last_updated)
        update_info = f" (обновлен {last_updated_dt.strftime('%H:%M')})"
    else:
        update_info = ""

    payment_url = f'ton://transfer/{TON_DEPOSIT_ADDRESS}?text={user_id}'

    caption = (
        f"🪙 Пополнение через TON:\n\n"
        f"1. Переведите любую сумму TON на этот адрес:\n"
        f"   `{TON_DEPOSIT_ADDRESS}`\n\n"
        f"2. **Обязательно** укажите в комментарии свой ID:\n"
        f"   `{user_id}`\n\n"
        f"💰 Текущий курс: 1 TON ≈ {rate_text}{update_info}\n"
        f"⚠️ Средства будут зачислены на ваш баланс в **РУБЛЯХ** после 3 подтверждений сети."
    )

    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("↗️ Оплатить в TON", url=payment_url))
    keyboard.row(InlineKeyboardButton("↩️ Назад", callback_data='deposit'))

    bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=caption, reply_markup=keyboard, parse_mode='Markdown')


@bot.callback_query_handler(
    func=lambda call: call.data.startswith('deposit_') and call.data != 'deposit_custom' and call.data != 'deposit_ton')
def handle_predefined_deposit(call: CallbackQuery):
    amount = int(call.data.split('_')[1])
    process_deposit(call, amount, 'yookassa')


def send_admin_deposit_notification(user, amount_rub, deposit_type, status, ton_amount=None):
    try:
        admin_id = ADMIN_ID
        if not admin_id:
            logger.warning("ADMIN_ID не установлен. Уведомления администратора не будут отправляться.")
            return

        if deposit_type == 'ton':
            type_text = "TON"
            amount_info = f"{ton_amount:.4f} TON ({amount_rub:.2f} руб)"
        else:
            type_text = "ЮKassa"
            amount_info = f"{amount_rub:.2f} руб"

        status_text = "создан" if status == 'created' else "завершен"

        message = (
            f"💰 *Пополнение баланса {status_text}*\n\n"
            f"👤 *Пользователь:*\n"
            f"   ID: `{user.id}`\n"
            f"   Username: @{user.username or 'не указан'}\n"
            f"   Имя: {getattr(user, 'first_name', 'не указано')}\n\n"
            f"💳 *Детали пополнения:*\n"
            f"   Способ: {type_text}\n"
            f"   Сумма: {amount_info}\n"
            f"   Статус: {status_text}"
        )

        bot.send_message(admin_id, message, parse_mode='Markdown')
        logger.info(f"Уведомление отправлено администратору {admin_id} о пополнении пользователя {user.id}")

    except Exception as e:
        logger.error(f"Ошибка отправки уведомления администратору: {e}")


@bot.callback_query_handler(func=lambda call: call.data == 'deposit_custom')
def handle_custom_deposit(call: CallbackQuery):
    user_id = call.from_user.id

    session_data = {
        'state': 'waiting_for_deposit_amount',
        'message_id': call.message.message_id
    }
    set_session_data(user_id, session_data)

    bot.edit_message_caption(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        caption="💰 На какую сумму хотите пополнить?",
        reply_markup=back_to_main_keyboard()
    )
    bot.register_next_step_handler(call.message, process_custom_deposit_amount)


def process_custom_deposit_amount(message: Message):
    user_id = message.from_user.id
    amount_input = message.text.strip()

    state_data = get_session_data(user_id)
    target_message_id = state_data.get('message_id')

    if state_data.get('state') != 'waiting_for_deposit_amount' or not target_message_id:
        return

    try:
        if message.message_id != target_message_id and target_message_id:
            bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение: {e}")

    try:
        amount = round(float(amount_input), 2)
        if amount <= 0:
            raise ValueError
    except ValueError:
        if target_message_id:
            bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=target_message_id,
                caption="❌ Некорректная сумма. Пожалуйста, введите число больше 0:",
                reply_markup=back_to_main_keyboard()
            )
            bot.register_next_step_handler(message, process_custom_deposit_amount)
            return
        else:
            bot.send_message(message.chat.id, "❌ Некорректная сумма. Пожалуйста, начните заново.")
            return

    call_mock = type('MockCall', (object,), {
        'id': None,
        'from_user': message.from_user,
        'message': type('MockMessage', (object,), {
            'chat': type('MockChat', (object,), {'id': message.chat.id})(),
            'message_id': target_message_id
        })()
    })()

    process_deposit(call_mock, amount, 'yookassa_custom')
    delete_session_data(user_id)


def process_deposit(call, amount: float, deposit_type='yookassa'):
    bot_username = bot.get_me().username
    payment_url = create_yookassa_payment(amount, call.from_user.id, bot_username)

    if payment_url:
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("✅ Я оплатил", callback_data='check_payment'))

        safe_edit_message_caption(
            bot,
            call.message.chat.id,
            call.message.message_id,
            f"💳 Для пополнения на **{amount:.2f} руб**:\n\n"
            f"1. Перейдите по ссылке: {payment_url}\n"
            f"2. Оплатите счет\n"
            f"3. Нажмите кнопку '✅ Я оплатил'\n\n"
            "⚠️ Платеж обрабатывается автоматически в течение нескольких минут.",
            keyboard,
            parse_mode='Markdown'
        )
    else:
        try:
            if hasattr(call, 'id'):
                bot.answer_callback_query(call.id, "❌ Ошибка создания платежа! Попробуйте позже.", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка при ответе на callback: {e}")




@bot.callback_query_handler(func=lambda call: call.data == 'check_payment')
def handle_check_payment(call: CallbackQuery):
    user_id = call.from_user.id

    payment = get_pending_payment(user_id)

    if not payment:
        bot.answer_callback_query(call.id, "❌ Активный платеж для проверки не найден", show_alert=True)
        return

    payment_id, amount = payment
    payment_info = check_payment_status(payment_id)

    if not payment_info:
        bot.answer_callback_query(call.id, "❌ Ошибка проверки платежа", show_alert=True)
        return

    if payment_info['status'] == 'succeeded':
        update_payment_status(payment_id, 'succeeded')
        update_balance(user_id, amount)
        add_transaction(user_id, amount, 'deposit', 'completed')
        user_data = get_user(user_id)
        send_admin_deposit_notification(call.from_user, amount, 'yookassa', 'completed')

        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=f"✅ Платеж успешно завершен!\n"
                    f"💳 Сумма: **{amount:.2f} руб**\n"
                    f"💰 Новый баланс: **{user_data['balance']:.2f} руб**",
            reply_markup=back_to_main_keyboard(),
            parse_mode='Markdown'
        )

    elif payment_info['status'] == 'pending':
        bot.answer_callback_query(call.id, "⌛ Платеж еще не прошел. Попробуйте проверить позже.", show_alert=True)
    else:
        update_payment_status(payment_id, payment_info['status'])
        bot.answer_callback_query(call.id,f"❌ Платеж не прошел. Статус: {payment_info['status']}", show_alert=True)


def get_ton_rub_rate():
    try:
        cached_rate = get_ton_rate()
        last_updated = get_ton_rate_updated_at()

        if cached_rate and last_updated:
            last_updated_dt = datetime.fromisoformat(last_updated)
            if (datetime.now() - last_updated_dt).total_seconds() < 600:  # 10 минут
                return float(cached_rate)

        fresh_rate = fetch_fresh_ton_rate()
        if fresh_rate:
            set_ton_rate(fresh_rate)
            set_ton_rate_updated_at(datetime.now().isoformat())
            logger.info(f"✅ Курс TON обновлен: {fresh_rate:.2f} RUB")
            return fresh_rate
        elif cached_rate:
            logger.warning("⚠️ Используется устаревший курс TON из кэша")
            return float(cached_rate)
        else:
            return None

    except Exception as e:
        logger.error(f"Ошибка получения курса TON: {e}")
        cached_rate = get_ton_rate()
        return float(cached_rate) if cached_rate else None


def fetch_fresh_ton_rate():
    try:
        response = requests.get(TON_RATE_API, timeout=5)
        response.raise_for_status()
        data = response.json()
        rate = data.get('the-open-network', {}).get('rub')
        if rate:
            return float(rate)
        return None
    except Exception as e:
        logger.error(f"Ошибка получения свежего курса TON/RUB: {e}")
        return None


async def update_ton_rate_periodically():
    while True:
        try:
            fresh_rate = fetch_fresh_ton_rate()
            if fresh_rate:
                set_ton_rate(fresh_rate)
                set_ton_rate_updated_at(datetime.now().isoformat())
                logger.info(f"🔄 Курс TON обновлен в фоне: {fresh_rate:.2f} RUB")
                bot.send_message(ADMIN_ID, f"🔄 Курс TON обновлен: {fresh_rate:.2f} RUB")
            else:
                logger.warning("❌ Не удалось обновить курс TON в фоновом режиме")
        except Exception as e:
            logger.error(f"Ошибка фонового обновления курса TON: {e}")

        await asyncio.sleep(600)  # 10 минут


async def check_deposits():
    if not TON_DEPOSIT_ADDRESS or not TON_API_KEY:
        logger.error("TON_DEPOSIT_ADDRESS или TON_API_KEY не заданы. Мониторинг не запущен.")
        return

    last_lt_str = get_setting('last_lt', '0')
    try:
        last_lt = int(last_lt_str)
    except ValueError:
        logger.error(f"Некорректное значение last_lt в БД: '{last_lt_str}'. Используется 0.")
        last_lt = 0

    logger.info(f"Запуск мониторинга TON. Последний LT: {last_lt}")

    while True:
        await asyncio.sleep(10)
        try:
            ton_rub_rate = get_ton_rub_rate()
            if not ton_rub_rate:
                continue

            api_url = (
                f'{TON_API_BASE_URL}/api/v2/getTransactions?'
                f'address={TON_DEPOSIT_ADDRESS}&limit=100&'
                f'archival=true&api_key={TON_API_KEY}'
            )

            resp = requests.get(api_url, timeout=10).json()

            if not resp.get('ok'):
                logger.error(f"Ошибка ответа TON API: {resp.get('error', 'Неизвестная ошибка')}")
                continue

            current_max_lt = last_lt

            for tx in reversed(resp.get('result', [])):
                lt = int(tx['transaction_id']['lt'])

                if lt > current_max_lt:
                    current_max_lt = lt

                if lt <= last_lt:
                    continue

                in_msg = tx.get('in_msg')
                if not in_msg:
                    continue

                value_nano = int(in_msg.get('value', 0))

                if value_nano > 0:
                    uid_str = ''
                    uid_str = in_msg.get('message', '').strip()

                    if not uid_str.isdigit():
                        logger.warning(f"Пропущена транзакция: {lt}. Некорректный uid в комментарии: '{uid_str}'")
                        continue

                    uid = int(uid_str)
                    ton_amount = value_nano / 1e9

                    rub_amount = round(ton_amount * ton_rub_rate, 2)

                    if rub_amount < 1.0:  
                        continue

                    user_data = get_user(uid)
                    if not user_data:
                        logger.warning(f"Пропущена транзакция: {lt}. Пользователь {uid} не найден.")
                        continue

                    update_balance(uid, rub_amount)
                    add_transaction(uid, rub_amount, 'deposit_ton', 'completed', target_user=f'{ton_amount:.4f} TON')
                    logger.info(f"✅ Депозит TON подтвержден! User: {uid}, TON: {ton_amount}, RUB: {rub_amount}")

                    try:
                        from_user_info = type('MockUser', (object,), {
                            'id': uid,
                            'username': user_data['username'],
                            'first_name': f"User{uid}"  
                        })()
                        send_admin_deposit_notification(from_user_info, rub_amount, 'ton', 'completed', ton_amount)
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления администратору: {e}")

                    try:
                        bot.send_message(
                            uid,
                            '✅ Депозит через TON подтвержден!\n'
                            f'Сумма: *+{ton_amount:.4f} TON* ({rub_amount:.2f} руб)\n'
                            f'Ваш новый баланс: {get_user(uid)["balance"]:.2f} руб',
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Error sending message to user {uid}: {e}")

            if current_max_lt > last_lt:
                last_lt = current_max_lt
                set_setting('last_lt', last_lt)  

        except requests.exceptions.Timeout:
            logger.error("TON API запрос таймаут.")
        except Exception as e:
            logger.error(f"Критическая ошибка в TON мониторинге: {e}")


def run_async_loop():
    time.sleep(1)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_deposits())


def run_async_rate_updater():
    time.sleep(2) 
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_ton_rate_periodically())


@bot.callback_query_handler(func=lambda c: c.data == 'TelegramPremium')
def premium_menu(call):
    bot.answer_callback_query(
        call.id,
        "🛠️Функция покупки Telegram Premium в разработке.",
        show_alert=True)


def main():
    try:
        init_db()
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

    try:
        cleanup_old_exports(max_files=1)
    except Exception as e:
        logger.error(f"Ошибка очистки старых файлов экспорта: {e}")

    logger.info("Получение начального курса TON...")
    initial_rate = get_ton_rub_rate()
    if initial_rate:
        logger.info(f"✅ Начальный курс TON установлен: {initial_rate:.2f} RUB")
    else:
        logger.error("❌ Не удалось получить начальный курс TON")

    deposit_thread = threading.Thread(target=run_async_loop, daemon=True)
    deposit_thread.start()
    logger.info("Запущен фоновый мониторинг TON депозитов.")

    rate_thread = threading.Thread(target=run_async_rate_updater, daemon=True)
    rate_thread.start()
    logger.info("Запущен фоновый мониторинг курса TON.")
    logger.info("Проверка и обновление токена Fragment API...")
    try:
        token = load_fragment_token()
        if not token:
            logger.info("Токен не найден. Запуск аутентификации...")
            token = authenticate_fragment()
            if token:
                logger.info("✅ Аутентификация Fragment API прошла успешно!")
            else:
                logger.error("❌ Не удалось получить токен Fragment API. Отправка звезд будет невозможна.")
        else:
            logger.info("✅ Существующий токен Fragment API найден.")
    except Exception as e:
        logger.error(f"Ошибка работы с Fragment API: {e}")

    logger.info("Бот запущен...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")


if __name__ == "__main__":
    main()
