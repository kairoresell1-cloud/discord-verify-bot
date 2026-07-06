import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")  # es: https://tuoprogetto.up.railway.app/callback
PORT = int(os.getenv("PORT", "8080"))

# Scope OAuth2 richiesti: identify per sapere chi è, guilds.join per poterlo
# aggiungere in automatico ad altri server in futuro
OAUTH_SCOPES = "identify guilds.join"

DISCORD_API = "https://discord.com/api/v10"

STATS_UPDATE_SECONDS = 30

OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # il TUO id Discord (tasto destro sul tuo nome -> Copia ID)
