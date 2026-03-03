import pandas as pd
from pathlib import Path
import logging
from typing import Optional, Tuple  # 👈 ДОБАВЛЯЕМ НЕДОСТАЮЩИЙ ИМПОРТ

logger = logging.getLogger(__name__)

class ExcelProcessor:
    """Класс для обработки Excel файлов"""
    
    @staticmethod
    async def validate_file(file_path: Path) -> Tuple[bool, str]:
        """
        Проверяет, что файл - валидный Excel
        """
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            return True, f"✅ Файл загружен: {len(df)} строк, {len(df.columns)} столбцов"
        except Exception as e:
            return False, f"❌ Ошибка: {str(e)}"
    
    @staticmethod
    async def vlookup_merge(main_file: Path, source_file: Path) -> Optional[Path]:
        """
        Выполняет ВПР:
        - Ищет по полю 'Ключ' в обоих файлах
        - Добавляет значения из source_file в main_file
        - Новый столбец называется 'Новый столбец'
        """
        try:
            logger.info(f"🔄 Начинаем ВПР: main={main_file.name}, source={source_file.name}")
            
            # Читаем файлы
            df_main = pd.read_excel(main_file, engine='openpyxl')
            df_source = pd.read_excel(source_file, engine='openpyxl')
            
            # Находим столбец со значениями (все кроме 'Ключ')
            value_columns = [col for col in df_source.columns if col != 'Ключ']
            value_col = value_columns[0] if value_columns else 'Значение'
            
            # Выполняем merge
            result = df_main.merge(
                df_source[['Ключ', value_col]], 
                on='Ключ', 
                how='left'
            )
            
            # Переименовываем новый столбец
            result.rename(columns={value_col: 'Новый столбец'}, inplace=True)
            
            # Создаём имя для файла с результатом
            output_path = Path('data') / f"result_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            output_path.parent.mkdir(exist_ok=True)
            
            # Сохраняем результат
            result.to_excel(output_path, index=False, engine='openpyxl')
            
            logger.info(f"✅ ВПР завершён, файл сохранён: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка ВПР: {e}")
            return None