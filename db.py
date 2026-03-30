import aiosqlite
import json

DB = "sessions.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                cookies TEXT
            )
        """)
        await db.commit()

async def save_cookies(user_id: int, cookies: dict):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO sessions (user_id, cookies) VALUES (?, ?)",
            (user_id, json.dumps(cookies))
        )
        await db.commit()

async def get_cookies(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT cookies FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else None

async def delete_cookies(user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()
