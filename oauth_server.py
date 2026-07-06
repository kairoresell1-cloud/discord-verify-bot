from aiohttp import web
import config
import database
import oauth

routes = web.RouteTableDef()


def create_app(bot):
    app = web.Application()
    app["bot"] = bot

    @routes.get("/")
    async def index(request):
        return web.Response(text="Bot online.")

    @routes.get("/callback")
    async def callback(request):
        code = request.query.get("code")
        state = request.query.get("state")  # formato "guild_id:user_id"
        if not code or not state or ":" not in state:
            return web.Response(text="Richiesta non valida.", status=400)

        guild_id, expected_user_id = state.split(":", 1)

        try:
            token_data = await oauth.exchange_code(code)
        except Exception:
            return web.Response(text="Errore durante la verifica. Riprova.", status=400)

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = token_data["expires_in"]

        identity = await oauth.get_user_identity(access_token)
        user_id = identity["id"]
        username = identity.get("username", "sconosciuto")

        if user_id != expected_user_id:
            return web.Response(text="Verifica non valida (state mismatch).", status=400)

        await database.save_user(guild_id, user_id, username, access_token, refresh_token, expires_in)

        # assegna il ruolo verificato nel server dove è stata avviata la verifica
        bot = request.app["bot"]
        guild = bot.get_guild(int(guild_id))
        guild_conf = await database.get_guild_config(guild_id)
        if guild and guild_conf and guild_conf.get("verified_role_id"):
            member = guild.get_member(int(user_id))
            role = guild.get_role(int(guild_conf["verified_role_id"]))
            if member and role:
                try:
                    await member.add_roles(role, reason="Verifica completata")
                except Exception:
                    pass

        return web.Response(
            text="✅ Verifica completata! Puoi tornare su Discord.",
            content_type="text/html",
        )

    app.add_routes(routes)
    return app


async def run_web_server(bot):
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
