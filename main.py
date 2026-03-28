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

# Настройка логирования для Railway (Выводит всё в консоль)
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
        logger.info(">>> ПРОВЕРКА YOUTUBE: Запуск цикла...")
        
        states = FileManager.load(Config.STATE_FILE, {})
        subs = FileManager.load(Config.SUB_FILE, {})

        if not subs:
            logger.warning(">>> ПРОВЕРКА ПРЕРВАНА: В базе нет активных подписчиков!")
            return

        if not Config.CHANNELS:
            logger.error(">>> ОШИБКА: Список CHANNEL_URL пуст!")
            return

        logger.info(f">>> ПРОВЕРКА: Обрабатываю {len(Config.CHANNELS)} каналов...")
        for url in Config.CHANNELS:
            try:
                await asyncio.wait_for(self._process_channel(url, states, subs, context), timeout=60)
            except Exception as e:
                logger.error(f"Ошибка на канале {url}: {e}")

        FileManager.save(Config.STATE_FILE, states)
        logger.info(">>> ПРОВЕРКА: Цикл успешно завершен.")

    async def _process_channel(self, url: str, states: dict, subs: dict, context: ContextTypes.DEFAULT_TYPE):
        scraper = YouTubeScraper(url)
        video = scraper.get_latest_video()

        if video:
            video_id = str(video['id'])
            last_id = str(states.get(url, ""))

            if video_id != last_id:
                logger.info(f"НОВОЕ ВИДЕО: {video['title']}")
                report = self.ai.analyze_video(video['title'], video['description'])
                message_text = self._format_message(video, report)
                await self._broadcast_message(list(subs.keys()), message_text, context)
                states[url] = video_id
            else:
                logger.info(f"Канал {video.get('channel_name', 'YouTube')}: обновлений нет.")

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
                    reply_markup=keyboard
                )
                logger.info(f"Отправлено пользователю {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки {chat_id}: {e}")

# --- ОБРАБОТЧИКИ КОМАНД ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Бот активен! Нажми /subscribe для получения обзоров.")

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Этот лог мы ДОЛЖНЫ увидеть в Railway сразу после нажатия кнопки
    logger.info(f"!!! ПОЛУЧЕНА КОМАНДА /SUBSCRIBE ОТ {update.effective_chat.id} !!!")
    
    chat_id = str(update.effective_chat.id)
    subs = FileManager.load(Config.SUB_FILE, {})

    if chat_id not in subs:
        subs[chat_id] = {"active": True}
        FileManager.save(Config.SUB_FILE, subs)
        logger.info(f"Пользователь {chat_id} добавлен в базу.")
        await update.message.reply_text("✅ Вы успешно подписаны! Ждите обновлений.")
    else:
        await update.message.reply_text("🔔 Вы уже есть в списке подписчиков.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await context.bot.send_message(chat_id=query.message.chat_id, text="Спасибо за ваш голос!")

def main():
    if not Config.TELEGRAM_TOKEN:
        logger.error("TOKEN не найден!")
        return

    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    handler = UpdateHandler(app)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CallbackQueryHandler(handle_callback))

    if app.job_queue:
        # Ставим проверку каждые 10 минут, первый запуск через 10 секунд
        app.job_queue.run_repeating(handler.run_check, interval=Config.CHECK_INTERVAL, first=10)
        logger.info("ПЛАНИРОВЩИК: Успешно запущен.")
    else:
        logger.error("ПЛАНИРОВЩИК: Ошибка JobQueue!")

    logger.info("БОТ ЗАПУЩЕН. Ожидание сообщений...")
    app.run_polling()

if __name__ == '__main__':
    main()
