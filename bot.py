import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp_socks import ProxyConnector
from dotenv import load_dotenv
import aiohttp
import os

from db import init_db, save_cookies, get_cookies, delete_cookies, get_all_users, get_group, save_group, get_user_settings, update_user_settings, save_last_grades_message, get_last_grades_message
from scraper import login, fetch_grades, fetch_timetable, search_teacher
from groups import GROUPS

load_dotenv()

dp = Dispatcher(storage=MemoryStorage())

class AuthStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()
    waiting_group = State()
    waiting_grades_time = State()
    waiting_timetable_time = State()
    waiting_admin_password = State()
    waiting_teacher_name = State()

def main_keyboard():
    now = datetime.now()
    buttons = [
        [InlineKeyboardButton(text="📊 Электронный дневник", callback_data="grades_current")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grades_{now.year}_{now.month}_prev"),
            InlineKeyboardButton(text="➡️ Вперёд", callback_data=f"grades_{now.year}_{now.month}_next"),
        ],
        [
            InlineKeyboardButton(text="📋 Расписание", callback_data="timetable"),
            InlineKeyboardButton(text="👁️ Поиск преподавателя", callback_data="search_teacher"),
        ],
        [
            InlineKeyboardButton(text="🔄 Сменить группу", callback_data="change_group"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help"),
            InlineKeyboardButton(text="🔐 Admin", callback_data="admin"),
        ],
        [InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def reply_keyboard():
    """Постоянная клавиатура внизу экрана"""
    buttons = [
        [KeyboardButton(text="📅 Оценки"), KeyboardButton(text="📋 Расписание")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="ℹ️ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Проверка на личный чат
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("❌ Бот работает только в личных сообщениях. Напиши мне в личку: @john_srmk_bot")
        return
    
    # Проверяем, авторизован ли пользователь
    cookies = await get_cookies(message.from_user.id)
    if not cookies:
        await message.answer(
            "👋 Привет! Я бот для просмотра оценок и расписания СРМК.\n\n"
            "Для начала работы нужно авторизоваться.\n\n"
            "Введи свой *логин от электронного дневника*:",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.waiting_login)
        return
    
    await message.answer(
        "👋 Привет! Ты уже авторизован.\n\n"
        "Выбери действие:",
        reply_markup=reply_keyboard()
    )

# Обработчики для постоянных кнопок
@dp.message(F.text == "📅 Оценки")
async def btn_grades(message: Message, state: FSMContext):
    cookies = await get_cookies(message.from_user.id)
    if not cookies:
        await message.answer("❌ Сессия истекла. Войди снова — /start")
        return
    
    # Удаляем предыдущее сообщение с оценками
    last_msg_id = await get_last_grades_message(message.from_user.id)
    if last_msg_id:
        try:
            await message.bot.delete_message(message.chat.id, last_msg_id)
        except:
            pass  # Сообщение уже удалено или недоступно
    
    now = datetime.now()
    msg = await message.answer("⏳ Загружаю оценки...")
    result = await fetch_grades(cookies, now.year, now.month)
    
    if result is None:
        await delete_cookies(message.from_user.id)
        await msg.edit_text("🔒 Сессия истекла, нужно войти снова — /start")
        return
    
    new_msg = await msg.edit_text(result, parse_mode="Markdown", reply_markup=main_keyboard())
    # Сохраняем ID нового сообщения
    await save_last_grades_message(message.from_user.id, new_msg.message_id)

@dp.message(F.text == "📋 Расписание")
async def btn_timetable(message: Message, state: FSMContext):
    group_id = await get_group(message.from_user.id)
    if not group_id:
        await message.answer(
            "❌ Группа не указана.\n\n"
            "Для просмотра расписания укажи свою группу (например: П-21):",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.waiting_group)
        return
    
    cookies = await get_cookies(message.from_user.id)
    if not cookies:
        await message.answer("❌ Сессия истекла. Войди снова — /start")
        return
    
    msg = await message.answer("⏳ Загружаю расписание...")
    now = datetime.now()
    result = await fetch_timetable(cookies, group_id, now.year, now.month)
    
    if result is None:
        await delete_cookies(message.from_user.id)
        await msg.edit_text("🔒 Сессия истекла, нужно войти снова — /start")
        return
    
    await msg.edit_text(result, parse_mode="Markdown", reply_markup=main_keyboard())

@dp.message(F.text == "⚙️ Настройки")
async def btn_settings(message: Message):
    settings = await get_user_settings(message.from_user.id)
    
    grades_status = "✅ Включено" if settings["notify_grades"] else "❌ Выключено"
    timetable_status = "✅ Включено" if settings["notify_timetable"] else "❌ Выключено"
    
    buttons = [
        [InlineKeyboardButton(
            text=f"Оценки: {grades_status}",
            callback_data="toggle_grades"
        )],
        [InlineKeyboardButton(
            text=f"Расписание: {timetable_status}",
            callback_data="toggle_timetable"
        )],
        [InlineKeyboardButton(
            text=f"⏰ Время оценок: {settings['grades_time']}",
            callback_data="set_grades_time"
        )],
        [InlineKeyboardButton(
            text=f"⏰ Время расписания: {settings['timetable_time']}",
            callback_data="set_timetable_time"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ]
    
    await message.answer(
        "⚙️ *Настройки уведомлений*\n\n"
        "Управляй автоматическими рассылками:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.message(F.text == "ℹ️ Помощь")
async def btn_help(message: Message):
    await message.answer(
        "ℹ️ *Помощь*\n\n"
        "🔹 *Электронный дневник* - оценки за текущий месяц\n"
        "🔹 *Назад/Вперёд* - навигация по месяцам\n"
        "🔹 *Расписание* - расписание занятий\n"
        "🔹 *Сменить группу* - изменить группу\n"
        "🔹 *Настройки* - управление рассылками\n"
        "🔹 *Выйти* - сменить аккаунт\n\n"
        "📬 *Автоматические рассылки*\n"
        "• 00:01 - расписание на день\n"
        "• 7:00 - оценки (кроме воскресенья)\n\n"
        "Управляй рассылками в разделе ⚙️ Настройки",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ *Помощь*\n\n"
        "🔹 *Электронный дневник* - оценки за текущий месяц\n"
        "🔹 *Назад/Вперёд* - навигация по месяцам\n"
        "🔹 *Расписание* - расписание занятий\n"
        "🔹 *Сменить группу* - изменить группу\n"
        "🔹 *Настройки* - управление рассылками\n"
        "🔹 *Выйти* - сменить аккаунт\n\n"
        "📬 *Автоматические рассылки*\n"
        "• 00:01 - расписание на день\n"
        "• 7:00 - оценки (кроме воскресенья)\n\n"
        "Управляй рассылками в разделе ⚙️ Настройки",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def block_groups(message: Message):
    await message.answer("❌ Бот работает только в личных сообщениях. Напиши мне в личку: @john_srmk_bot")

@dp.message(AuthStates.waiting_login)
async def process_login(message: Message, state: FSMContext):
    await state.update_data(username=message.text)
    await message.delete()  # удаляем сообщение с логином
    await message.answer("🔒 Теперь введи *пароль*:", parse_mode="Markdown")
    await state.set_state(AuthStates.waiting_password)

@dp.message(AuthStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    await message.delete()  # удаляем пароль из чата!
    data = await state.get_data()
    
    wait_msg = await message.answer("⏳ Авторизуюсь...")
    
    try:
        cookies = await login(data["username"], message.text)
        await state.clear()
        
        if cookies:
            await save_cookies(message.from_user.id, cookies)
            await wait_msg.edit_text("✅ Успешно! Теперь можешь пользоваться ботом.")
            # Показываем постоянную клавиатуру
            await message.answer(
                "Выбери действие:",
                reply_markup=reply_keyboard()
            )
        else:
            await wait_msg.edit_text(
                "❌ Неверный логин или пароль.\n"
                "Попробуй снова — /start"
            )
    except Exception as e:
        await wait_msg.edit_text(
            "❌ Ошибка подключения к серверу.\n"
            "Попробуй позже — /start"
        )
        await state.clear()

@dp.message(AuthStates.waiting_group)
async def process_group(message: Message, state: FSMContext):
    group_name = message.text.strip().upper()
    
    group_id = GROUPS.get(group_name)
    
    if group_id:
        await save_group(message.from_user.id, group_id)
        await state.clear()
        await message.answer(
            f"✅ Группа {group_name} сохранена!\n\n"
            "Выбери действие:",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            f"❌ Группа {group_name} не найдена.\n\n"
            "Попробуй ещё раз (например: П-21):"
        )

async def send_grades(callback: CallbackQuery, year: int, month: int):
    await callback.answer()
    
    # Удаляем предыдущее сообщение с оценками
    last_msg_id = await get_last_grades_message(callback.from_user.id)
    if last_msg_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, last_msg_id)
        except:
            pass  # Сообщение уже удалено или недоступно
    
    msg = await callback.message.answer("⏳ Загружаю оценки...")
    
    try:
        cookies = await get_cookies(callback.from_user.id)
        if not cookies:
            await msg.edit_text("❌ Сессия истекла. Войди снова — /start")
            return
        
        result = await fetch_grades(cookies, year, month)
        
        if result is None:
            # Сессия протухла
            await delete_cookies(callback.from_user.id)
            await msg.edit_text("🔒 Сессия истекла, нужно войти снова — /start")
            return
        
        # Создаём кнопки навигации с текущим месяцем
        buttons = [
            [InlineKeyboardButton(text="📊 Электронный дневник", callback_data="grades_current")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grades_{year}_{month}_prev"),
                InlineKeyboardButton(text="➡️ Вперёд", callback_data=f"grades_{year}_{month}_next"),
            ],
            [
                InlineKeyboardButton(text="📋 Расписание", callback_data="timetable"),
                InlineKeyboardButton(text="🔐 Admin", callback_data="admin"),
            ],
            [
                InlineKeyboardButton(text="🔄 Сменить группу", callback_data="change_group"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            ],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
            [InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")],
        ]
        
        if "❌ Сервер недоступен" in result:
            new_msg = await msg.edit_text(result, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            new_msg = await msg.edit_text(result, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        
        # Сохраняем ID нового сообщения
        await save_last_grades_message(callback.from_user.id, new_msg.message_id)
    except Exception as e:
        await msg.edit_text(
            "❌ Произошла ошибка при загрузке оценок.\n"
            "Попробуй позже.",
            reply_markup=main_keyboard()
        )

@dp.callback_query(F.data == "grades_current")
async def grades_current(callback: CallbackQuery):
    now = datetime.now()
    await send_grades(callback, now.year, now.month)

@dp.callback_query(F.data.startswith("grades_") & F.data.endswith("_prev"))
async def grades_prev(callback: CallbackQuery):
    # Извлекаем год и месяц из callback_data
    parts = callback.data.split("_")
    year = int(parts[1])
    month = int(parts[2])
    
    # Переходим на месяц назад
    month = month - 1 if month > 1 else 12
    year = year if month != 12 else year - 1
    await send_grades(callback, year, month)

@dp.callback_query(F.data.startswith("grades_") & F.data.endswith("_next"))
async def grades_next(callback: CallbackQuery):
    # Извлекаем год и месяц из callback_data
    parts = callback.data.split("_")
    year = int(parts[1])
    month = int(parts[2])
    
    # Переходим на месяц вперёд
    month = month + 1 if month < 12 else 1
    year = year if month != 1 else year + 1
    await send_grades(callback, year, month)

@dp.callback_query(F.data == "admin")
async def show_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        "🔐 *Админ-панель*\n\n"
        "Введи пароль для доступа:",
        parse_mode="Markdown"
    )
    await state.set_state(AuthStates.waiting_admin_password)

@dp.message(AuthStates.waiting_admin_password)
async def process_admin_password(message: Message, state: FSMContext):
    await message.delete()  # Удаляем пароль из чата
    
    if message.text == "Wa9n8d77!!":
        await state.clear()
        
        # Получаем статистику
        users = await get_all_users()
        total_users = len(users)
        
        # Получаем количество пользователей с активными уведомлениями
        active_grades = 0
        active_timetable = 0
        
        for user_id in users:
            settings = await get_user_settings(user_id)
            if settings["notify_grades"]:
                active_grades += 1
            if settings["notify_timetable"]:
                active_timetable += 1
        
        # Создаём кнопки админ-панели
        buttons = [
            [InlineKeyboardButton(text="👁️ Поиск преподавателя", callback_data="admin_search_teacher")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ]
        
        await message.answer(
            f"🔐 *Админ-панель*\n\n"
            f"📊 *Статистика бота:*\n"
            f"• Всего пользователей: {total_users}\n"
            f"• Уведомления об оценках: {active_grades}\n"
            f"• Уведомления о расписании: {active_timetable}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        await state.clear()
        await message.answer(
            "❌ Неверный пароль!",
            reply_markup=main_keyboard()
        )

@dp.callback_query(F.data == "change_group")
async def change_group(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_group = await get_group(callback.from_user.id)
    
    if current_group:
        # Находим название группы по ID
        group_name = None
        for name, gid in GROUPS.items():
            if gid == current_group:
                group_name = name
                break
        
        await callback.message.edit_text(
            f"Текущая группа: *{group_name or 'не найдена'}*\n\n"
            "Введи новую группу (например: П-22):",
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "Группа не указана.\n\n"
            "Введи свою группу (например: П-21):"
        )
    
    await state.set_state(AuthStates.waiting_group)

@dp.callback_query(F.data == "timetable")
async def show_timetable(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    group_id = await get_group(callback.from_user.id)
    if not group_id:
        await callback.message.answer(
            "❌ Группа не указана.\n\n"
            "Для просмотра расписания укажи свою группу (например: П-21):",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.waiting_group)
        return
    
    msg = await callback.message.answer("⏳ Загружаю расписание...")
    
    try:
        cookies = await get_cookies(callback.from_user.id)
        if not cookies:
            await msg.edit_text("❌ Сессия истекла. Войди снова — /start")
            return
        
        now = datetime.now()
        result = await fetch_timetable(cookies, group_id, now.year, now.month)
        
        if result is None:
            await delete_cookies(callback.from_user.id)
            await msg.edit_text("🔒 Сессия истекла, нужно войти снова — /start")
            return
        
        await msg.edit_text(result, parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        await msg.edit_text(
            "❌ Произошла ошибка при загрузке расписания.\n"
            "Попробуй позже.",
            reply_markup=main_keyboard()
        )

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "ℹ️ *Помощь*\n\n"
        "🔹 *Электронный дневник* - оценки за текущий месяц\n"
        "🔹 *Назад/Вперёд* - навигация по месяцам\n"
        "🔹 *Расписание* - расписание занятий\n"
        "🔹 *Поиск преподавателя* - найти все пары преподавателя\n"
        "🔹 *Сменить группу* - изменить группу\n"
        "🔹 *Настройки* - управление рассылками\n"
        "🔹 *Выйти* - сменить аккаунт\n\n"
        "📬 *Автоматические рассылки*\n"
        "• 00:01 - расписание на день\n"
        "• 7:00 - оценки (кроме воскресенья)",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery):
    await callback.answer()
    settings = await get_user_settings(callback.from_user.id)
    
    grades_status = "✅ Включено" if settings["notify_grades"] else "❌ Выключено"
    timetable_status = "✅ Включено" if settings["notify_timetable"] else "❌ Выключено"
    
    buttons = [
        [InlineKeyboardButton(
            text=f"Оценки: {grades_status}",
            callback_data="toggle_grades"
        )],
        [InlineKeyboardButton(
            text=f"Расписание: {timetable_status}",
            callback_data="toggle_timetable"
        )],
        [InlineKeyboardButton(
            text=f"⏰ Время оценок: {settings['grades_time']}",
            callback_data="set_grades_time"
        )],
        [InlineKeyboardButton(
            text=f"⏰ Время расписания: {settings['timetable_time']}",
            callback_data="set_timetable_time"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ]
    
    await callback.message.edit_text(
        "⚙️ *Настройки уведомлений*\n\n"
        "Управляй автоматическими рассылками:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data == "toggle_grades")
async def toggle_grades(callback: CallbackQuery):
    settings = await get_user_settings(callback.from_user.id)
    new_value = not settings["notify_grades"]
    await update_user_settings(callback.from_user.id, notify_grades=new_value)
    await show_settings(callback)

@dp.callback_query(F.data == "toggle_timetable")
async def toggle_timetable(callback: CallbackQuery):
    settings = await get_user_settings(callback.from_user.id)
    new_value = not settings["notify_timetable"]
    await update_user_settings(callback.from_user.id, notify_timetable=new_value)
    await show_settings(callback)

@dp.callback_query(F.data == "set_grades_time")
async def set_grades_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        "⏰ Введи время для рассылки оценок\n\n"
        "Формат: ЧЧ:ММ (например: 08:00)\n"
        "Текущее время по МСК"
    )
    await state.set_state(AuthStates.waiting_grades_time)

@dp.callback_query(F.data == "set_timetable_time")
async def set_timetable_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        "⏰ Введи время для рассылки расписания\n\n"
        "Формат: ЧЧ:ММ (например: 00:01)\n"
        "Текущее время по МСК"
    )
    await state.set_state(AuthStates.waiting_timetable_time)

@dp.message(AuthStates.waiting_grades_time)
async def process_grades_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    
    # Проверка формата времени
    import re
    if re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
        # Нормализуем формат времени (добавляем ведущий ноль)
        parts = time_str.split(':')
        normalized_time = f"{int(parts[0]):02d}:{parts[1]}"
        
        await update_user_settings(message.from_user.id, grades_time=normalized_time)
        await state.clear()
        await message.answer(
            f"✅ Время рассылки оценок установлено: {normalized_time}",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            "❌ Неверный формат времени.\n"
            "Используй формат ЧЧ:ММ (например: 08:00)"
        )

@dp.message(AuthStates.waiting_timetable_time)
async def process_timetable_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    
    # Проверка формата времени
    import re
    if re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
        # Нормализуем формат времени (добавляем ведущий ноль)
        parts = time_str.split(':')
        normalized_time = f"{int(parts[0]):02d}:{parts[1]}"
        
        await update_user_settings(message.from_user.id, timetable_time=normalized_time)
        await state.clear()
        await message.answer(
            f"✅ Время рассылки расписания установлено: {normalized_time}",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            "❌ Неверный формат времени.\n"
            "Используй формат ЧЧ:ММ (например: 00:01)"
        )

@dp.callback_query(F.data == "search_teacher")
async def search_teacher_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        "👁️ *Поиск преподавателя*\n\n"
        "Введи фамилию преподавателя для поиска:\n"
        "(например: Дудина)",
        parse_mode="Markdown"
    )
    await state.set_state(AuthStates.waiting_teacher_name)

@dp.callback_query(F.data == "admin_search_teacher")
async def admin_search_teacher(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text(
        "👁️ *Поиск преподавателя*\n\n"
        "Введи фамилию преподавателя для поиска:\n"
        "(например: Дудина)",
        parse_mode="Markdown"
    )
    await state.set_state(AuthStates.waiting_teacher_name)

@dp.message(AuthStates.waiting_teacher_name)
async def process_teacher_name(message: Message, state: FSMContext):
    await message.delete()  # Удаляем сообщение пользователя
    teacher_name = message.text.strip()
    
    msg = await message.answer(f"⏳ Ищу преподавателя {teacher_name} во всех группах...\nЭто может занять 1-2 минуты.")
    
    try:
        cookies = await get_cookies(message.from_user.id)
        if not cookies:
            await msg.edit_text("❌ Сессия истекла. Войди снова — /start")
            await state.clear()
            return
        
        # Ищем преподавателя во всех группах
        result = await search_teacher(cookies, teacher_name)
        
        await state.clear()
        
        buttons = [
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ]
        
        await msg.edit_text(
            result,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        await state.clear()
        buttons = [
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ]
        await msg.edit_text(
            f"❌ Ошибка при поиске: {str(e)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await callback.answer()
    
    # Получаем статистику заново
    users = await get_all_users()
    total_users = len(users)
    
    active_grades = 0
    active_timetable = 0
    
    for user_id in users:
        settings = await get_user_settings(user_id)
        if settings["notify_grades"]:
            active_grades += 1
        if settings["notify_timetable"]:
            active_timetable += 1
    
    # Создаём кнопки админ-панели
    buttons = [
        [InlineKeyboardButton(text="👁️ Поиск преподавателя", callback_data="admin_search_teacher")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ]
    
    await callback.message.edit_text(
        f"🔐 *Админ-панель*\n\n"
        f"📊 *Статистика бота:*\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Уведомления об оценках: {active_grades}\n"
        f"• Уведомления о расписании: {active_timetable}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Выбери действие:",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "logout")
async def logout(callback: CallbackQuery, state: FSMContext):
    await delete_cookies(callback.from_user.id)
    await callback.message.edit_text("👋 Вышел из аккаунта.")
    await callback.answer()
    await callback.message.answer(
        "Введи логин для входа:", parse_mode="Markdown"
    )
    await state.set_state(AuthStates.waiting_login)

async def scheduler(bot: Bot):
    """Планировщик ежедневной рассылки"""
    MSK = timezone(timedelta(hours=3))
    
    while True:
        now = datetime.now(MSK)
        current_time = now.strftime("%H:%M")
        
        logging.info(f"Scheduler check (MSK): {current_time}")
        
        # Проверяем всех пользователей и их настройки времени
        users = await get_all_users()
        
        for user_id in users:
            try:
                settings = await get_user_settings(user_id)
                
                logging.info(f"User {user_id}: grades={settings['notify_grades']}, time={settings['grades_time']}, timetable={settings['notify_timetable']}, time={settings['timetable_time']}")
                
                # Проверяем время для расписания
                if settings["notify_timetable"] and settings["timetable_time"] == current_time:
                    logging.info(f"Sending timetable to {user_id}")
                    cookies = await get_cookies(user_id)
                    group_id = await get_group(user_id)
                    
                    if cookies and group_id:
                        result = await fetch_timetable(cookies, group_id, now.year, now.month)
                        if result and "❌" not in result and "📭" not in result:
                            await bot.send_message(
                                user_id,
                                f"🌙 *Расписание на сегодня*\n\n{result}",
                                parse_mode="Markdown"
                            )
                
                # Проверяем время для оценок (кроме воскресенья)
                if settings["notify_grades"] and settings["grades_time"] == current_time and now.weekday() != 6:
                    logging.info(f"Sending grades to {user_id}")
                    cookies = await get_cookies(user_id)
                    
                    if cookies:
                        # Удаляем предыдущее сообщение с оценками
                        last_msg_id = await get_last_grades_message(user_id)
                        if last_msg_id:
                            try:
                                await bot.delete_message(user_id, last_msg_id)
                            except:
                                pass  # Сообщение уже удалено или недоступно
                        
                        result = await fetch_grades(cookies, now.year, now.month)
                        if result and "❌" not in result:
                            msg = await bot.send_message(
                                user_id,
                                f"📅 *Ежедневная сводка оценок*\n\n{result}",
                                parse_mode="Markdown"
                            )
                            # Сохраняем ID нового сообщения
                            await save_last_grades_message(user_id, msg.message_id)
            except Exception as e:
                logging.error(f"Ошибка рассылки пользователю {user_id}: {e}")
        
        await asyncio.sleep(60)  # Проверяем каждую минуту

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    
    # Запускаем планировщик в фоне
    asyncio.create_task(scheduler(bot))
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
