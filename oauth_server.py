from aiohttp import web
import discord
import config
import database
import oauth

routes = web.RouteTableDef()


def get_avatar_url(identity: dict) -> str:
    """Costruisce l'URL dell'avatar Discord dell'utente, con fallback
    all'avatar di default se non ne ha impostato uno."""
    user_id = identity["id"]
    avatar_hash = identity.get("avatar")
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=256"
    discriminator = identity.get("discriminator", "0")
    if discriminator and discriminator != "0":
        index = int(discriminator) % 5
    else:
        index = (int(user_id) >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def render_page(success: bool, title: str, message: str, avatar_url: str | None = None) -> str:
    """Genera la pagina HTML del callback OAuth2.

    Design: sfondo scuro statico con un unico bagliore, card pulita con bordo
    sottile, badge-avatar in stile "stato" agganciato all'icona (richiama il
    pattern degli status indicator di Discord), un solo momento animato in
    apertura e un unico burst di coriandoli discreto in caso di successo.
    """

    if success:
        accent = "#57F287"
        glow = "88, 242, 130"
        icon_path = 'M4 12.5 9.5 18 20 6'
        icon_len = 26
        run_confetti = "spawnConfetti();"
    else:
        accent = "#ED4245"
        glow = "237, 66, 69"
        icon_path = 'M6 6 18 18 M18 6 6 18'
        icon_len = 24
        run_confetti = ""

    avatar_badge = ""
    if avatar_url:
        avatar_badge = f"""
          <div class="avatar-badge">
            <img src="{avatar_url}" alt="" referrerpolicy="no-referrer">
          </div>"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; }}

  body {{
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'gg sans', Roboto, Helvetica, Arial, sans-serif;
    color: #F5F6FA;
    background:
      radial-gradient(circle at 25% 15%, rgba({glow}, 0.16), transparent 42%),
      radial-gradient(circle at 80% 85%, rgba(88, 101, 242, 0.10), transparent 45%),
      #0A0B10;
    position: relative;
    overflow: hidden;
  }}

  /* grana sottile e statica, per dare profondità senza muoversi */
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    opacity: 0.035;
    pointer-events: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    mix-blend-mode: overlay;
  }}

  canvas#fx {{
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 2;
  }}

  .card {{
    position: relative;
    z-index: 1;
    width: 100%;
    max-width: 400px;
    background: #101119;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px;
    padding: 44px 36px 36px;
    text-align: center;
    box-shadow: 0 24px 60px rgba(0,0,0,0.5);
    opacity: 0;
    animation: cardIn 0.5s 0.05s cubic-bezier(.2,.8,.3,1) forwards;
  }}
  @keyframes cardIn {{
    from {{ opacity: 0; transform: translateY(10px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}

  .icon-stage {{
    position: relative;
    width: 84px;
    height: 84px;
    margin: 0 auto 28px;
  }}

  .ring-bloom {{
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 1.5px solid {accent};
    opacity: 0;
    animation: bloom 0.9s 0.35s cubic-bezier(.2,.7,.3,1) forwards;
  }}
  @keyframes bloom {{
    0%   {{ transform: scale(0.8); opacity: 0.6; }}
    100% {{ transform: scale(1.55); opacity: 0; }}
  }}

  .icon-circle {{
    width: 84px;
    height: 84px;
    border-radius: 50%;
    background: {accent}1a;
    border: 1.5px solid {accent}55;
    display: flex;
    align-items: center;
    justify-content: center;
    transform: scale(0.85);
    opacity: 0;
    animation: iconIn 0.4s 0.1s cubic-bezier(.3,.9,.4,1.1) forwards;
  }}
  @keyframes iconIn {{
    to {{ transform: scale(1); opacity: 1; }}
  }}

  .icon-circle svg {{ width: 34px; height: 34px; overflow: visible; }}
  .icon-circle path {{
    fill: none;
    stroke: {accent};
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-dasharray: {icon_len};
    stroke-dashoffset: {icon_len};
    animation: draw 0.4s ease-out 0.4s forwards;
  }}
  @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}

  .avatar-badge {{
    position: absolute;
    right: -4px;
    bottom: -4px;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    padding: 3px;
    background: #101119;
    opacity: 0;
    transform: scale(0.6);
    animation: badgeIn 0.35s 0.55s cubic-bezier(.3,.9,.4,1.2) forwards;
  }}
  @keyframes badgeIn {{
    to {{ opacity: 1; transform: scale(1); }}
  }}
  .avatar-badge img {{
    width: 100%;
    height: 100%;
    border-radius: 50%;
    object-fit: cover;
    display: block;
  }}

  h1 {{
    margin: 0 0 10px;
    font-size: 22px;
    font-weight: 650;
    letter-spacing: -0.2px;
    color: #fff;
    opacity: 0;
    animation: textIn 0.4s 0.5s ease-out forwards;
  }}

  p.message {{
    margin: 0 0 30px;
    font-size: 14.5px;
    line-height: 1.55;
    color: #9A9CAE;
    opacity: 0;
    animation: textIn 0.4s 0.58s ease-out forwards;
  }}
  p.message b {{ color: #D6D8E4; font-weight: 600; }}

  @keyframes textIn {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}

  .btn {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    text-decoration: none;
    color: #fff;
    font-weight: 600;
    font-size: 14.5px;
    padding: 12px 24px;
    border-radius: 10px;
    background: #5865F2;
    transition: background 0.15s ease, transform 0.15s ease;
    opacity: 0;
    animation: textIn 0.4s 0.64s ease-out forwards;
  }}
  .btn:hover {{ background: #4954d4; transform: translateY(-1px); }}
  .btn:active {{ transform: translateY(0); }}

  .footer-note {{
    margin-top: 20px;
    font-size: 12px;
    color: #5C5E6E;
    opacity: 0;
    animation: textIn 0.4s 0.7s ease-out forwards;
  }}

  @media (prefers-reduced-motion: reduce) {{
    .card, .icon-circle, .icon-circle path, .ring-bloom, .avatar-badge, h1, p.message, .btn, .footer-note {{
      animation: none !important;
      opacity: 1 !important;
      transform: none !important;
      stroke-dashoffset: 0 !important;
    }}
  }}
</style>
</head>
<body>
  <canvas id="fx"></canvas>

  <div class="card">
    <div class="icon-stage">
      <div class="ring-bloom"></div>
      <div class="icon-circle">
        <svg viewBox="0 0 24 24"><path d="{icon_path}"/></svg>
      </div>{avatar_badge}
    </div>
    <h1>{title}</h1>
    <p class="message">{message}</p>
    <a class="btn" href="discord://">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
        <path d="M20.317 4.369a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.045-.32 13.58.099 18.058a.082.082 0 0 0 .031.056 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.099.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.076.076 0 0 0-.04.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.029 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.055c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.331c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.211 0 2.176 1.094 2.157 2.418 0 1.334-.955 2.419-2.157 2.419zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.211 0 2.176 1.094 2.157 2.418 0 1.334-.946 2.419-2.157 2.419z"/>
      </svg>
      Apri Discord
    </a>
    <div class="footer-note">Puoi chiudere questa pagina in qualsiasi momento.</div>
  </div>

<script>
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canvas = document.getElementById('fx');
  const ctx = canvas.getContext('2d');
  let w = canvas.width = window.innerWidth;
  let h = canvas.height = window.innerHeight;
  window.addEventListener('resize', () => {{
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }});

  const colors = ['#57F287', '#5865F2', '#FEE75C', '#ffffff'];
  let pieces = [];

  function spawnConfetti() {{
    if (reduceMotion) return;
    const originX = w / 2;
    for (let i = 0; i < 54; i++) {{
      pieces.push({{
        x: originX + (Math.random() - 0.5) * 60,
        y: h * 0.28,
        size: 4 + Math.random() * 5,
        color: colors[Math.floor(Math.random() * colors.length)],
        speedY: 1.5 + Math.random() * 2.2,
        speedX: (Math.random() - 0.5) * 3,
        rot: Math.random() * 360,
        rotSpeed: (Math.random() - 0.5) * 6,
        life: 0,
        shape: Math.random() > 0.5 ? 'rect' : 'circle',
      }});
    }}
  }}

  function loop() {{
    ctx.clearRect(0, 0, w, h);
    pieces.forEach(p => {{
      p.x += p.speedX;
      p.y += p.speedY;
      p.speedY += 0.02;
      p.rot += p.rotSpeed;
      p.life++;
      ctx.save();
      ctx.globalAlpha = Math.max(0, 1 - p.life / 150);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot * Math.PI / 180);
      ctx.fillStyle = p.color;
      if (p.shape === 'rect') {{
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      }} else {{
        ctx.beginPath();
        ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
        ctx.fill();
      }}
      ctx.restore();
    }});
    pieces = pieces.filter(p => p.life < 150);
    requestAnimationFrame(loop);
  }}
  requestAnimationFrame(loop);

  {run_confetti}
</script>
</body>
</html>"""


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
            return web.Response(
                text=render_page(False, "Richiesta non valida", "Il link usato non è corretto o è incompleto. Riprova cliccando di nuovo il bottone di verifica su Discord."),
                content_type="text/html",
                status=400,
            )

        guild_id, expected_user_id = state.split(":", 1)

        try:
            token_data = await oauth.exchange_code(code)
        except Exception:
            return web.Response(
                text=render_page(False, "Verifica non riuscita", "Qualcosa è andato storto durante lo scambio con Discord. Torna sul server e riprova la verifica."),
                content_type="text/html",
                status=400,
            )

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = token_data["expires_in"]

        identity = await oauth.get_user_identity(access_token)
        user_id = identity["id"]
        username = identity.get("username", "sconosciuto")

        if user_id != expected_user_id:
            return web.Response(
                text=render_page(False, "Verifica non valida", "Questo link di verifica non corrisponde al tuo account. Richiedi un nuovo link personale su Discord."),
                content_type="text/html",
                status=400,
            )

        await database.save_user(user_id, username, access_token, refresh_token, expires_in, guild_id=guild_id)

        # assegna il ruolo verificato nel server dove è stata avviata la verifica
        bot = request.app["bot"]
        guild = bot.get_guild(int(guild_id))
        guild_conf = await database.get_guild_config(guild_id)
        if guild and guild_conf and guild_conf.get("verified_role_id"):
            role = guild.get_role(int(guild_conf["verified_role_id"]))
            try:
                member = await guild.fetch_member(int(user_id))
            except Exception as e:
                print(f"[VERIFICA] Impossibile trovare il membro {user_id} nel server {guild_id}: {e}")
                member = None
            if member and role:
                try:
                    await member.add_roles(role, reason="Verifica completata")
                    print(f"[VERIFICA] Ruolo assegnato a {username} ({user_id}) nel server {guild_id}")
                except discord.Forbidden:
                    print(f"[VERIFICA] ERRORE: il bot non ha i permessi per assegnare il ruolo in {guild_id} "
                          f"(controlla la gerarchia ruoli e il permesso 'Gestisci Ruoli')")
                except Exception as e:
                    print(f"[VERIFICA] ERRORE assegnando ruolo: {e}")
            elif not role:
                print(f"[VERIFICA] ERRORE: ruolo {guild_conf['verified_role_id']} non trovato nel server {guild_id}")
        else:
            print(f"[VERIFICA] ERRORE: guild {guild_id} non trovata o senza ruolo configurato")

        avatar_url = get_avatar_url(identity)

        return web.Response(
            text=render_page(
                True,
                "Verifica completata",
                f"Benvenuto <b>{username}</b>. Puoi tornare su Discord.",
                avatar_url=avatar_url,
            ),
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
