from aiogram.types import LabeledPrice, PreCheckoutQuery
from aiogram import Bot
import logging
import secrets

logger = logging.getLogger(__name__)

class PaymentHandler:
    def __init__(self, bot: Bot):
        self.bot = bot
    
    async def create_invoice(self, chat_id: int, price: int, service_name: str = "Объединение таблиц") -> bool:
        """Создаёт счёт на оплату Stars для конкретной услуги"""
        try:
            prices = [LabeledPrice(label="XTR", amount=price)]
            
            # Генерируем уникальный payload для каждого платежа
            payload = f"{service_name.lower()}_{secrets.token_hex(4)}"
            
            await self.bot.send_invoice(
                chat_id=chat_id,
                title=f"Оплата: {service_name}",
                description=f"Услуга: {service_name}",
                payload=payload,
                provider_token="",
                currency="XTR",
                prices=prices,
                start_parameter="vlookup_bot"  # Простой и валидный параметр
            )
            logger.info(f"💰 Счёт создан для пользователя {chat_id}, услуга: {service_name}, цена: {price}⭐")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка создания счёта: {e}")
            return False
    
    async def process_pre_checkout(self, pre_checkout_query: PreCheckoutQuery):
        """Подтверждаем оплату"""
        await pre_checkout_query.answer(ok=True)
        logger.info(f"✅ Оплата подтверждена: {pre_checkout_query.id}")