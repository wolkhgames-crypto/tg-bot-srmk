import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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

from db import init_db, save_cookies, get_cookies, delete_cookies, get_all_users, get_group, save_group, get_user_settings, update_user_settings
from scraper import login, fetch_grades, fetch_timetable
from groups import GROUPS

load_dotenv()

dp = Dispatcher(storage=MemoryStorage())

class AuthStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()
    waiting_group = State()

def main_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📅 Текущий месяц", callback_data="grades_current")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="grades_prev"),
            InlineKeyboardButton(text="➡️ Вперёд", callback_data="grades_next"),
        ],
        [
            InlineKeyboardButton(text="📋 Расписание", callback_data="timetable"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
        ],
        [
            InlineKeyboardButton(text="🔄 Сменить группу", callback_data="change_group"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
        [InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Проверка на личный чат
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("❌ Бот работает только в личных сообщениях. Напиши мне в личку: @john_srmk_bot")
        return
    
    cookies = await get_cookies(message.from_user.id)
    if cookies:
        await message.answer(
            "👋 Ты уже авторизован!\nВыбери действие:",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            "👋 Привет! Введи свой *логин* (email) от портала:",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.waiting_login)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ *Помощь*\n\n"
        "🔹 *Текущий месяц* - оценки за этот месяц\n"
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
            await wait_msg.edit_text(
                "✅ Успешно! Выбери действие:",
                reply_markup=main_keyboard()
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
    msg = await callback.message.edit_text("⏳ Загружаю оценки...")
    
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
        
        if "❌ Сервер недоступен" in result:
            await msg.edit_text(result, reply_markup=main_keyboard())
        else:
            await msg.edit_text(result, parse_mode="Markdown", reply_markup=main_keyboard())
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

@dp.callback_query(F.data == "grades_prev")
async def grades_prev(callback: CallbackQuery):
    now = datetime.now()
    month = now.month - 1 or 12
    year = now.year if now.month > 1 else now.year - 1
    await send_grades(callback, year, month)

@dp.callback_query(F.data == "grades_next")
async def grades_next(callback: CallbackQuery):
    now = datetime.now()
    month = now.month % 12 + 1
    year = now.year if now.month < 12 else now.year + 1
    await send_grades(callback, year, month)

@dp.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "📊 *Статистика*\n\n"
        "Эта функция покажет:\n"
        "• Средний балл за семестр\n"
        "• Количество оценок по предметам\n"
        "• Динамику успеваемости\n\n"
        "_Функция в разработке..._",
        parse_mode="Markdown",
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
        await callback.message.edit_text(
            "❌ Группа не указана.\n\n"
            "Для просмотра расписания укажи свою группу (например: П-21):",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.waiting_group)
        return
    
    msg = await callback.message.edit_text("⏳ Загружаю расписание...")
    
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
        "🔹 *Текущий месяц* - оценки за этот месяц\n"
        "🔹 *Назад/Вперёд* - навигация по месяцам\n"
        "🔹 *Расписание* - расписание занятий\n"
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

async def send_daily_grades(bot: Bot):
    """Отправка оценок всем пользователям"""
    now = datetime.now()
    users = await get_all_users()
    
    for user_id in users:
        try:
            settings = await get_user_settings(user_id)
            if not settings["notify_grades"]:
                continue
            
            cookies = await get_cookies(user_id)
            if cookies:
                result = await fetch_grades(cookies, now.year, now.month)
                if result and "❌" not in result:
                    await bot.send_message(
                        user_id,
                        f"📅 *Ежедневная сводка оценок*\n\n{result}",
                        parse_mode="Markdown"
                    )
        except Exception as e:
            logging.error(f"Ошибка отправки оценок пользователю {user_id}: {e}")

async def send_daily_timetable(bot: Bot):
    """Отправка расписания всем пользователям в 00:01"""
    now = datetime.now()
    users = await get_all_users()
    
    for user_id in users:
        try:
            settings = await get_user_settings(user_id)
            if not settings["notify_timetable"]:
                continue
            
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
        except Exception as e:
            logging.error(f"Ошибка отправки расписания пользователю {user_id}: {e}")

async def scheduler(bot: Bot):
    """Планировщик ежедневной рассылки"""
    while True:
        now = datetime.now()
        
        # Отправляем расписание в 00:01 каждый день
        if now.hour == 0 and now.minute == 1:
            await send_daily_timetable(bot)
            await asyncio.sleep(60)  # Ждём минуту, чтобы не отправить дважды
        # Отправляем оценки в 7:00 каждый день, кроме воскресенья (weekday 6)
        elif now.hour == 7 and now.minute == 0 and now.weekday() != 6:
            await send_daily_grades(bot)
            await asyncio.sleep(60)  # Ждём минуту, чтобы не отправить дважды
        else:
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд

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
