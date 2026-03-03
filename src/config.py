import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS', '').split(','))) if os.getenv('ADMIN_IDS') else []
    PRICE_STARS = int(os.getenv('PRICE_STARS', 10))
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB