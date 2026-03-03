import pandas as pd
from pathlib import Path
import logging
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

class PivotBuilder:
    """Класс для построения сводных таблиц"""

    @staticmethod
    def analyze_columns(file_path: Path) -> Tuple[List[str], List[str], Dict]:
        """
        Анализирует файл и возвращает:
        - список категориальных столбцов (object, category)
        - список числовых столбцов (number)
        - словарь с количеством пустых значений по столбцам
        """
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            categorical = df.select_dtypes(include=['object', 'category']).columns.tolist()
            numeric = df.select_dtypes(include=['number']).columns.tolist()
            
            # Подсчёт пустых значений
            empty_counts = df.isna().sum().to_dict()
            
            return categorical, numeric, empty_counts
        except Exception as e:
            logger.error(f"Ошибка анализа файла: {e}")
            raise

    @staticmethod
    def build_pivot(
        file_path: Path,
        group_cols: List[str],
        value_cols: List[str],
        calcs: List[str],
        empty_handler: str
    ) -> Optional[Path]:
        """
        Строит сводную таблицу.

        :param file_path: путь к исходному файлу
        :param group_cols: список столбцов для группировки
        :param value_cols: список числовых столбцов для расчётов
        :param calcs: список типов расчётов ('sum','count','mean')
        :param empty_handler: 'zero' или 'skip'
        :return: путь к результирующему файлу или None при ошибке
        """
        try:
            df = pd.read_excel(file_path, engine='openpyxl')

            # Обработка пустых значений
            if empty_handler == 'zero':
                df = df.fillna(0)
            elif empty_handler == 'skip':
                df = df.dropna(subset=value_cols)
            else:
                raise ValueError(f"Неизвестный обработчик пустых: {empty_handler}")

            # Формируем агрегации
            agg_dict = {}
            for col in value_cols:
                if 'sum' in calcs:
                    agg_dict[f'{col}_сумма'] = pd.NamedAgg(column=col, aggfunc='sum')
                if 'count' in calcs:
                    agg_dict[f'{col}_количество'] = pd.NamedAgg(column=col, aggfunc='count')
                if 'mean' in calcs:
                    agg_dict[f'{col}_среднее'] = pd.NamedAgg(column=col, aggfunc='mean')

            # Группировка
            pivot = df.groupby(group_cols).agg(**agg_dict).reset_index()

            # Добавляем итоговую строку
            totals = {col: '' for col in group_cols}
            for key in agg_dict.keys():
                if 'сумма' in key:
                    totals[key] = pivot[key].sum()
                elif 'количество' in key:
                    totals[key] = pivot[key].sum()
                elif 'среднее' in key:
                    totals[key] = pivot[key].mean()

            totals_row = pd.DataFrame([totals])
            pivot = pd.concat([pivot, totals_row], ignore_index=True)

            # Сохраняем результат
            output_path = Path('data') / f"pivot_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            output_path.parent.mkdir(exist_ok=True)
            pivot.to_excel(output_path, index=False, engine='openpyxl')

            logger.info(f"✅ Сводная таблица создана: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Ошибка при построении сводной: {e}")
            return None