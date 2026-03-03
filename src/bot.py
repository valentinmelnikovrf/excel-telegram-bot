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

logger = logging.getLogger(__name__)

# Состояния FSM
class VLookupStates(StatesGroup):
    waiting_main_file = State()
    waiting_source_file = State()
    files_validated = State()
    waiting_payment = State()
    waiting_price_input = State()

class ExcelBot:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.BOT_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.excel_processor = ExcelProcessor()
        self.excel_validator = ExcelValidator()
        self.payment_handler = PaymentHandler(self.bot)
        self.price_manager = PriceManager(config)
        self.user_files = {}
        self.user_stats = {}
        self.user_service = {}
        self._register_handlers()
    
    def _register_handlers(self):
        
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
            await state.clear()
            await message.answer(Messages.MERGE_CANCELLED)
            await self._handle_start(message)
        
        @self.dp.message(F.text.contains("🔗 Объединить таблицы"))
        async def select_merge_service(message: Message, state: FSMContext):
            user_id = message.from_user.id
            self.user_service[user_id] = 'merge'
            price = self.price_manager.get_price('merge')
            
            await state.set_state(VLookupStates.waiting_main_file)
            
            # Отправляем картинку-инструкцию
            image_path = Path('images/help_step1.png')
            if image_path.exists():
                photo = FSInputFile(image_path)
                await message.answer_photo(photo, caption="📌 Как подготовить первый файл")
            
            # Кнопка отмены
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
            
            builder = ReplyKeyboardBuilder()
            builder.button(text="◀️ Назад в меню")
            builder.adjust(1)
            
            await message.answer(
                Messages.PIVOT_COMING_SOON.format(price=price),
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
        
        # ИСПРАВЛЕННЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ АДМИН
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
            await self._handle_start(message)
        
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
            
            # Отправляем картинку про второй файл
            image_path = Path('images/help_step2.png')
            if image_path.exists():
                photo = FSInputFile(image_path)
                await message.answer_photo(photo, caption="📌 Как подготовить второй файл")
            
            # Кнопка отмены
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
            
            # Отправляем сообщение о начале проверки
            status_msg = await message.answer(Messages.MERGE_VALIDATING)
            
            # Проверяем файлы
            is_valid, validation_msg, stats = await self.excel_validator.validate_files(
                self.user_files[user_id]['main'],
                self.user_files[user_id]['source']
            )
            
            await status_msg.delete()
            
            if not is_valid:
                # Отправляем картинки с ошибками
                error_img1 = Path('images/help_error_1.png')
                error_img2 = Path('images/help_error_2.png')
                
                if error_img1.exists():
                    photo = FSInputFile(error_img1)
                    await message.answer_photo(photo)
                
                if error_img2.exists():
                    photo = FSInputFile(error_img2)
                    await message.answer_photo(photo)
                
                # Кнопки для действий
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
            
            # Сохраняем статистику
            self.user_stats[user_id] = stats
            
            # Получаем цену для выбранной услуги
            service = self.user_service.get(user_id, 'merge')
            price = self.price_manager.get_price(service)
            
            # Создаем клавиатуру для подтверждения
            builder = InlineKeyboardBuilder()
            builder.button(text=f"✅ Да, оплатить {price}⭐", callback_data="proceed_to_payment")
            builder.button(text="❌ Нет, отменить", callback_data="cancel_operation")
            builder.adjust(1)
            
            # Отправляем картинку с результатом
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
        
        @self.dp.message(F.successful_payment)
        async def process_successful_payment(message: Message, state: FSMContext):
            user_id = message.from_user.id
            
            if user_id not in self.user_files or 'main' not in self.user_files[user_id] or 'source' not in self.user_files[user_id]:
                await message.answer("❌ Ошибка: файлы не найдены. Начните заново с /start")
                await state.clear()
                return
            
            status_msg = await message.answer(Messages.MERGE_PROCESSING)
            
            # Выполняем ВПР
            result_path = await self.excel_processor.vlookup_merge(
                self.user_files[user_id]['main'],
                self.user_files[user_id]['source']
            )
            
            if result_path and result_path.exists():
                await status_msg.delete()
                
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
                await status_msg.edit_text("❌ Ошибка при обработке файлов. Попробуйте снова.")
                await self._cleanup_user_files(user_id)
            
            await state.clear()
        
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
                active_users = len(self.user_files)
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
    
    async def _cleanup_user_files(self, user_id: int):
        if user_id in self.user_files:
            for file_path in self.user_files[user_id].values():
                with suppress(Exception):
                    file_path.unlink(missing_ok=True)
            del self.user_files[user_id]
    
    async def _handle_start(self, message: Message):
        prices = self.price_manager.get_all_prices()
        
        # Сначала отправляем приветствие с описаниями
        await message.answer(
            Messages.MAIN_MENU.format(
                merge_price=prices['merge'],
                pivot_price=prices['pivot']
            ),
            parse_mode="Markdown"
        )
        
        # Затем отправляем клавиатуру с кнопками
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
        # Отправляем все обучающие картинки
        images = [
            ('help_main.png', '📖 Главная инструкция'),
            ('help_key.png', '🔑 Что такое Ключ'),
            ('help_step1.png', '📁 Шаг 1: Первый файл'),
            ('help_step2.png', '📁 Шаг 2: Второй файл'),
            ('help_result.png', '✨ Результат'),
            ('help_error_1.png', '❌ Ошибка №1'),
            ('help_error_2.png', '❌ Ошибка №2')
        ]
        
        for img_name, caption in images:
            img_path = Path('images') / img_name
            if img_path.exists():
                photo = FSInputFile(img_path)
                await message.answer_photo(photo, caption=caption)
        
        # Кнопка возврата
        builder = ReplyKeyboardBuilder()
        builder.button(text="◀️ Назад в меню")
        builder.adjust(1)
        
        await message.answer(
            "📚 Все инструкции выше. Если остались вопросы - напишите в поддержку!",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )
    
    async def _show_admin_panel(self, message: Message):
        prices = self.price_manager.get_all_prices()
        active_users = len(self.user_files)
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
        await self.dp.start_polling(self.bot)