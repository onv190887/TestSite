import logging
from g4f.client import Client

logger = logging.getLogger(__name__)


class AIAnalyst:
    """Класс для анализа содержания видео с помощью бесплатных нейросетей."""

    def __init__(self):
        self.client = Client()

    def analyze_video(self, title: str, description: str) -> str:
        """Генерирует краткое саммари на основе названия и описания ролика."""
        logger.info(f"Запрос к ИИ для видео: {title}")

        prompt = (
            f"Проанализируй видео с названием: '{title}'.\n"
            f"Описание видео: '{description[:500]}...'\n\n"
            f"Сделай краткий обзор (3-4 предложения) на русском языке. "
            f"Выдели самое важное. Используй дружелюбный тон."
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",  # Можно менять на gpt-3.5-turbo, если этот медленный
                messages=[{"role": "user", "content": prompt}],
            )

            summary = response.choices[0].message.content
            return summary if summary else "К сожалению, не удалось создать обзор для этого видео."

        except Exception as e:
            logger.error(f"Ошибка при работе с нейросетью: {e}")
            # Возвращаем запасной вариант, чтобы пользователь не остался с пустым сообщением
            return f"📺 <b>{title}</b>\n\n(Обзор временно недоступен, но вы можете посмотреть ролик по ссылке ниже)"