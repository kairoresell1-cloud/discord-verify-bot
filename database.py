import os
import aiosqlite
import time
import random

DB_PATH = os.getenv("DB_PATH", "verified_users.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                verified_role_id TEXT,
                stats_channel_id TEXT,
                stats_message_id TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS allowed_guilds (
                guild_id TEXT PRIMARY KEY,
                guild_name TEXT,
                authorized_at REAL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS verified_users (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                verified_at REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.commit()


# ---------- WHITELIST SERVER AUTORIZZATI ----------

async def add_allowed_guild(guild_id: str, guild_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO allowed_guilds (guild_id, guild_name, authorized_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET guild_name=excluded.guild_name
            """,
            (guild_id, guild_name, time.time()),
        )
        await db.commit()


async def remove_allowed_guild(guild_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM allowed_guilds WHERE guild_id=?", (guild_id,))
        await db.commit()


async def is_guild_allowed(guild_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM allowed_guilds WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return row is not None


async def list_allowed_guilds():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM allowed_guilds ORDER BY authorized_at")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- CONFIGURAZIONE PER SERVER ----------

async def set_guild_role(guild_id: str, role_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO guild_config (guild_id, verified_role_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET verified_role_id=excluded.verified_role_id
            """,
            (guild_id, role_id),
        )
        await db.commit()


async def set_stats_message(guild_id: str, channel_id: str, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO guild_config (guild_id, stats_channel_id, stats_message_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                stats_channel_id=excluded.stats_channel_id,
                stats_message_id=excluded.stats_message_id
            """,
            (guild_id, channel_id, message_id),
        )
        await db.commit()


async def get_guild_config(guild_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_guild_configs_with_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM guild_config WHERE stats_message_id IS NOT NULL"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------- UTENTI VERIFICATI (per server) ----------

async def save_user(guild_id: str, user_id: str, username: str, access_token: str, refresh_token: str, expires_in: int):
    expires_at = time.time() + expires_in
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO verified_users (guild_id, user_id, username, access_token, refresh_token, expires_at, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                username=excluded.username,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at,
                verified_at=excluded.verified_at
            """,
            (guild_id, user_id, username, access_token, refresh_token, expires_at, time.time()),
        )
        await db.commit()


async def update_tokens(guild_id: str, user_id: str, access_token: str, refresh_token: str, expires_in: int):
    expires_at = time.time() + expires_in
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE verified_users SET access_token=?, refresh_token=?, expires_at=? WHERE guild_id=? AND user_id=?",
            (access_token, refresh_token, expires_at, guild_id, user_id),
        )
        await db.commit()


async def get_all_users(guild_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM verified_users WHERE guild_id=?", (guild_id,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def count_users(guild_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM verified_users WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return row[0]
