import os
import aiosqlite
import time

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

        # Configurazione GLOBALE del canale di log live (uno solo, per tutto il bot)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS log_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                channel_id TEXT,
                message_id TEXT
            )
            """
        )

        # Storico delle verifiche, usato per popolare il pannello di log live
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                username TEXT,
                guild_id TEXT,
                guild_name TEXT,
                verified_at REAL
            )
            """
        )

        # Tabella GLOBALE degli utenti verificati: chi si verifica in più
        # server diversi viene contato una sola volta (user_id è la chiave).
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS verified_users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                verified_at REAL NOT NULL,
                first_guild_id TEXT
            )
            """
        )
        await db.commit()

    await _migrate_old_schema_if_needed()


async def _migrate_old_schema_if_needed():
    """Se il DB ha ancora il vecchio schema (chiave composta guild_id+user_id,
    quindi lo stesso utente contato più volte se verificato in più server),
    lo migra automaticamente al nuovo schema globale, unificando i duplicati
    e tenendo per ciascun utente il record più recente."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("PRAGMA table_info(verified_users)")
        cols = [row[1] for row in await cur.fetchall()]

        if "guild_id" not in cols:
            return  # schema già aggiornato, niente da fare

        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM verified_users ORDER BY verified_at ASC")
        old_rows = [dict(r) for r in await cur.fetchall()]

        await db.execute("ALTER TABLE verified_users RENAME TO verified_users_old")
        await db.execute(
            """
            CREATE TABLE verified_users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                verified_at REAL NOT NULL,
                first_guild_id TEXT
            )
            """
        )

        merged = {}
        for row in old_rows:
            uid = row["user_id"]
            if uid not in merged:
                row["first_guild_id"] = row["guild_id"]
                merged[uid] = row
            elif row["verified_at"] >= merged[uid]["verified_at"]:
                first_guild = merged[uid]["first_guild_id"]
                row["first_guild_id"] = first_guild
                merged[uid] = row

        for uid, row in merged.items():
            await db.execute(
                """
                INSERT INTO verified_users
                    (user_id, username, access_token, refresh_token, expires_at, verified_at, first_guild_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, row["username"], row["access_token"], row["refresh_token"],
                 row["expires_at"], row["verified_at"], row["first_guild_id"]),
            )

        await db.execute("DROP TABLE verified_users_old")
        await db.commit()
        print(f"[MIGRAZIONE] {len(old_rows)} record uniti in {len(merged)} utenti globali unici.")


# ---------- CONFIGURAZIONE PER SERVER (ruolo verifica, pannello live stats) ----------

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


# ---------- UTENTI VERIFICATI (GLOBALI: contano una volta sola in totale) ----------

async def save_user(user_id: str, username: str, access_token: str, refresh_token: str,
                     expires_in: int, guild_id: str = None):
    expires_at = time.time() + expires_in
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO verified_users
                (user_id, username, access_token, refresh_token, expires_at, verified_at, first_guild_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at,
                verified_at=excluded.verified_at
            """,
            (user_id, username, access_token, refresh_token, expires_at, time.time(), guild_id),
        )
        await db.commit()


async def update_tokens(user_id: str, access_token: str, refresh_token: str, expires_in: int):
    expires_at = time.time() + expires_in
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE verified_users SET access_token=?, refresh_token=?, expires_at=? WHERE user_id=?",
            (access_token, refresh_token, expires_at, user_id),
        )
        await db.commit()


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM verified_users")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def count_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM verified_users")
        row = await cur.fetchone()
        return row[0]


# ---------- LOG LIVE DELLE VERIFICHE (globale, un solo canale/messaggio) ----------

async def set_log_channel(channel_id: str, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO log_config (id, channel_id, message_id)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                channel_id=excluded.channel_id,
                message_id=excluded.message_id
            """,
            (channel_id, message_id),
        )
        await db.commit()


async def get_log_channel():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM log_config WHERE id=1")
        row = await cur.fetchone()
        return dict(row) if row else None


async def add_verification_log(user_id: str, username: str, guild_id: str, guild_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO verification_log (user_id, username, guild_id, guild_name, verified_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, guild_id, guild_name, time.time()),
        )
        await db.commit()


async def get_recent_verification_log(limit: int = 15):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM verification_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
