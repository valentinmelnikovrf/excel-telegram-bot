import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, FSInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from contextlib import suppress
from typing import Optional

from src.config import Config
from src.excel_processor import ExcelProcessor
from src.excel_validator import ExcelValidator
from src.payments import PaymentHandler
from src.prices import PriceManager
from src.messages import Messages
from src.pivot import PivotBuilder
from src.pivot_validator import PivotValidator

logger = logging.getLogger(__name__)

# Состояния для ВПР
class VLookupStates(StatesGroup):
    waiting_main_file = State()
    waiting_source_file = State()
    files_validated = State()
    waiting_payment = State()
    waiting_price_input = State()

# Состояния для сводных таблиц
class PivotStates(StatesGroup):
    waiting_file = State()
    selecting_group_columns = State()
    selecting_value_columns = State()
    selecting_calcs = State()
    selecting_empty_handler = State()
    waiting_payment = State()

class ExcelBot:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.BOT_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # Компоненты для ВПР
        self.excel_processor = ExcelProcessor()
        self.excel_validator = ExcelValidator()
        self.payment_handler = PaymentHandler(self.bot)
        self.price_manager = PriceManager(config)
        
        # Компоненты для сводных
        self.pivot_builder = PivotBuilder()
        self.pivot_validator = PivotValidator()
        
        # Хранилища данных пользователей
        self.user_files = {}           # для ВПР
        self.user_stats = {}            # для ВПР
        self.user_service = {}           # выбранная услуга
        self.pivot_data = {}            # для сводных
        
        self._register_handlers()
    
    def _register_handlers(self):
        # ---------- Общие команды ----------
        @self.dp.message(Command("start"))
        async def cmd_start(message: Message):
            await self._handle_start(message)
        
        @self.dp.message(Command("help"))
        async def cmd_help(message: Message):
            await self._handle_help(message)
        
        @self.dp.message(Command("cancel"))
        async def cancel_handler(message: Message, state: FSMContext):
            current_state = await state.get_state()
            if current_state is None:
                return
            await self._cleanup_user_files(message.from_user.id)
            await self._cleanup_pivot_data(message.from_user.id)
            await state.clear()
            await message.answer(Messages.MERGE_CANCELLED)
            await self._handle_start(message)
        
        # ---------- Кнопки главного меню ----------
        @self.dp.message(F.text.contains("🔗 Объединить таблицы"))
        async def select_merge_service(message: Message, state: FSMContext):
            user_id = message.from_user.id
            self.user_service[user_id] = 'merge'
            price = self.price_manager.get_price('merge')
            
            await state.set_state(VLookupStates.waiting_main_file)
            
            image_path = Path('images/help_step1.png')
            if image_path.exists():
                photo = FSInputFile(image_path)
                await message.answer_photo(photo, caption="📌 Как подготовить первый файл")
            
            builder = ReplyKeyboardBuilder()
            builder.button(text="❌ Отменить")
            builder.adjust(1)
            
            await message.answer(
                Messages.MERGE_START.format(
                    price=price,
                    key_explanation=Messages.KEY_EXPLANATION
                ),
                parse_mode="Markdown",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        
        @self.dp.message(F.text.contains("📊 Создать сводную"))
        async def select_pivot_service(message: Message, state: FSMContext):
            user_id = message.from_user.id
            self.user_service[user_id] = 'pivot'
            price = self.price_manager.get_price('pivot')
            
            await state.set_state(PivotStates.waiting_file)
            
            image_path = Path('images/help_pivot_step1.png')
            if image_path.exists():
                photo = FSInputFile(image_path)
                await message.answer_photo(photo, caption="📊 Как подготовить файл для сводной")
            
            builder = ReplyKeyboardBuilder()
            builder.button(text="❌ Отменить")
            builder.adjust(1)
            
            await message.answer(
                Messages.PIVOT_START.format(price=price),
                parse_mode="Markdown",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        
        @self.dp.message(F.text.contains("📋 Другие"))
        async def select_other_service(message: Message):
            builder = ReplyKeyboardBuilder()
            builder.button(text="◀️ Назад в меню")
            builder.adjust(1)
            await message.answer(
                Messages.OTHER_TOOLS_TEXT,
                parse_mode="Markdown",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        
        @self.dp.message(F.text.contains("❓ Помощь"))
        async def help_button(message: Message):
            await self._handle_help(message)
        
        @self.dp.message(F.text.contains("📞 Поддержка"))
        async def support_button(message: Message):
            builder = ReplyKeyboardBuilder()
            builder.button(text="◀️ Назад в меню")
            builder.adjust(1)
            await message.answer(
                Messages.SUPPORT_TEXT,
                parse_mode="Markdown",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        
        @self.dp.message(F.text == "🔧 Админ")
        async def admin_button(message: Message, state: FSMContext):
            if message.from_user.id in self.config.ADMIN_IDS:
                await self._show_admin_panel(message)
            else:
                await message.answer("❌ У вас нет прав администратора")
        
        @self.dp.message(F.text.contains("◀️ Назад в меню"))
        @self.dp.message(F.text.contains("❌ Отменить"))
        async def back_to_menu(message: Message, state: FSMContext):
            await state.clear()
            await self._cleanup_user_files(message.from_user.id)
            await self._cleanup_pivot_data(message.from_user.id)
            await self._handle_start(message)
        
        # ---------- Обработчики для ВПР ----------
        @self.dp.message(VLookupStates.waiting_main_file, F.document)
        async def handle_main_file(message: Message, state: FSMContext):
            if not message.document.file_name.endswith('.xlsx'):
                await message.answer("❌ Только файлы .xlsx поддерживаются!")
                return
            if message.document.file_size > self.config.MAX_FILE_SIZE:
                await message.answer("❌ Файл слишком большой (макс. 20MB)")
                return
            
            file_path = Path('data') / f"main_{message.from_user.id}_{message.document.file_name}"
            file_path.parent.mkdir(exist_ok=True)
            await self.bot.download(message.document, destination=file_path)
            
            is_valid, msg = await self.excel_processor.validate_file(file_path)
            if not is_valid:
                await message.answer(f"❌ {msg}")
                file_path.unlink(missing_ok=True)
                return
            
            user_id = message.from_user.id
            if user_id not in self.user_files:
                self.user_files[user_id] = {}
            self.user_files[user_id]['main'] = file_path
            
            image_path = Path('images/help_step2.png')
            if image_path.exists():
                photo = FSInputFile(image_path)
                await message.answer_photo(photo, caption="📌 Как подготовить второй файл")
            
            builder = ReplyKeyboardBuilder()
            builder.button(text="❌ Отменить")
            builder.adjust(1)
            
            await message.answer(
                Messages.MERGE_STEP1_SUCCESS.format(file_info=msg.split(':')[1].strip()),
                parse_mode="Markdown",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
            await state.set_state(VLookupStates.waiting_source_file)
        
        @self.dp.message(VLookupStates.waiting_source_file, F.document)
        async def handle_source_file(message: Message, state: FSMContext):
            if not message.document.file_name.endswith('.xlsx'):
                await message.answer("❌ Только файлы .xlsx поддерживаются!")
                return
            if message.document.file_size > self.config.MAX_FILE_SIZE:
                await message.answer("❌ Файл слишком большой (макс. 20MB)")
                return
            
            file_path = Path('data') / f"source_{message.from_user.id}_{message.document.file_name}"
            file_path.parent.mkdir(exist_ok=True)
            await self.bot.download(message.document, destination=file_path)
            
            is_valid, msg = await self.excel_processor.validate_file(file_path)
            if not is_valid:
                await message.answer(f"❌ {msg}")
                file_path.unlink(missing_ok=True)
                return
            
            user_id = message.from_user.id
            self.user_files[user_id]['source'] = file_path
            
            status_msg = await message.answer(Messages.MERGE_VALIDATING)
            
            is_valid, validation_msg, stats = await self.excel_validator.validate_files(
                self.user_files[user_id]['main'],
                self.user_files[user_id]['source']
            )
            await status_msg.delete()
            
            if not is_valid:
                error_img1 = Path('images/help_error_1.png')
                error_img2 = Path('images/help_error_2.png')
                if error_img1.exists():
                    photo = FSInputFile(error_img1)
                    await message.answer_photo(photo)
                if error_img2.exists():
                    photo = FSInputFile(error_img2)
                    await message.answer_photo(photo)
                
                builder = InlineKeyboardBuilder()
                builder.button(text="📖 Инструкция", callback_data="show_help")
                builder.button(text="🔄 Начать заново", callback_data="restart")
                builder.button(text="◀️ В меню", callback_data="menu")
                builder.adjust(1)
                
                await message.answer(
                    Messages.MERGE_VALIDATION_FAILED.format(error_message=validation_msg),
                    parse_mode="Markdown",
                    reply_markup=builder.as_markup()
                )
                await self._cleanup_user_files(user_id)
                await state.clear()
                return
            
            self.user_stats[user_id] = stats
            service = self.user_service.get(user_id, 'merge')
            price = self.price_manager.get_price(service)
            
            builder = InlineKeyboardBuilder()
            builder.button(text=f"✅ Да, оплатить {price}⭐", callback_data="proceed_to_payment")
            builder.button(text="❌ Нет, отменить", callback_data="cancel_operation")
            builder.adjust(1)
            
            result_img = Path('images/help_result.png')
            if result_img.exists():
                photo = FSInputFile(result_img)
                await message.answer_photo(photo, caption="✨ Так будет выглядеть результат")
            
            await message.answer(
                Messages.MERGE_VALIDATION_SUCCESS.format(
                    main_rows=stats['main_rows'],
                    source_rows=stats['source_rows'],
                    main_keys=stats['main_keys'],
                    source_keys=stats['source_keys'],
                    matching_keys=stats['matching_keys'],
                    missing_keys=stats['missing_keys'],
                    value_column=stats['value_column'],
                    price=price
                ),
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
            await state.set_state(VLookupStates.files_validated)
        
        @self.dp.callback_query(VLookupStates.files_validated)
        async def process_validation_callback(callback: CallbackQuery, state: FSMContext):
            user_id = callback.from_user.id
            if callback.data == "cancel_operation":
                await callback.message.edit_text("❌ Операция отменена")
                await self._cleanup_user_files(user_id)
                await state.clear()
                await self._handle_start(callback.message)
                await callback.answer()
                return
            
            if callback.data == "proceed_to_payment":
                await callback.message.edit_text("💳 **Создаю счёт для оплаты...**")
                service = self.user_service.get(user_id, 'merge')
                price = self.price_manager.get_price(service)
                service_name = self.price_manager.get_service_name(service)
                
                success = await self.payment_handler.create_invoice(user_id, price, service_name)
                if success:
                    await state.set_state(VLookupStates.waiting_payment)
                    await callback.answer()
                else:
                    await callback.message.edit_text("❌ Не удалось создать счёт. Попробуйте позже.")
                    await self._cleanup_user_files(user_id)
                    await state.clear()
                    await callback.answer()
        
        # ---------- Обработчики для сводных таблиц ----------
        @self.dp.message(PivotStates.waiting_file, F.document)
        async def handle_pivot_file(message: Message, state: FSMContext):
            if not message.document.file_name.endswith('.xlsx'):
                await message.answer("❌ Только файлы .xlsx поддерживаются!")
                return
            if message.document.file_size > self.config.MAX_FILE_SIZE:
                await message.answer("❌ Файл слишком большой (макс. 20MB)")
                return
            
            file_path = Path('data') / f"pivot_{message.from_user.id}_{message.document.file_name}"
            file_path.parent.mkdir(exist_ok=True)
            await self.bot.download(message.document, destination=file_path)
            
            user_id = message.from_user.id
            status_msg = await message.answer("🔍 Анализирую файл...")
            is_valid, validation_msg, data = await self.pivot_validator.validate_file(file_path)
            await status_msg.delete()
            
            if not is_valid:
                await message.answer(Messages.PIVOT_NO_NUMERIC_COLUMNS)
                file_path.unlink(missing_ok=True)
                await state.clear()
                return
            
            self.pivot_data[user_id] = {
                'file': file_path,
                'categorical': data['categorical'],
                'numeric': data['numeric'],
                'total_rows': data['total_rows'],
                'empty_cells': data['empty_cells']
            }
            
            logger.info(f"✅ Файл загружен для сводной: категории={data['categorical']}, числа={data['numeric']}")
            
            await state.update_data(selected_groups=[])
            await state.set_state(PivotStates.selecting_group_columns)
            await self._show_group_columns(message, user_id, state)
        
        # ЕДИНЫЙ ОБРАБОТЧИК ДЛЯ ВСЕХ CALLBACK СВОДНЫХ ТАБЛИЦ
        @self.dp.callback_query(lambda c: c.data and c.data.startswith('pivot_'))
        async def handle_pivot_callbacks(callback: CallbackQuery, state: FSMContext):
            data = callback.data
            user_id = callback.from_user.id
            logger.info(f"📊 Сводные: callback={data}, user={user_id}")
            
            # Обработка выбора группировки
            if data.startswith('pivot_group_') and data != 'pivot_group_done':
                col = data.replace('pivot_group_', '')
                state_data = await state.get_data()
                selected = state_data.get('selected_groups', [])
                
                if col in selected:
                    selected.remove(col)
                else:
                    if len(selected) < 5:
                        selected.append(col)
                    else:
                        await callback.answer("Можно выбрать не более 5 столбцов!", show_alert=True)
                        return
                
                await state.update_data(selected_groups=selected)
                await self._show_group_columns(callback.message, user_id, state)
            
            # Завершение выбора группировки
            elif data == 'pivot_group_done':
                state_data = await state.get_data()
                selected = state_data.get('selected_groups', [])
                if not selected:
                    await callback.answer("Выберите хотя бы один столбец!", show_alert=True)
                    return
                
                await state.update_data(pivot_group_cols=selected)
                await state.set_state(PivotStates.selecting_value_columns)
                await state.update_data(selected_values=[])
                await self._show_value_columns(callback.message, user_id, state)
            
            # Обработка выбора числовых столбцов
            elif data.startswith('pivot_value_') and data != 'pivot_value_done':
                col = data.replace('pivot_value_', '')
                state_data = await state.get_data()
                selected = state_data.get('selected_values', [])
                
                if col in selected:
                    selected.remove(col)
                else:
                    selected.append(col)
                
                await state.update_data(selected_values=selected)
                await self._show_value_columns(callback.message, user_id, state)
            
            # Завершение выбора числовых столбцов
            elif data == 'pivot_value_done':
                state_data = await state.get_data()
                selected = state_data.get('selected_values', [])
                if not selected:
                    await callback.answer("Выберите хотя бы один столбец!", show_alert=True)
                    return
                
                await state.update_data(pivot_value_cols=selected)
                await state.set_state(PivotStates.selecting_calcs)
                await state.update_data(selected_calcs=[])
                await self._show_calcs(callback.message, state)
            
            # Обработка выбора расчетов
            elif data.startswith('pivot_calc_') and data != 'pivot_calc_done':
                calc = data.replace('pivot_calc_', '')
                state_data = await state.get_data()
                selected = state_data.get('selected_calcs', [])
                
                if calc in selected:
                    selected.remove(calc)
                else:
                    selected.append(calc)
                
                await state.update_data(selected_calcs=selected)
                await self._show_calcs(callback.message, state)
            
            # Завершение выбора расчетов
            elif data == 'pivot_calc_done':
                state_data = await state.get_data()
                selected = state_data.get('selected_calcs', [])
                if not selected:
                    await callback.answer("Выберите хотя бы один тип расчёта!", show_alert=True)
                    return
                
                await state.update_data(pivot_calcs=selected)
                await state.set_state(PivotStates.selecting_empty_handler)
                await self._show_empty_handler(callback.message, state)
            
            # Обработка выбора обработки пустых
            elif data.startswith('pivot_empty_'):
                handler = data.replace('pivot_empty_', '')
                await state.update_data(pivot_empty_handler=handler)
                await self._show_pivot_preview(callback.message, user_id, state)
            
            # Оплата
            elif data == 'pivot_pay':
                price = self.price_manager.get_price('pivot')
                success = await self.payment_handler.create_invoice(user_id, price, "Сводная таблица")
                if success:
                    await state.set_state(PivotStates.waiting_payment)
                    await callback.message.edit_text("💳 Счёт создан. Оплатите, чтобы продолжить.")
                else:
                    await callback.message.edit_text("❌ Не удалось создать счёт. Попробуйте позже.")
                    await self._cleanup_pivot_data(user_id)
                    await state.clear()
            
            # Отмена
            elif data == 'pivot_cancel':
                await self._cleanup_pivot_data(user_id)
                await state.clear()
                await callback.message.edit_text("❌ Операция отменена.")
                await self._handle_start(callback.message)
            
            await callback.answer()
        
        # ---------- Обработка успешных платежей ----------
        @self.dp.message(F.successful_payment)
        async def process_successful_payment(message: Message, state: FSMContext):
            user_id = message.from_user.id
            service = self.user_service.get(user_id)
            
            if service == 'merge':
                # Обработка для ВПР
                if user_id not in self.user_files or 'main' not in self.user_files[user_id] or 'source' not in self.user_files[user_id]:
                    await message.answer("❌ Ошибка: файлы не найдены. Начните заново с /start")
                    await state.clear()
                    return
                
                status_msg = await message.answer(Messages.MERGE_PROCESSING)
                result_path = await self.excel_processor.vlookup_merge(
                    self.user_files[user_id]['main'],
                    self.user_files[user_id]['source']
                )
                await status_msg.delete()
                
                if result_path and result_path.exists():
                    stats = self.user_stats.get(user_id, {})
                    document = FSInputFile(result_path)
                    builder = ReplyKeyboardBuilder()
                    builder.button(text="🔗 Новое объединение")
                    builder.button(text="◀️ В меню")
                    builder.adjust(2)
                    
                    await message.answer_document(
                        document,
                        caption=Messages.MERGE_SUCCESS.format(
                            main_rows=stats.get('main_rows', '?'),
                            matching_keys=stats.get('matching_keys', '?'),
                            missing_keys=stats.get('missing_keys', 0)
                        ),
                        parse_mode="Markdown",
                        reply_markup=builder.as_markup(resize_keyboard=True)
                    )
                    await self._cleanup_user_files(user_id)
                    if user_id in self.user_stats:
                        del self.user_stats[user_id]
                else:
                    await message.answer("❌ Ошибка при обработке файлов. Попробуйте снова.")
                    await self._cleanup_user_files(user_id)
            
            elif service == 'pivot':
                await self._process_pivot_payment(message, state)
            
            if user_id in self.user_service:
                del self.user_service[user_id]
            await state.clear()
        
        # ---------- Админ-панель ----------
        @self.dp.message(Command("admin"))
        async def cmd_admin(message: Message, state: FSMContext):
            if message.from_user.id not in self.config.ADMIN_IDS:
                await message.answer("❌ У вас нет прав администратора")
                return
            await self._show_admin_panel(message)
        
        @self.dp.callback_query(lambda c: c.data and c.data.startswith('admin_'))
        async def process_admin_callback(callback: CallbackQuery, state: FSMContext):
            if callback.from_user.id not in self.config.ADMIN_IDS:
                await callback.answer("❌ Нет прав")
                return
            
            if callback.data == "admin_stats":
                active_users = len(self.user_files) + len(self.pivot_data)
                waiting_payment = len([u for u in self.user_stats.keys() if u in self.user_files])
                prices = self.price_manager.get_all_prices()
                
                await callback.message.answer(
                    Messages.ADMIN_STATS.format(
                        active_users=active_users,
                        waiting_payment=waiting_payment,
                        merge_price=prices['merge'],
                        pivot_price=prices['pivot'],
                        other_price=prices['other']
                    )
                )
                await callback.answer()
            
            elif callback.data == "admin_set_price_merge":
                await state.set_state(VLookupStates.waiting_price_input)
                await state.update_data(price_service='merge')
                await callback.message.edit_text(
                    Messages.ADMIN_SET_PRICE.format(
                        service_name="объединения таблиц",
                        current_price=self.price_manager.get_price('merge')
                    )
                )
                await callback.answer()
            
            elif callback.data == "admin_set_price_pivot":
                await state.set_state(VLookupStates.waiting_price_input)
                await state.update_data(price_service='pivot')
                await callback.message.edit_text(
                    Messages.ADMIN_SET_PRICE.format(
                        service_name="сводных таблиц",
                        current_price=self.price_manager.get_price('pivot')
                    )
                )
                await callback.answer()
            
            elif callback.data == "admin_reset_prices":
                self.price_manager.reset_to_default()
                prices = self.price_manager.get_all_prices()
                await callback.message.edit_text(
                    Messages.ADMIN_PRICES_RESET.format(
                        merge_price=prices['merge'],
                        pivot_price=prices['pivot']
                    )
                )
                await callback.answer()
        
        @self.dp.message(VLookupStates.waiting_price_input)
        async def process_price_input(message: Message, state: FSMContext):
            if message.from_user.id not in self.config.ADMIN_IDS:
                await state.clear()
                return
            
            try:
                price = int(message.text.strip())
                data = await state.get_data()
                service = data.get('price_service', 'merge')
                
                if self.price_manager.set_price(service, price):
                    service_names = {'merge': 'объединения', 'pivot': 'сводных'}
                    await message.answer(
                        Messages.ADMIN_PRICE_UPDATED.format(
                            service_name=service_names.get(service, service),
                            price=price
                        )
                    )
                else:
                    await message.answer("❌ Ошибка: цена должна быть от 1 до 1000")
            except ValueError:
                await message.answer("❌ Ошибка: введите число")
            
            await state.clear()
            await self._show_admin_panel(message)
        
        @self.dp.callback_query(lambda c: c.data in ["show_help", "restart", "menu"])
        async def handle_action_callbacks(callback: CallbackQuery, state: FSMContext):
            if callback.data == "show_help":
                await self._handle_help(callback.message)
            elif callback.data == "restart":
                await state.clear()
                await self._handle_start(callback.message)
            elif callback.data == "menu":
                await state.clear()
                await self._handle_start(callback.message)
            await callback.answer()
        
        @self.dp.pre_checkout_query()
        async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery):
            await self.payment_handler.process_pre_checkout(pre_checkout_query)
    
    # ---------- Вспомогательные методы ----------
    async def _cleanup_user_files(self, user_id: int):
        if user_id in self.user_files:
            for file_path in self.user_files[user_id].values():
                with suppress(Exception):
                    file_path.unlink(missing_ok=True)
            del self.user_files[user_id]
    
    async def _cleanup_pivot_data(self, user_id: int):
        if user_id in self.pivot_data:
            file_path = self.pivot_data[user_id].get('file')
            if file_path and file_path.exists():
                with suppress(Exception):
                    file_path.unlink(missing_ok=True)
            del self.pivot_data[user_id]
    
    async def _show_group_columns(self, message: Message, user_id: int, state: FSMContext):
        """Показывает столбцы для группировки"""
        data = self.pivot_data.get(user_id)
        if not data:
            await message.answer("❌ Ошибка данных. Начните заново.")
            await state.clear()
            return
        
        categorical = data['categorical'][:5]
        state_data = await state.get_data()
        selected = state_data.get('selected_groups', [])
        
        if not categorical:
            await message.answer("❌ В файле нет столбцов для группировки. Попробуйте другой файл.")
            await state.clear()
            return
        
        builder = InlineKeyboardBuilder()
        for col in categorical:
            mark = "📌 " if col in selected else "   "
            builder.button(text=f"{mark}{col}", callback_data=f"pivot_group_{col}")
        builder.button(text="✅ Готово", callback_data="pivot_group_done")
        builder.adjust(2)
        
        selected_text = ", ".join(selected) if selected else "пока ничего"
        
        await message.answer(
            f"📋 **Шаг 2/5: Выберите столбцы для группировки**\n\n"
            f"**📌 Выбрано:** {selected_text}\n"
            f"(можно выбрать до 5, нажмите на кнопки, затем \"✅ Готово\")\n\n"
            f"💡 *Если нет кнопок с названиями столбцов, значит в файле нет подходящих категорий.*",
            reply_markup=builder.as_markup()
        )
    
    async def _show_value_columns(self, message: Message, user_id: int, state: FSMContext):
        """Показывает числовые столбцы для расчетов"""
        data = self.pivot_data.get(user_id)
        if not data:
            await message.answer("❌ Ошибка данных. Начните заново.")
            await state.clear()
            return
        
        numeric = data['numeric']
        state_data = await state.get_data()
        selected = state_data.get('selected_values', [])
        
        builder = InlineKeyboardBuilder()
        for col in numeric:
            mark = "📌 " if col in selected else "   "
            builder.button(text=f"{mark}{col}", callback_data=f"pivot_value_{col}")
        builder.button(text="✅ Готово", callback_data="pivot_value_done")
        builder.adjust(2)
        
        selected_text = ", ".join(selected) if selected else "пока ничего"
        
        await message.answer(
            f"📋 **Шаг 3/5: Выберите числовые столбцы для расчетов**\n\n"
            f"**📌 Выбрано:** {selected_text}\n"
            f"(можно выбрать несколько, нажмите на кнопки, затем \"✅ Готово\")",
            reply_markup=builder.as_markup()
        )
    
    async def _show_calcs(self, message: Message, state: FSMContext):
        """Показывает типы расчетов"""
        state_data = await state.get_data()
        selected = state_data.get('selected_calcs', [])
        
        builder = InlineKeyboardBuilder()
        calcs = [
            ('sum', 'Сумма'),
            ('count', 'Количество'),
            ('mean', 'Среднее')
        ]
        
        for calc_id, calc_name in calcs:
            mark = "📌 " if calc_id in selected else "   "
            builder.button(text=f"{mark}{calc_name}", callback_data=f"pivot_calc_{calc_id}")
        builder.button(text="✅ Готово", callback_data="pivot_calc_done")
        builder.adjust(1)
        
        calc_names = {'sum': 'Сумма', 'count': 'Количество', 'mean': 'Среднее'}
        selected_text = ", ".join([calc_names[c] for c in selected]) if selected else "пока ничего"
        
        await message.answer(
            f"📋 **Шаг 4/5: Выберите типы расчетов**\n\n"
            f"**📌 Выбрано:** {selected_text}\n"
            f"(можно выбрать несколько, нажмите на кнопки, затем \"✅ Готово\")",
            reply_markup=builder.as_markup()
        )
    
    async def _show_empty_handler(self, message: Message, state: FSMContext):
        """Показывает выбор обработки пустых значений"""
        builder = InlineKeyboardBuilder()
        builder.button(text="🔵 Заменить на 0", callback_data="pivot_empty_zero")
        builder.button(text="🟢 Пропустить строки", callback_data="pivot_empty_skip")
        builder.adjust(1)
        
        await message.answer(
            Messages.PIVOT_EMPTY_HANDLER,
            reply_markup=builder.as_markup()
        )
    
    async def _show_pivot_preview(self, message: Message, user_id: int, state: FSMContext):
        """Показывает предпросмотр сводной таблицы"""
        data = self.pivot_data.get(user_id)
        state_data = await state.get_data()
        price = self.price_manager.get_price('pivot')
        
        group_cols = state_data.get('pivot_group_cols', [])
        value_cols = state_data.get('pivot_value_cols', [])
        calcs = state_data.get('pivot_calcs', [])
        empty_handler = state_data.get('pivot_empty_handler', 'zero')
        
        calc_names = {'sum': 'Сумма', 'count': 'Количество', 'mean': 'Среднее'}
        calcs_str = ", ".join([calc_names.get(c, c) for c in calcs])
        
        builder = InlineKeyboardBuilder()
        builder.button(text=f"✅ Оплатить {price}⭐", callback_data="pivot_pay")
        builder.button(text="❌ Отменить", callback_data="pivot_cancel")
        builder.adjust(1)
        
        await message.answer(
            Messages.PIVOT_PREVIEW.format(
                total_rows=data['total_rows'],
                empty_cells=data['empty_cells'],
                group_cols=", ".join(group_cols),
                value_cols=", ".join(value_cols),
                calcs=calcs_str,
                empty_handler="Заменить на 0" if empty_handler == 'zero' else "Пропустить строки",
                price=price
            ),
            reply_markup=builder.as_markup()
        )
    
    async def _process_pivot_payment(self, message: Message, state: FSMContext):
        """Обработка оплаты сводной таблицы"""
        user_id = message.from_user.id
        if user_id not in self.pivot_data:
            await message.answer("❌ Ошибка: данные не найдены. Начните заново.")
            await state.clear()
            return
        
        data = self.pivot_data[user_id]
        file_path = data['file']
        state_data = await state.get_data()
        
        group_cols = state_data.get('pivot_group_cols', [])
        value_cols = state_data.get('pivot_value_cols', [])
        calcs = state_data.get('pivot_calcs', [])
        empty_handler = state_data.get('pivot_empty_handler', 'zero')
        
        status_msg = await message.answer("⏳ Строю сводную таблицу...")
        
        result_path = self.pivot_builder.build_pivot(
            file_path, group_cols, value_cols, calcs, empty_handler
        )
        
        await status_msg.delete()
        
        if result_path and result_path.exists():
            document = FSInputFile(result_path)
            await message.answer_document(
                document,
                caption=Messages.PIVOT_SUCCESS.format(
                    result_rows="?",
                    group_cols=", ".join(group_cols),
                    calcs=", ".join(calcs)
                )
            )
            file_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)
            del self.pivot_data[user_id]
        else:
            await message.answer("❌ Ошибка при построении сводной. Попробуйте снова.")
        await state.clear()
    
    async def _handle_start(self, message: Message):
        """Главное меню"""
        prices = self.price_manager.get_all_prices()
        
        await message.answer(
            Messages.MAIN_MENU.format(
                merge_price=prices['merge'],
                pivot_price=prices['pivot']
            ),
            parse_mode="Markdown"
        )
        
        builder = ReplyKeyboardBuilder()
        builder.button(text=f"🔗 Объединить таблицы (ВПР) ({prices['merge']}⭐)")
        builder.button(text=f"📊 Создать сводную таблицу ({prices['pivot']}⭐)")
        builder.button(text="📋 Другие инструменты")
        builder.button(text="❓ Помощь")
        builder.button(text="📞 Поддержка")
        
        if message.from_user.id in self.config.ADMIN_IDS:
            builder.button(text="🔧 Админ")
        
        builder.adjust(2, 2, 1, 1)
        
        await message.answer(
            "👇 **Выберите действие:**",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )
    
    async def _handle_help(self, message: Message):
        """Помощь с картинками"""
        images = [
            ('help_main.png', '📖 Главная инструкция'),
            ('help_key.png', '🔑 Что такое Ключ'),
            ('help_step1.png', '📁 Шаг 1: Первый файл'),
            ('help_step2.png', '📁 Шаг 2: Второй файл'),
            ('help_result.png', '✨ Результат'),
            ('help_error_1.png', '❌ Ошибка №1'),
            ('help_error_2.png', '❌ Ошибка №2'),
            ('help_pivot_step1.png', '📊 Сводные: подготовка'),
            ('help_pivot_result.png', '📊 Пример сводной')
        ]
        
        for img_name, caption in images:
            img_path = Path('images') / img_name
            if img_path.exists():
                photo = FSInputFile(img_path)
                await message.answer_photo(photo, caption=caption)
        
        builder = ReplyKeyboardBuilder()
        builder.button(text="◀️ Назад в меню")
        builder.adjust(1)
        await message.answer(
            "📚 Все инструкции выше. Если остались вопросы - напишите в поддержку!",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )
    
    async def _show_admin_panel(self, message: Message):
        """Админ-панель"""
        prices = self.price_manager.get_all_prices()
        active_users = len(self.user_files) + len(self.pivot_data)
        waiting_payment = len([u for u in self.user_stats.keys() if u in self.user_files])
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔗 Установить цену (объединение)", callback_data="admin_set_price_merge")
        builder.button(text="📊 Установить цену (сводные)", callback_data="admin_set_price_pivot")
        builder.button(text="🔄 Сбросить все цены", callback_data="admin_reset_prices")
        builder.button(text="📊 Статистика", callback_data="admin_stats")
        builder.adjust(1)
        
        await message.answer(
            Messages.ADMIN_PANEL.format(
                merge_price=prices['merge'],
                pivot_price=prices['pivot'],
                other_price=prices['other'],
                active_users=active_users,
                waiting_payment=waiting_payment,
                user_id=message.from_user.id
            ),
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    
    async def start(self):
        """Запуск бота"""
        await self.dp.start_polling(self.bot)