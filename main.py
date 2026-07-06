import asyncio
import config
import database
from bot import bot
from oauth_server import run_web_server


async def main():
    await database.init_db()
    await run_web_server(bot)
    await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
