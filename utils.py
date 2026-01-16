import time
import threading
from main import logger


def animate_caption(bot, call):
    from main import animation_running 
    dots = 1
    while animation_running:
        caption = "🔄 Отправляю звезды" + "." * dots
        try:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=caption,
                reply_markup=None
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                logger.warning(f"Ошибка при обновлении сообщения анимации: {e}")
            break

        dots = (dots % 3) + 1
        time.sleep(1)