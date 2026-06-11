import os
from flask import Flask, render_template, redirect, request, session
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "make_up_a_random_string_here")

app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") # Needed to fetch roles/channels

MONGO_URI = os.getenv("MONGO_URI")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["discord_bot"] 

@app.route("/")
def index():
    return render_template("index.html", client_id=CLIENT_ID, redirect_uri=REDIRECT_URI)

@app.route("/login")
def login():
    return redirect(f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20guilds")

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code: return redirect("/")

    data = {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI, "scope": "identify guilds"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    response = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    tokens = response.json()

    if "access_token" not in tokens: return redirect("/")

    session["access_token"] = tokens["access_token"]
    guild_response = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"})
    guilds = guild_response.json()

    if not isinstance(guilds, list): return redirect("/")

    manageable_guilds = [g for g in guilds if (int(g.get("permissions", 0)) & 0x8) == 0x8 or (int(g.get("permissions", 0)) & 0x20) == 0x20]
    session["guilds"] = manageable_guilds
    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    if "access_token" not in session: return redirect("/")
    return render_template("dashboard.html", guilds=session.get("guilds", []))

@app.route("/dashboard/<int:guild_id>", methods=["GET", "POST"])
def guild_dashboard(guild_id):
    if "access_token" not in session: return redirect("/")

    # Handle Saving Settings
    if request.method == "POST":
        form_type = request.form.get("form_type")
        
        if form_type == "autorole":
            role_id = request.form.get("autorole_id")
            if role_id and role_id != "none":
                db["autorole_settings"].update_one({"guild_id": guild_id}, {"$set": {"role_id": int(role_id)}}, upsert=True)
            elif role_id == "none":
                db["autorole_settings"].delete_one({"guild_id": guild_id})
                
        elif form_type == "welcome":
            channel_id = request.form.get("welcome_channel_id")
            message = request.form.get("welcome_message")
            if channel_id and channel_id != "none":
                db["welcome_settings"].update_one({"guild_id": guild_id}, {"$set": {"channel_id": int(channel_id), "message": message}}, upsert=True)
            elif channel_id == "none":
                db["welcome_settings"].delete_one({"guild_id": guild_id})
                
        elif form_type == "logging":
            channel_id = request.form.get("log_channel_id")
            if channel_id and channel_id != "none":
                db["log_settings"].update_one({"guild_id": guild_id}, {"$set": {"channel_id": int(channel_id)}}, upsert=True)
            elif channel_id == "none":
                db["log_settings"].delete_one({"guild_id": guild_id})
                
        elif form_type == "automod":
            block_links = request.form.get("block_links") == "on"
            block_invites = request.form.get("block_invites") == "on"
            banned_words = [w.strip() for w in request.form.get("banned_words", "").split(",") if w.strip()]
            active_channels = request.form.getlist("automod_channels")
            active_channels = [int(c) for c in active_channels] # Convert to int
            
            db["automod_settings"].update_one(
                {"guild_id": guild_id}, 
                {"$set": {"block_links": block_links, "block_invites": block_invites, "banned_words": banned_words, "active_channels": active_channels}}, 
                upsert=True
            )
	elif form_type == "announcement":
            channel_id = request.form.get("announcement_channel_id")
            message = request.form.get("announcement_message")
            if channel_id and message:
                # Use the Bot Token to send a message to the selected channel
                requests.post(
                    f"https://discord.com/api/v10/channels/{channel_id}/messages",
                    headers={"Authorization": f"Bot {BOT_TOKEN}"},
                    json={"content": message}
                )
                
        elif form_type == "config":
            staff_role = request.form.get("STAFF_ROLE")
            mod_role = request.form.get("MOD_ROLE")
            admin_role = request.form.get("ADMIN_ROLE")
            trusted_staff_role = request.form.get("TRUSTED_STAFF_ROLE")
            log_channel_id = request.form.get("LOG_CHANNEL_ID")
            
            db["bot_config"].update_one(
                {"guild_id": guild_id},
                {"$set": {
                    "STAFF_ROLE": staff_role,
                    "MOD_ROLE": mod_role,
                    "ADMIN_ROLE": admin_role,
                    "TRUSTED_STAFF_ROLE": trusted_staff_role,
                    "LOG_CHANNEL_ID": int(log_channel_id) if log_channel_id and log_channel_id != "none" else None
                }},
                upsert=True
            )
            
        return redirect(f"/dashboard/{guild_id}")

    # GET Request: Fetch Data for Display
    bot_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    # Fetch Roles
    roles_res = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=bot_headers)
    roles = roles_res.json() if roles_res.status_code == 200 else []
    roles = [r for r in roles if r["name"] != "@everyone" and not r["managed"]] # Filter @everyone and bots
    
    # Fetch Channels
    chans_res = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=bot_headers)
    channels = chans_res.json() if chans_res.status_code == 200 else []
    text_channels = [c for c in channels if c["type"] == 0] # Type 0 is text channel

    # Fetch Settings
    settings = {
        "autorole": db["autorole_settings"].find_one({"guild_id": guild_id}),
        "welcome": db["welcome_settings"].find_one({"guild_id": guild_id}),
        "logging": db["log_settings"].find_one({"guild_id": guild_id}),
        "automod": db["automod_settings"].find_one({"guild_id": guild_id})
    }
    
    guild_name = "Unknown Server"
    for g in session.get("guilds", []):
        if int(g["id"]) == guild_id: guild_name = g["name"]; break

    return render_template("settings.html", guild_id=guild_id, guild_name=guild_name, roles=roles, channels=text_channels, settings=settings)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))