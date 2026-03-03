import pandas as pd
from pathlib import Path
from typing import Tuple, Dict  # 👈 ДОБАВЛЯЕМ НЕДОСТАЮЩИЙ ИМПОРТ
import logging

logger = logging.getLogger(__name__)

class ExcelValidator:
    """Класс для проверки Excel файлов перед оплатой"""
    
    @staticmethod
    async def validate_files(main_file: Path, source_file: Path) -> Tuple[bool, str, Dict]:
        """
        Проверяет оба файла на возможность выполнения ВПР
        
        Возвращает:
        - success: можно ли выполнить ВПР
        - message: сообщение для пользователя
        - stats: статистика (количество строк, совпадений и т.д.)
        """
        try:
            stats = {}
            
            # Читаем оба файла
            df_main = pd.read_excel(main_file, engine='openpyxl')
            df_source = pd.read_excel(source_file, engine='openpyxl')
            
            # Проверяем наличие поля "Ключ"
            if 'Ключ' not in df_main.columns:
                return False, "❌ В главном файле нет столбца **'Ключ'**", {}
            
            if 'Ключ' not in df_source.columns:
                return False, "❌ В файле-источнике нет столбца **'Ключ'**", {}
            
            # Проверяем, есть ли столбцы со значениями в source
            value_columns = [col for col in df_source.columns if col != 'Ключ']
            if not value_columns:
                return False, "❌ В файле-источнике нет столбцов со значениями", {}
            
            # Собираем статистику
            stats['main_rows'] = len(df_main)
            stats['source_rows'] = len(df_source)
            stats['main_keys'] = df_main['Ключ'].nunique()
            stats['source_keys'] = df_source['Ключ'].nunique()
            
            # Проверяем, сколько ключей из main есть в source
            main_keys_set = set(df_main['Ключ'].dropna().unique())
            source_keys_set = set(df_source['Ключ'].dropna().unique())
            
            matching_keys = main_keys_set.intersection(source_keys_set)
            stats['matching_keys'] = len(matching_keys)
            stats['missing_keys'] = len(main_keys_set - source_keys_set)
            
            # Проверяем на пустые значения
            stats['main_empty_keys'] = df_main['Ключ'].isna().sum()
            stats['source_empty_keys'] = df_source['Ключ'].isna().sum()
            
            # Название столбца со значениями
            value_col = value_columns[0]
            stats['value_column'] = value_col
            
            # Формируем сообщение
            message = (
                f"✅ **ФАЙЛЫ ПОДХОДЯТ ДРУГ ДРУГУ!**\n\n"
                f"📊 **Статистика:**\n"
                f"• В главном файле: {stats['main_rows']} строк\n"
                f"• В файле-источнике: {stats['source_rows']} строк\n"
                f"• Уникальных ключей в главном: {stats['main_keys']}\n"
                f"• Уникальных ключей в источнике: {stats['source_keys']}\n"
                f"• Найдено совпадений: {stats['matching_keys']}\n"
            )
            
            if stats['missing_keys'] > 0:
                message += f"• ⚠️ Ключей без совпадения: {stats['missing_keys']}\n"
            
            if stats['main_empty_keys'] > 0:
                message += f"• ⚠️ Пустых ключей в главном: {stats['main_empty_keys']}\n"
            
            message += (
                f"\n📎 Будет добавлен столбец: **'{value_col}'**\n"
                f"   (в результате будет называться **'Новый столбец'**)\n\n"
                f"💡 *Пустые ячейки появятся там, где нет совпадений ключей*"
            )
            
            return True, message, stats
            
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке файлов: {e}")
            return False, f"❌ Ошибка при проверке файлов: {str(e)}", {}