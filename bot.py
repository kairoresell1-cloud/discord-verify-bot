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


class NotOwner(app_commands.CheckFailure):
    pass


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.OWNER_ID:
            raise NotOwner()
        return True
    return app_commands.check(predicate)


def user_is_owner(interaction: discord.Interaction) -> bool:
    """Controllo diretto (non decoratore) da usare dentro i bottoni delle View,
    che restano persistenti e cliccabili da chiunque veda il messaggio."""
    return interaction.user.id == config.OWNER_ID


def build_log_embed(entries: list) -> discord.Embed:
    """Costruisce l'embed del pannello di log live, a partire dagli ultimi
    N record di verifica (più recente per primo)."""
    embed = discord.Embed(
        title="📋 Log verifiche in tempo reale",
        color=discord.Color.blurple(),
    )
    if not entries:
        embed.description = "_Nessuna verifica ancora registrata._"
    else:
        lines = []
        for e in entries:
            ts = f"<t:{int(e['verified_at'])}:R>"
            lines.append(f"✅ **{e['username']}** verificato in **{e['guild_name']}** — {ts}")
        embed.description = "\n".join(lines)
    embed.set_footer(text="Si aggiorna automaticamente ad ogni nuova verifica")
    return embed


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


class SafeView(discord.ui.View):
    """View di base che intercetta qualsiasi errore nei bottoni/select e
    risponde sempre all'utente, invece di lasciare l'interazione a vuoto."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)

        message = "⚠️ Si è verificato un errore imprevisto. Controlla i log del bot."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception as e:
            print(f"[ERRORE] Impossibile notificare l'utente dell'errore: {e}")


# ---------- PANNELLO DI VERIFICA (usabile in qualsiasi server) ----------

class VerifyView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)  # persistente

    @discord.ui.button(label="✅ Verificati", style=discord.ButtonStyle.blurple, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = build_oauth_url(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(
            title="✨ Ultimo passo per la verifica",
            description=(
                "Clicca il bottone **Verifica ora** qui sotto per completare l'accesso.\n\n"
                "🔗 Il link è **personale** e legato al tuo account: non condividerlo con nessuno.\n"
                "⚡ Ci vogliono pochi secondi, poi potrai tornare direttamente su Discord."
            ),
            color=discord.Color(0x8B5CF6),  # viola
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text="Il link scade dopo l'utilizzo")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Verifica ora", url=url, style=discord.ButtonStyle.link, emoji="🔐"))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ---------- PANNELLO ADMIN (solo owner) ----------

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

    async def on_submit(self, interaction: discord.Interaction):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può farlo.", ephemeral=True)
            return

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

        # pool globale: tutti gli utenti verificati, in qualunque server abbiano premuto il bottone
        all_candidates = await database.get_all_users()
        if not all_candidates:
            await interaction.followup.send("⚠️ Nessun utente verificato trovato.", ephemeral=True)
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

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback
        traceback.print_exception(type(error), error, error.__traceback__)
        message = "⚠️ Si è verificato un errore imprevisto. Controlla i log del bot."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception as e:
            print(f"[ERRORE] Impossibile notificare l'utente dell'errore: {e}")


class ConfirmLeaveView(SafeView):
    """Conferma prima di far uscire il bot da un server, per evitare click accidentali."""

    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=60)
        self.guild = guild

    @discord.ui.button(label="✅ Sì, esci dal server", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può farlo.", ephemeral=True)
            return
        name = self.guild.name
        try:
            await self.guild.leave()
            await interaction.response.edit_message(content=f"✅ Il bot è uscito da **{name}**.", view=None)
        except Exception as e:
            await interaction.response.edit_message(content=f"⚠️ Errore durante l'uscita da **{name}**: {e}", view=None)

    @discord.ui.button(label="❌ Annulla", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può farlo.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ Operazione annullata.", view=None)


class LeaveGuildSelect(discord.ui.Select):
    def __init__(self, guilds: list[discord.Guild]):
        options = [
            discord.SelectOption(
                label=g.name[:100],
                description=f"{g.member_count or 0} membri • ID: {g.id}",
                value=str(g.id),
            )
            for g in guilds[:25]
        ]
        super().__init__(
            placeholder="Scegli un server da cui far uscire il bot...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può farlo.", ephemeral=True)
            return

        guild_id = int(self.values[0])
        guild = interaction.client.get_guild(guild_id)
        if not guild:
            await interaction.response.send_message(
                "⚠️ Non trovo più quel server (forse il bot ne è già uscito).", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"⚠️ Sei sicuro di voler far **uscire il bot** da **{guild.name}**?\n"
            f"Questa azione non si può annullare, il bot dovrà essere reinvitato manualmente.",
            view=ConfirmLeaveView(guild),
            ephemeral=True,
        )


class ServerListView(SafeView):
    def __init__(self, guilds: list[discord.Guild]):
        super().__init__(timeout=120)
        self.add_item(LeaveGuildSelect(guilds))


class AdminPanelView(SafeView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Aggiungi persone a un server", style=discord.ButtonStyle.blurple, custom_id="admin_add_people")
    async def add_people(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può usare questo pannello.", ephemeral=True)
            return
        await interaction.response.send_modal(AddPeopleModal())

    @discord.ui.button(label="📊 Statistiche ora", style=discord.ButtonStyle.grey, custom_id="admin_stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può usare questo pannello.", ephemeral=True)
            return
        count = await database.count_users()
        await interaction.response.send_message(f"👥 Totale verificati (tutti i server): **{count}**", ephemeral=True)

    @discord.ui.button(label="📌 Attiva pannello live", style=discord.ButtonStyle.grey, custom_id="admin_live_stats")
    async def live_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può usare questo pannello.", ephemeral=True)
            return
        count = await database.count_users()
        msg = await interaction.channel.send(f"👥 **Totale verificati (tutti i server):** {count}\n_(si aggiorna da solo)_")
        await database.set_stats_message(str(interaction.guild.id), str(interaction.channel.id), str(msg.id))
        await interaction.response.send_message("✅ Pannello live creato in questo canale.", ephemeral=True)

    @discord.ui.button(label="🌐 Server del bot", style=discord.ButtonStyle.grey, custom_id="admin_server_list")
    async def server_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not user_is_owner(interaction):
            await interaction.response.send_message("🚫 Solo il proprietario del bot può usare questo pannello.", ephemeral=True)
            return

        guilds = sorted(bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        if not guilds:
            await interaction.response.send_message("⚠️ Il bot non è presente in nessun server.", ephemeral=True)
            return

        lines = [f"• **{g.name}** — {g.member_count or 0} membri (ID: `{g.id}`)" for g in guilds]
        text = f"🖥️ **Server dove si trova il bot ({len(guilds)}):**\n" + "\n".join(lines[:25])
        if len(guilds) > 25:
            text += f"\n\n_(+{len(guilds) - 25} altri, non mostrati nel menu qui sotto)_"

        await interaction.response.send_message(text, view=ServerListView(guilds), ephemeral=True)


# ---------- COMANDI SLASH ----------

@bot.tree.command(name="verifica", description="Posta il pannello di verifica in questo canale")
@app_commands.describe(ruolo="Il ruolo da assegnare a chi si verifica in questo server")
@app_commands.checks.has_permissions(administrator=True)
async def verifica(interaction: discord.Interaction, ruolo: discord.Role):
    await database.set_guild_role(str(interaction.guild.id), str(ruolo.id))

    embed = discord.Embed(
        title="🔐 Verifica il tuo account",
        description=(
            "Benvenuto su **{}**! Per sbloccare l'accesso completo al server, "
            "completa la verifica in pochi secondi.\n"
        ).format(interaction.guild.name),
        color=discord.Color(0x8B5CF6),  # viola
    )
    embed.add_field(name="✅ Veloce", value="Bastano pochi click", inline=True)
    embed.add_field(name="🔒 Sicuro", value="Verifica ufficiale Discord", inline=True)
    embed.add_field(name="🎉 Ricompensa", value=f"Ottieni il ruolo {ruolo.mention}", inline=True)
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.set_footer(text="Clicca il bottone qui sotto per iniziare")
    await interaction.response.send_message(embed=embed, view=VerifyView())


@bot.tree.command(name="adminmenu", description="[Owner] Posta il pannello di amministrazione in questo canale")
@is_owner()
async def adminmenu(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛠️ Pannello Admin",
        description=(
            "**➕ Aggiungi persone a un server**: incolla un link di invito e scegli quante persone "
            "*nuove* verificate (in qualsiasi server tra i tuoi) far entrare automaticamente.\n\n"
            "**📊 Statistiche ora**: quante persone in totale hanno autorizzato il bot.\n\n"
            "**📌 Attiva pannello live**: crea un messaggio che si aggiorna da solo col conteggio.\n\n"
            "**🌐 Server del bot**: elenca i server dove sta il bot e permette di farlo uscire da remoto.\n\n"
            "⚠️ Il bot deve già essere presente nel server di destinazione.\n"
            "🔒 Questo pannello è visibile a tutti nel canale, ma solo tu puoi usarne i bottoni."
        ),
        color=discord.Color.red(),
    )
    await interaction.response.send_message(embed=embed, view=AdminPanelView())


@bot.tree.command(name="log", description="[Owner] Mostra in questo canale il log live delle verifiche")
@is_owner()
async def log_cmd(interaction: discord.Interaction):
    entries = await database.get_recent_verification_log(15)
    embed = build_log_embed(entries)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await database.set_log_channel(str(interaction.channel.id), str(msg.id))


@verifica.error
@adminmenu.error
@log_cmd.error
async def on_admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 Solo gli amministratori possono usare questo comando.", ephemeral=True)
    elif isinstance(error, NotOwner):
        await interaction.response.send_message("🚫 Solo il proprietario del bot può usare questo comando.", ephemeral=True)
    else:
        raise error


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Rete di sicurezza globale: intercetta QUALSIASI errore non gestito nei
    comandi slash (compresi quelli rilanciati con 'raise error' qui sopra),
    stampa il traceback completo nei log e risponde sempre all'utente invece
    di lasciare l'interazione a vuoto (quello che Discord mostra come
    "L'interazione è fallita")."""
    import traceback
    traceback.print_exception(type(error), error, error.__traceback__)

    message = "⚠️ Si è verificato un errore imprevisto eseguendo questo comando. Controlla i log del bot."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception as e:
        print(f"[ERRORE] Impossibile notificare l'utente dell'errore: {e}")


# ---------- AGGIORNAMENTO AUTOMATICO PANNELLI LIVE ----------

@tasks.loop(seconds=config.STATS_UPDATE_SECONDS)
async def update_live_stats():
    configs = await database.get_all_guild_configs_with_stats()
    count = await database.count_users()  # totale globale, uguale per tutti i pannelli
    for conf in configs:
        try:
            channel = bot.get_channel(int(conf["stats_channel_id"]))
            if not channel:
                continue
            message = await channel.fetch_message(int(conf["stats_message_id"]))
            await message.edit(content=f"👥 **Totale verificati (tutti i server):** {count}\n_(si aggiorna da solo)_")
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
