import asyncpg
import json
import os

# Connection string из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_vkobaOxLN6S9@ep-fragrant-term-almpg8n6-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require")

# Глобальный пул соединений
_pool = None

async def get_pool():
    """Получить или создать пул соединений"""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool

async def close_pool():
    """Закрыть пул соединений"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

async def init_db():
    """Инициализация таблиц в PostgreSQL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id BIGINT PRIMARY KEY,
                cookies TEXT,
                group_name TEXT,
                notify_grades INTEGER DEFAULT 1,
                notify_timetable INTEGER DEFAULT 1,
                grades_time TEXT DEFAULT '07:00',
                timetable_time TEXT DEFAULT '00:01',
                last_grades_message_id BIGINT
            )
        """)

async def save_cookies(user_id: int, cookies: dict, group_name: str = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (user_id, cookies, group_name) 
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) 
            DO UPDATE SET cookies = $2, group_name = $3
            """,
            user_id, json.dumps(cookies), group_name
        )

async def get_cookies(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT cookies FROM sessions WHERE user_id = $1", user_id
        )
    return json.loads(row['cookies']) if row else None

async def get_group(user_id: int) -> str | None:
    """Получить группу пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT group_name FROM sessions WHERE user_id = $1", user_id
        )
    return row['group_name'] if row else None

async def save_group(user_id: int, group_name: str):
    """Сохранить группу пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Проверяем, есть ли пользователь в таблице
        row = await conn.fetchrow("SELECT user_id FROM sessions WHERE user_id = $1", user_id)
        
        if row:
            # Обновляем существующую запись
            await conn.execute(
                "UPDATE sessions SET group_name = $1 WHERE user_id = $2",
                group_name, user_id
            )
        else:
            # Создаём новую запись с группой
            await conn.execute(
                "INSERT INTO sessions (user_id, group_name) VALUES ($1, $2)",
                user_id, group_name
            )

async def delete_cookies(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)

async def get_all_users() -> list[int]:
    """Получить список всех user_id с активными сессиями"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM sessions")
    return [row['user_id'] for row in rows]

async def get_user_settings(user_id: int) -> dict:
    """Получить настройки пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT notify_grades, notify_timetable, grades_time, timetable_time FROM sessions WHERE user_id = $1",
            user_id
        )
    
    if row:
        return {
            "notify_grades": bool(row['notify_grades']),
            "notify_timetable": bool(row['notify_timetable']),
            "grades_time": row['grades_time'],
            "timetable_time": row['timetable_time']
        }
    return {
        "notify_grades": True,
        "notify_timetable": True,
        "grades_time": "07:00",
        "timetable_time": "00:01"
    }

async def update_user_settings(user_id: int, notify_grades: bool = None, notify_timetable: bool = None, 
                               grades_time: str = None, timetable_time: str = None):
    """Обновить настройки пользователя"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        updates = []
        params = []
        param_num = 1
        
        if notify_grades is not None:
            updates.append(f"notify_grades = ${param_num}")
            params.append(1 if notify_grades else 0)
            param_num += 1
        if notify_timetable is not None:
            updates.append(f"notify_timetable = ${param_num}")
            params.append(1 if notify_timetable else 0)
            param_num += 1
        if grades_time is not None:
            updates.append(f"grades_time = ${param_num}")
            params.append(grades_time)
            param_num += 1
        if timetable_time is not None:
            updates.append(f"timetable_time = ${param_num}")
            params.append(timetable_time)
            param_num += 1
        
        if updates:
            params.append(user_id)
            query = f"UPDATE sessions SET {', '.join(updates)} WHERE user_id = ${param_num}"
            await conn.execute(query, *params)

async def save_last_grades_message(user_id: int, message_id: int):
    """Сохранить ID последнего сообщения с оценками"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET last_grades_message_id = $1 WHERE user_id = $2",
            message_id, user_id
        )

async def get_last_grades_message(user_id: int) -> int | None:
    """Получить ID последнего сообщения с оценками"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_grades_message_id FROM sessions WHERE user_id = $1", user_id
        )
    return row['last_grades_message_id'] if row and row['last_grades_message_id'] else None

async def backup_users_to_file():
    """Сохранить список всех пользователей в файл"""
    users = await get_all_users()
    with open("users_backup.txt", "w") as f:
        for user_id in users:
            f.write(f"{user_id}\n")
    return len(users)
