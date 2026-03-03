import asyncio
import logging
import os
from src.config import Config
from src.bot import ExcelBot

async def main():
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Загружаем конфиг
    config = Config()
    
    if not config.BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не найден в .env файле!")
        return
    
    # Создаём папку data если её нет
    os.makedirs("data", exist_ok=True)
    
    # Создаём и запускаем бота
    bot = ExcelBot(config)
    
    try:
        logging.info("🚀 Бот запущен и готов к работе!")
        
        # Определяем, где мы работаем
        if os.getenv('RENDER', False):
            logging.info("🌐 Запуск на Render.com в режиме вебхука")
            webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
            await bot.bot.set_webhook(webhook_url)
            logging.info(f"✅ Вебхук установлен: {webhook_url}")
            
            # Бесконечное ожидание
            await asyncio.Event().wait()
        else:
            # Локально используем polling
            logging.info("💻 Локальный запуск в режиме polling")
            await bot.start()
            
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен")
    except Exception as e:
        logging.error(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())