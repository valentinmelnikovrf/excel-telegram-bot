import json
from pathlib import Path
import logging
from typing import Optional  # 👈 ДОБАВЛЯЕМ ИМПОРТ

logger = logging.getLogger(__name__)

class PriceManager:
    """Класс для управления ценами на услуги"""
    
    def __init__(self, config):
        self.config = config
        self.prices_file = Path('data/prices.json')
        self.default_prices = {
            'merge': 10,      # Объединение таблиц (ВПР)
            'pivot': 15,      # Сводные таблицы
            'other': 5,       # Другие услуги (заглушка)
        }
        self.prices = self.load_prices()
    
    def load_prices(self):
        """Загружает цены из файла"""
        try:
            if self.prices_file.exists():
                with open(self.prices_file, 'r', encoding='utf-8') as f:
                    prices = json.load(f)
                    logger.info(f"💰 Цены загружены: {prices}")
                    return prices
            else:
                # Создаем файл с ценами по умолчанию
                self.save_prices(self.default_prices)
                return self.default_prices.copy()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки цен: {e}")
            return self.default_prices.copy()
    
    def save_prices(self, prices):
        """Сохраняет цены в файл"""
        try:
            # Создаем папку data если её нет
            self.prices_file.parent.mkdir(exist_ok=True)
            
            with open(self.prices_file, 'w', encoding='utf-8') as f:
                json.dump(prices, f, ensure_ascii=False, indent=2)
            logger.info(f"💰 Цены сохранены: {prices}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения цен: {e}")
            return False
    
    def get_price(self, service: str) -> int:
        """Возвращает цену для указанной услуги"""
        return self.prices.get(service, self.default_prices.get(service, 10))
    
    def set_price(self, service: str, price: int) -> bool:
        """Устанавливает цену для услуги"""
        if service not in self.default_prices:
            logger.error(f"❌ Неизвестная услуга: {service}")
            return False
        
        if price < 1 or price > 1000:
            logger.error(f"❌ Некорректная цена: {price}")
            return False
        
        self.prices[service] = price
        return self.save_prices(self.prices)
    
    def reset_to_default(self, service: str = None):
        """Сбрасывает цену(ы) на значения по умолчанию"""
        if service:
            if service in self.default_prices:
                self.prices[service] = self.default_prices[service]
        else:
            self.prices = self.default_prices.copy()
        
        return self.save_prices(self.prices)
    
    def get_all_prices(self) -> dict:
        """Возвращает все цены"""
        return self.prices.copy()
    
    def get_price_text(self, service: str) -> str:
        """Возвращает красивое описание цены для пользователя"""
        prices_text = {
            'merge': f"🔗 Объединение таблиц: **{self.prices['merge']}⭐**",
            'pivot': f"📊 Сводные таблицы: **{self.prices['pivot']}⭐**",
            'other': f"📋 Другие услуги: **{self.prices['other']}⭐**",
        }
        return prices_text.get(service, f"Услуга: **{self.prices.get(service, 10)}⭐**")
    
    def get_service_name(self, service: str) -> str:
        """Возвращает название услуги"""
        names = {
            'merge': 'Объединение таблиц',
            'pivot': 'Сводные таблицы',
            'other': 'Другие услуги'
        }
        return names.get(service, service)