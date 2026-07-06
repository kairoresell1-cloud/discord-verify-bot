import aiohttp
import config


async def exchange_code(code: str) -> dict:
    """Scambia il 'code' OAuth2 con access_token + refresh_token"""
    data = {
        "client_id": config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{config.DISCORD_API}/oauth2/token", data=data, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    data = {
        "client_id": config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{config.DISCORD_API}/oauth2/token", data=data, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()


async def get_user_identity(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{config.DISCORD_API}/users/@me", headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()


async def resolve_invite(invite_code: str) -> dict:
    """Risolve un invito (codice o link completo) nel guild_id corrispondente"""
    code = invite_code.strip().split("/")[-1]
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{config.DISCORD_API}/invites/{code}") as resp:
            if resp.status != 200:
                raise ValueError("Invito non valido o scaduto")
            return await resp.json()


async def add_user_to_guild(bot_token: str, guild_id: str, user_id: str, user_access_token: str) -> tuple[bool, str]:
    """Aggiunge un utente a un server usando il suo token OAuth2 (scope guilds.join)"""
    url = f"{config.DISCORD_API}/guilds/{guild_id}/members/{user_id}"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }
    payload = {"access_token": user_access_token}
    async with aiohttp.ClientSession() as session:
        async with session.put(url, json=payload, headers=headers) as resp:
            if resp.status in (201, 204):
                return True, "ok"
            body = await resp.text()
            return False, f"{resp.status}: {body}"
