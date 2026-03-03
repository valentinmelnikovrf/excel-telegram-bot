import asyncio
import logging
import os
from src.config import Config
from src.bot import ExcelBot
from aiohttp import web

# Создаем простое HTTP-приложение для проверки порта
async def handle(request):
    return web.Response(text="Бот работает!")

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
    
    # Создаём бота
    bot = ExcelBot(config)
    
    try:
        # Определяем, где мы работаем
        if os.getenv('RENDER', False):
            logging.info("🌐 Запуск на Render.com в режиме вебхука")
            
            # Получаем порт из переменной окружения (Render дает PORT=10000)
            port = int(os.getenv('PORT', 10000))
            
            # Устанавливаем вебхук
            webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
            await bot.bot.set_webhook(webhook_url)
            logging.info(f"✅ Вебхук установлен: {webhook_url}")
            
            # Создаем aiohttp приложение для прослушивания порта
            app = web.Application()
            app.router.add_get('/', handle)
            
            # Правильный способ обработки вебхуков в aiogram 3.x
            app.router.add_post('/webhook', bot.dp._process_update)
            
            # Запускаем HTTP сервер
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            
            logging.info(f"✅ HTTP сервер запущен на порту {port}")
            
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