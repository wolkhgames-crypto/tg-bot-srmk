import aiosqlite
import json

DB = "sessions.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                cookies TEXT,
                group_name TEXT
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
