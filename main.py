import asyncio
import logging
import os
from src.config import Config
from src.bot import ExcelBot
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

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
    
    # При локальном запуске удаляем вебхук
    if not os.getenv('RENDER', False):
        try:
            await bot.bot.delete_webhook()
            logging.info("✅ Вебхук удален для локального запуска")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось удалить вебхук: {e}")
    
    try:
        # Определяем, где мы работаем
        if os.getenv('RENDER', False):
            logging.info("🌐 Запуск на Render.com в режиме вебхука")
            
            # Получаем порт из переменной окружения
            port = int(os.getenv('PORT', 10000))
            
            # URL для вебхука
            render_url = os.getenv('RENDER_EXTERNAL_HOSTNAME', 'excel-telegram-bot.onrender.com')
            webhook_url = f"https://{render_url}/webhook"
            
            # Создаем aiohttp приложение
            app = web.Application()
            
            # Регистрируем обработчик вебхуков
            webhook_requests_handler = SimpleRequestHandler(
                dispatcher=bot.dp,
                bot=bot.bot,
            )
            webhook_requests_handler.register(app, path='/webhook')
            
            # Добавляем простой обработчик для проверки
            async def handle_root(request):
                return web.Response(
                    text="✅ Бот работает! Вебхук активен.",
                    content_type='text/html',
                    charset='utf-8'
                )
            app.router.add_get('/', handle_root)
            
            # Запускаем сервер
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            
            # Устанавливаем вебхук
            await bot.bot.set_webhook(webhook_url)
            logging.info(f"✅ Вебхук установлен: {webhook_url}")
            
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
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())