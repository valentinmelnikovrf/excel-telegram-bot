import pandas as pd
from pathlib import Path
from typing import Tuple, List, Dict
import logging

logger = logging.getLogger(__name__)

class PivotValidator:
    """Класс для валидации файла перед построением сводной таблицы"""

    @staticmethod
    async def validate_file(file_path: Path) -> Tuple[bool, str, Dict]:
        """
        Проверяет, есть ли в файле столбцы для группировки и числовые столбцы.
        Возвращает:
        - success: можно ли строить сводную
        - message: сообщение для пользователя
        - data: словарь с категориальными и числовыми столбцами, а также статистикой
        """
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            
            # Определяем категориальные столбцы (текстовые, объектные, с малым количеством уникальных значений)
            categorical = []
            numeric = []
            
            for col in df.columns:
                # Пропускаем полностью пустые столбцы
                if df[col].isna().all():
                    continue
                
                # Проверяем тип данных
                if pd.api.types.is_numeric_dtype(df[col]):
                    numeric.append(col)
                elif pd.api.types.is_datetime64_any_dtype(df[col]):
                    categorical.append(col)  # Даты тоже можно использовать для группировки
                else:
                    # Для текстовых столбцов проверяем количество уникальных значений
                    unique_count = df[col].nunique()
                    if unique_count < len(df) * 0.8:  # Если уникальных значений меньше 80% - это категория
                        categorical.append(col)
                    else:
                        # Если много уникальных значений - возможно это ID, тоже добавляем в категории
                        categorical.append(col)
            
            # Если нет категориальных столбцов, но есть числовые - используем первый числовой как категорию
            if not categorical and numeric:
                first_num = numeric[0]
                categorical.append(first_num)
                numeric.remove(first_num)
                logger.info(f"Нет категориальных столбцов, используем {first_num} как категорию")
            
            # Если нет числовых столбцов – ошибка
            if not numeric:
                return False, "❌ В файле нет числовых столбцов! Невозможно построить сводную таблицу.", {}

            # Подсчёт пустых значений
            empty_counts = df.isna().sum().to_dict()
            total_rows = len(df)
            empty_cells = sum(empty_counts.values())

            data = {
                'categorical': categorical,
                'numeric': numeric,
                'total_rows': total_rows,
                'empty_cells': empty_cells,
                'empty_counts': empty_counts
            }

            # Формируем информационное сообщение
            cat_list = "\n".join([f"🔹 {col}" for col in categorical[:10]])
            if len(categorical) > 10:
                cat_list += f"\n🔹 ... и ещё {len(categorical)-10}"

            num_list = "\n".join([f"🔸 {col}" for col in numeric[:10]])
            if len(numeric) > 10:
                num_list += f"\n🔸 ... и ещё {len(numeric)-10}"

            message = (
                f"✅ **Файл загружен!**\n\n"
                f"📊 **Найдены столбцы:**\n\n"
                f"Для группировки (категории):\n{cat_list}\n\n"
                f"Для расчетов (числа):\n{num_list}\n\n"
                f"Всего строк: {total_rows}, пустых ячеек: {empty_cells}"
            )

            return True, message, data

        except Exception as e:
            logger.error(f"Ошибка валидации файла для сводной: {e}")
            return False, f"❌ Ошибка при чтении файла: {str(e)}", {}