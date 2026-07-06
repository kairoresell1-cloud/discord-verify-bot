import discord
from discord import app_commands
from discord.ext import commands, tasks
import urllib.parse
import asyncio
import random

import config
import database
import oauth

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


class NotWhitelisted(app_commands.CheckFailure):
    pass


class NotOwner(app_commands.CheckFailure):
    pass


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.OWNER_ID:
            raise NotOwner()
        return True
    return app_commands.check(predicate)


def is_whitelisted():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not await database.is_guild_allowed(str(interaction.guild.id)):
            raise NotWhitelisted()
        return True
    return app_commands.check(predicate)


def build_oauth_url(guild_id: int, user_id: int) -> str:
    params = {
        "client_id": config.CLIENT_ID,
        "redirect_uri": config.REDIRECT_URI,
        "response_type": "code",
        "scope": config.OAUTH_SCOPES,
        "state": f"{guild_id}:{user_id}",
        "prompt": "consent",
    }
    return f"https://discord.com/oauth2/authorize?{urllib.parse.urlencode(params)}"


# ---------- PANNELLO DI VERIFICA ----------

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistente

    @discord.ui.button(label="✅ Verificati", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await database.is_guild_allowed(str(interaction.guild.id)):
            await interaction.response.send_message("🚫 La verifica non è più attiva in questo server.", ephemeral=True)
            return
        url = build_oauth_url(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(
            title="Verifica il tuo account",
            description="Clicca il link qui sotto per completare la verifica. Il link è personale, non condividerlo.",
            color=discord.Color.blurple(),
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Verifica ora", url=url, style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ---------- PANNELLO ADMIN ----------

class AddPeopleModal(discord.ui.Modal, title="Aggiungi persone a un server"):
    invite_link = discord.ui.TextInput(
        label="Link di invito del server di destinazione",
        placeholder="discord.gg/xxxxxxx",
        required=True,
    )
    amount = discord.ui.TextInput(
        label="Quante persone NUOVE vuoi far entrare?",
        placeholder="es. 10",
        required=True,
    )

    def __init__(self, source_guild_id: int):
        super().__init__()
        self.source_guild_id = source_guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            n = int(self.amount.value.strip())
            if n <= 0:
                raise ValueError
        except ValueError:
            await interaction.followup.send("⚠️ Numero non valido.", ephemeral=True)
            return

        try:
            invite_info = await oauth.resolve_invite(self.invite_link.value)
            dest_guild_id = invite_info["guild"]["id"]
            guild_name = invite_info["guild"]["name"]
        except Exception:
            await interaction.followup.send("⚠️ Link di invito non valido o scaduto.", ephemeral=True)
            return

        all_candidates = await database.get_all_users(str(self.source_guild_id))
        if not all_candidates:
            await interaction.followup.send("⚠️ Nessun utente verificato trovato in questo server.", ephemeral=True)
            return

        # escludi chi è già presente nel server di destinazione
        dest_guild = bot.get_guild(int(dest_guild_id))
        already_there_ids = set()
        if dest_guild:
            already_there_ids = {str(m.id) for m in dest_guild.members}

        filtered = [u for u in all_candidates if u["user_id"] not in already_there_ids]
        skipped_already_there = len(all_candidates) - len(filtered)

        if not filtered:
            await interaction.followup.send(
                f"⚠️ Tutti gli utenti verificati sono già presenti in **{guild_name}**.", ephemeral=True
            )
            return

        candidates = random.sample(filtered, min(n, len(filtered)))

        added, failed = 0, 0
        errors = []

        for user in candidates:
            access_token = user["access_token"]

            success, msg = await oauth.add_user_to_guild(
                config.DISCORD_TOKEN, dest_guild_id, user["user_id"], access_token
            )

            if not success and "401" in msg:
                try:
                    refreshed = await oauth.refresh_access_token(user["refresh_token"])
                    await database.update_tokens(
                        str(self.source_guild_id),
                        user["user_id"],
                        refreshed["access_token"],
                        refreshed["refresh_token"],
                        refreshed["expires_in"],
                    )
                    success, msg = await oauth.add_user_to_guild(
                        config.DISCORD_TOKEN, dest_guild_id, user["user_id"], refreshed["access_token"]
                    )
                except Exception:
                    pass

            if success:
                added += 1
            else:
                failed += 1
                errors.append(f"{user['username']}: {msg}")

            await asyncio.sleep(0.5)  # rispetta i rate limit di Discord

        result = f"✅ Aggiunti **{added}** nuovi utenti a **{guild_name}**."
        if skipped_already_there:
            result += f"\nℹ️ Esclusi perché già presenti: {skipped_already_there}"
        if failed:
            result += f"\n❌ Falliti: {failed}"
        if errors:
            result += "\n\nDettagli errori (primi 5):\n" + "\n".join(errors[:5])

        await interaction.followup.send(result, ephemeral=True)


class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Aggiungi persone a un server", style=discord.ButtonStyle.blurple, custom_id="admin_add_people")
    async def add_people(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await database.is_guild_allowed(str(interaction.guild.id)):
            await interaction.response.send_message("🚫 Questo server non è più autorizzato.", ephemeral=True)
            return
        await interaction.response.send_modal(AddPeopleModal(interaction.guild.id))

    @discord.ui.button(label="📊 Statistiche ora", style=discord.ButtonStyle.grey, custom_id="admin_stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await database.is_guild_allowed(str(interaction.guild.id)):
            await interaction.response.send_message("🚫 Questo server non è più autorizzato.", ephemeral=True)
            return
        count = await database.count_users(str(interaction.guild.id))
        await interaction.response.send_message(f"👥 Autorizzati in questo server: **{count}**", ephemeral=True)

    @discord.ui.button(label="📌 Attiva pannello live", style=discord.ButtonStyle.grey, custom_id="admin_live_stats")
    async def live_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await database.is_guild_allowed(str(interaction.guild.id)):
            await interaction.response.send_message("🚫 Questo server non è più autorizzato.", ephemeral=True)
            return
        count = await database.count_users(str(interaction.guild.id))
        msg = await interaction.channel.send(f"👥 **Autorizzati in questo server:** {count}\n_(si aggiorna da solo)_")
        await database.set_stats_message(str(interaction.guild.id), str(interaction.channel.id), str(msg.id))
        await interaction.response.send_message("✅ Pannello live creato in questo canale.", ephemeral=True)


# ---------- COMANDI SLASH (solo admin) ----------

@bot.tree.command(name="verifica", description="Posta il pannello di verifica in questo canale")
@app_commands.describe(ruolo="Il ruolo da assegnare a chi si verifica in questo server")
@app_commands.checks.has_permissions(administrator=True)
@is_whitelisted()
async def verifica(interaction: discord.Interaction, ruolo: discord.Role):
    await database.set_guild_role(str(interaction.guild.id), str(ruolo.id))

    embed = discord.Embed(
        title="Benvenuto!",
        description="Clicca il bottone qui sotto per verificarti e ottenere l'accesso al server.",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed, view=VerifyView())


@bot.tree.command(name="adminmenu", description="Posta il pannello di amministrazione in questo canale")
@app_commands.checks.has_permissions(administrator=True)
@is_whitelisted()
async def adminmenu(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛠️ Pannello Admin",
        description=(
            "**➕ Aggiungi persone a un server**: incolla un link di invito e scegli quante persone "
            "*nuove* verificate far entrare automaticamente (chi è già in quel server viene escluso).\n\n"
            "**📊 Statistiche ora**: quante persone di questo server hanno autorizzato il bot.\n\n"
            "**📌 Attiva pannello live**: crea un messaggio che si aggiorna da solo col conteggio.\n\n"
            "⚠️ Il bot deve già essere presente nel server di destinazione."
        ),
        color=discord.Color.red(),
    )
    await interaction.response.send_message(embed=embed, view=AdminPanelView())


@bot.tree.command(name="autorizza", description="[Owner] Autorizza questo server a usare /verifica e /adminmenu")
@is_owner()
async def autorizza(interaction: discord.Interaction):
    await database.add_allowed_guild(str(interaction.guild.id), interaction.guild.name)
    await interaction.response.send_message(f"✅ Server **{interaction.guild.name}** autorizzato.", ephemeral=True)


@bot.tree.command(name="revoca", description="[Owner] Revoca l'autorizzazione a questo server")
@is_owner()
async def revoca(interaction: discord.Interaction):
    await database.remove_allowed_guild(str(interaction.guild.id))
    await interaction.response.send_message(f"🚫 Server **{interaction.guild.name}** revocato.", ephemeral=True)


@bot.tree.command(name="elenco_autorizzati", description="[Owner] Mostra tutti i server autorizzati")
@is_owner()
async def elenco_autorizzati(interaction: discord.Interaction):
    guilds = await database.list_allowed_guilds()
    if not guilds:
        await interaction.response.send_message("Nessun server autorizzato ancora.", ephemeral=True)
        return
    lines = [f"• {g['guild_name']} (`{g['guild_id']}`)" for g in guilds]
    await interaction.response.send_message("**Server autorizzati:**\n" + "\n".join(lines), ephemeral=True)


@verifica.error
@adminmenu.error
@autorizza.error
@revoca.error
@elenco_autorizzati.error
async def on_admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 Solo gli amministratori possono usare questo comando.", ephemeral=True)
    elif isinstance(error, NotWhitelisted):
        await interaction.response.send_message(
            "🚫 Questo server non è autorizzato a usare questa funzione. Chiedi al proprietario del bot di autorizzarlo con /autorizza.",
            ephemeral=True,
        )
    elif isinstance(error, NotOwner):
        await interaction.response.send_message("🚫 Solo il proprietario del bot può usare questo comando.", ephemeral=True)
    else:
        raise error


# ---------- AGGIORNAMENTO AUTOMATICO PANNELLI LIVE ----------

@tasks.loop(seconds=config.STATS_UPDATE_SECONDS)
async def update_live_stats():
    configs = await database.get_all_guild_configs_with_stats()
    for conf in configs:
        try:
            channel = bot.get_channel(int(conf["stats_channel_id"]))
            if not channel:
                continue
            message = await channel.fetch_message(int(conf["stats_message_id"]))
            count = await database.count_users(conf["guild_id"])
            await message.edit(content=f"👥 **Autorizzati in questo server:** {count}\n_(si aggiorna da solo)_")
        except Exception:
            continue


@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    bot.add_view(AdminPanelView())
    await bot.tree.sync()
    if not update_live_stats.is_running():
        update_live_stats.start()
    print(f"Bot connesso come {bot.user}")
