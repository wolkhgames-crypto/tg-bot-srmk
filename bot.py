import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, ChatTypeFilter
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp_socks import ProxyConnector
from dotenv import load_dotenv
import aiohttp
import os

from db import init_db, save_cookies, get_cookies, delete_cookies
from scraper import login, fetch_grades

load_dotenv()

dp = Dispatcher(storage=MemoryStorage())

class AuthStates(StatesGroup):
    waiting_login = State()
    waiting_password = State()

def main_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📅 Текущий месяц", callback_data="grades_current")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="grades_prev"),
            InlineKeyboardButton(text="➡️ Вперёд", callback_data="grades_next"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help"),
        ],
        [InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"), ChatTypeFilter(ChatType.PRIVATE))
async def cmd_start(message: Message, state: FSMContext):
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

@dp.message(ChatTypeFilter(ChatType.GROUP, ChatType.SUPERGROUP))
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

@dp.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "ℹ️ *Помощь*\n\n"
        "🔹 *Текущий месяц* - оценки за этот месяц\n"
        "🔹 *Назад/Вперёд* - навигация по месяцам\n"
        "🔹 *Статистика* - общая статистика\n"
        "🔹 *Выйти* - сменить аккаунт\n\n"
        "*Обозначения оценок:*\n"
        "🟢 5 - отлично\n"
        "🟡 4 - хорошо\n"
        "🟠 3 - удовлетворительно\n"
        "🔴 2 - неудовлетворительно",
        parse_mode="Markdown",
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

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
