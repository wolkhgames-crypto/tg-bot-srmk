import aiosqlite
import json

DB = "sessions.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                cookies TEXT,
                group_name TEXT,
                notify_grades INTEGER DEFAULT 1,
                notify_timetable INTEGER DEFAULT 1,
                grades_time TEXT DEFAULT '07:00',
                timetable_time TEXT DEFAULT '00:01',
                last_grades_message_id INTEGER
            )
        """)
        await db.commit()

async def save_cookies(user_id: int, cookies: dict, group_name: str = None):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO sessions (user_id, cookies, group_name) VALUES (?, ?, ?)",
            (user_id, json.dumps(cookies), group_name)
        )
        await db.commit()

async def get_cookies(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT cookies FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else None

async def get_group(user_id: int) -> str | None:
    """Получить группу пользователя"""
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT group_name FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def save_group(user_id: int, group_name: str):
    """Сохранить группу пользователя"""
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE sessions SET group_name = ? WHERE user_id = ?",
            (group_name, user_id)
        )
        await db.commit()

async def delete_cookies(user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_all_users() -> list[int]:
    """Получить список всех user_id с активными сессиями"""
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT user_id FROM sessions") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_user_settings(user_id: int) -> dict:
    """Получить настройки пользователя"""
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT notify_grades, notify_timetable, grades_time, timetable_time FROM sessions WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "notify_grades": bool(row[0]),
                    "notify_timetable": bool(row[1]),
                    "grades_time": row[2],
                    "timetable_time": row[3]
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
    async with aiosqlite.connect(DB) as db:
        updates = []
        params = []
        
        if notify_grades is not None:
            updates.append("notify_grades = ?")
            params.append(1 if notify_grades else 0)
        if notify_timetable is not None:
            updates.append("notify_timetable = ?")
            params.append(1 if notify_timetable else 0)
        if grades_time is not None:
            updates.append("grades_time = ?")
            params.append(grades_time)
        if timetable_time is not None:
            updates.append("timetable_time = ?")
            params.append(timetable_time)
        
        if updates:
            params.append(user_id)
            query = f"UPDATE sessions SET {', '.join(updates)} WHERE user_id = ?"
            await db.execute(query, params)
            await db.commit()

async def save_last_grades_message(user_id: int, message_id: int):
    """Сохранить ID последнего сообщения с оценками"""
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE sessions SET last_grades_message_id = ? WHERE user_id = ?",
            (message_id, user_id)
        )
        await db.commit()

async def get_last_grades_message(user_id: int) -> int | None:
    """Получить ID последнего сообщения с оценками"""
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT last_grades_message_id FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else None
