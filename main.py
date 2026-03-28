import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    Application
)

from scraper import YouTubeScraper
from ai_handler import AIAnalyst

# Настройка логирования для Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()


class Config:
    """Конфигурация приложения."""
    DATA_DIR = 'data'
    SUB_FILE = os.path.join(DATA_DIR, 'subscribers.json')
    STATE_FILE = os.path.join(DATA_DIR, 'last_state.json')
    CHECK_INTERVAL = 600  # 10 минут
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHANNELS = [url.strip() for url in os.getenv("CHANNEL_URL", "").split(",") if url.strip()]


class FileManager:
    """Безопасная работа с файлами данных."""

    @staticmethod
    def load(filepath: str, default: Any) -> Any:
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки {filepath}: {e}")
            return default

    @staticmethod
    def save(filepath: str, data: Any):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Ошибка сохранения {filepath}: {e}")


class BotInterface:
    """Кнопки обратной связи."""

    @staticmethod
    def get_feedback_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👍 Интересно", callback_data="like"),
             InlineKeyboardButton("👎 Пропустить", callback_data="dislike")]
        ])


class UpdateHandler:
    """Логика проверки обновлений YouTube."""

    def __init__(self, bot_application: Application):
        self.app = bot_application
        self.ai = AIAnalyst()

    async def run_check(self, context: ContextTypes.DEFAULT_TYPE):
        """Главный цикл проверки, запускаемый JobQueue."""
        logger.info(">>> НАЧАЛО ПРОВЕРКИ YOUTUBE КАНАЛОВ")

        states = FileManager.load(Config.STATE_FILE, {})
        subs = FileManager.load(Config.SUB_FILE, {})

        if not subs:
            logger.warning("Проверка отменена: в базе 0 подписчиков.")
            return

        if not Config.CHANNELS:
            logger.error("Список каналов пуст! Проверь переменную CHANNEL_URL.")
            return

        for url in Config.CHANNELS:
            try:
                # Ограничиваем время проверки одного канала, чтобы бот не завис
                await asyncio.wait_for(self._process_channel(url, states, subs, context), timeout=60)
            except Exception as e:
                logger.error(f"Ошибка при обработке {url}: {e}")

        FileManager.save(Config.STATE_FILE, states)
        logger.info(">>> ЦИКЛ ПРОВЕРКИ ЗАВЕРШЕН")

    async def _process_channel(self, url: str, states: dict, subs: dict, context: ContextTypes.DEFAULT_TYPE):
        scraper = YouTubeScraper(url)
        video = scraper.get_latest_video()

        if video:
            video_id = str(video['id'])
            last_id = str(states.get(url, ""))

            if video_id != last_id:
                logger.info(f"Найдено новое видео: {video['title']}")

                # Анализ через ИИ
                report = self.ai.analyze_video(video['title'], video['description'])
                message_text = self._format_message(video, report)

                # Рассылка всем подписчикам
                await self._broadcast_message(list(subs.keys()), message_text, context)

                # Обновляем ID последнего видео
                states[url] = video_id
            else:
                logger.info(f"На канале '{video.get('channel_name', url)}' новых видео нет.")

    def _format_message(self, video: dict, report: str) -> str:
        return (
            f"📺 <b>КАНАЛ: {video['channel_name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{report}\n\n"
            f"🔗 <a href='{video['link']}'>Смотреть ролик</a>"
        )

    async def _broadcast_message(self, user_ids: List[str], text: str, context: ContextTypes.DEFAULT_TYPE):
        keyboard = BotInterface.get_feedback_keyboard()
        for chat_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_web_page_preview=False
                )
                logger.info(f"Сообщение отправлено пользователю {chat_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение {chat_id}: {e}")


# --- ОБРАБОТЧИКИ КОМАНД ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой ИИ-аналитик YouTube.\n\n"
        "Я слежу за выбранными каналами и присылаю краткие обзоры новых видео.\n"
        "Нажми /subscribe, чтобы начать получать уведомления."
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subs = FileManager.load(Config.SUB_FILE, {})

    if chat_id not in subs:
        subs[chat_id] = {"subscribed_at": str(asyncio.get_event_loop().time())}
        FileManager.save(Config.SUB_FILE, subs)
        logger.info(f"Новый подписчик: {chat_id}")
        await update.message.reply_text("✅ Готово! Теперь вы будете получать обзоры новых видео.")
    else:
        await update.message.reply_text("🔔 Вы уже подписаны на обновления.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)  # Убираем кнопки после нажатия
    await context.bot.send_message(chat_id=query.message.chat_id, text=f"Спасибо за ваш отзыв: {query.data}!")


def main():
    if not Config.TELEGRAM_TOKEN:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_TOKEN не найден!")
        return

    # Создаем приложение
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()

    # Инициализируем наш обработчик обновлений
    update_handler = UpdateHandler(app)

    # Регистрация команд
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Настройка планировщика (JobQueue)
    if app.job_queue:
        # Запускать каждые 10 минут (Config.CHECK_INTERVAL), первый запуск через 10 сек.
        app.job_queue.run_repeating(update_handler.run_check, interval=Config.CHECK_INTERVAL, first=10)
        logger.info("Планировщик проверок YouTube запущен.")
    else:
        logger.error("JobQueue недоступен. Проверьте установку python-telegram-bot[job-queue]")

    logger.info("Бот запущен и ожидает сообщений...")
    app.run_polling()


if __name__ == '__main__':
    main()