import os
from flask import Flask, render_template, redirect, request, session
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "make_up_a_random_string_here")

# Force Flask to use secure cookies for HTTPS (Render)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Discord OAuth2 Config
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Connect to MongoDB
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
    if not code:
        return "Error: No code provided by Discord.", 400

    # LOUD DEBUG: Print the variables we are using
    print(f"--- DEBUGGING LOGIN ---")
    print(f"CLIENT_ID: {CLIENT_ID}")
    print(f"CLIENT_SECRET is loaded: {'Yes' if CLIENT_SECRET else 'NO! MISSING!'}")
    print(f"REDIRECT_URI: {REDIRECT_URI}")
    print(f"CODE: {code}")
    print(f"-----------------------")

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "identify guilds"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    response = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    tokens = response.json()

    # LOUD DEBUG: Print Discord's exact response
    print(f"DISCORD RESPONSE: {tokens}")

    if "access_token" not in tokens:
        error_desc = tokens.get("error_description", tokens.get("error", "Unknown error"))
        return f"<h1>Login Failed</h1><p>Discord said: <b>{error_desc}</b></p><p>Please take a screenshot of this and check your Render Logs!</p>", 400

    session["access_token"] = tokens["access_token"]

    guild_response = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"})
    guilds = guild_response.json()

    if not isinstance(guilds, list):
        return "Failed to fetch user guilds from Discord.", 400

    manageable_guilds = [g for g in guilds if (int(g.get("permissions", 0)) & 0x8) == 0x8 or (int(g.get("permissions", 0)) & 0x20) == 0x20]
    session["guilds"] = manageable_guilds
    return redirect("/dashboard")
@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect("/")
    return render_template("dashboard.html", guilds=session.get("guilds", []))

@app.route("/dashboard/<int:guild_id>", methods=["GET", "POST"])
def guild_dashboard(guild_id):
    if "access_token" not in session:
        return redirect("/")

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
            active_channels = [int(c) for c in active_channels]
            
            db["automod_settings"].update_one(
                {"guild_id": guild_id}, 
                {"$set": {"block_links": block_links, "block_invites": block_invites, "banned_words": banned_words, "active_channels": active_channels}}, 
                upsert=True
            )
            
        elif form_type == "announcement":
            channel_id = request.form.get("announcement_channel_id")
            message = request.form.get("announcement_message")
            if channel_id and message:
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

        elif form_type == "create_app":
            app_id = request.form.get("app_id").lower().replace(" ", "-")
            app_name = request.form.get("app_name")
            
            # NEW: Read from a single text box, split by new lines, and remove empty lines
            questions_raw = request.form.get("questions_text", "")
            questions = [q.strip() for q in questions_raw.split("\n") if q.strip()]
            
            is_open = request.form.get("is_open") == "on"
            submitted_channel_id = request.form.get("submitted_channel_id")
            accepted_channel_id = request.form.get("accepted_channel_id")
            denied_channel_id = request.form.get("denied_channel_id")
            
            if app_id and app_name and questions:
                db["applications_config"].update_one(
                    {"guild_id": guild_id, "app_id": app_id},
                    {"$set": {
                        "app_name": app_name,
                        "questions": questions,
                        "is_open": is_open,
                        "submitted_channel_id": int(submitted_channel_id) if submitted_channel_id and submitted_channel_id != "none" else None,
                        "accepted_channel_id": int(accepted_channel_id) if accepted_channel_id and accepted_channel_id != "none" else None,
                        "denied_channel_id": int(denied_channel_id) if denied_channel_id and denied_channel_id != "none" else None
                    }},
                    upsert=True
                )

        elif form_type == "send_app_panel":
            app_id = request.form.get("panel_app_id")
            panel_channel_id = request.form.get("panel_channel_id")
            
            app_config = db["applications_config"].find_one({"guild_id": guild_id, "app_id": app_id})
            if app_config and panel_channel_id:
                component = {
                    "type": 1, "components": [{
                        "type": 2, 
                        "label": f"Apply for {app_config['app_name']}", 
                        "style": 1, 
                        "custom_id": f"apply_{app_id}",
                        "emoji": {"name": "📝"}
                    }]
                }
                
                # Beautiful Embed payload
                embed_payload = {
                    "title": f"📝 {app_config['app_name']}",
                    "description": "Click the button below to start your application. You will receive a DM from the bot to fill out the questions.",
                    "color": 0x5865F2, # Blurple color
                    "footer": {"text": f"App ID: {app_id}"}
                }
                
                requests.post(
                    f"https://discord.com/api/v10/channels/{panel_channel_id}/messages",
                    headers={"Authorization": f"Bot {BOT_TOKEN}"},
                    json={
                        "embeds": [embed_payload], 
                        "components": [component]
                    }
                )

        elif form_type == "delete_app":
            app_id = request.form.get("delete_app_id")
            if app_id:
                db["applications_config"].delete_one({"guild_id": guild_id, "app_id": app_id})
            
        return redirect(f"/dashboard/{guild_id}")

    # GET Request: Fetch Data for Display
    bot_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    # Fetch Roles
    roles_res = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/roles", headers=bot_headers)
    roles = roles_res.json() if roles_res.status_code == 200 else []
    roles = [r for r in roles if r["name"] != "@everyone" and not r["managed"]]
    
    # Fetch Channels
    chans_res = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=bot_headers)
    channels = chans_res.json() if chans_res.status_code == 200 else []
    text_channels = [c for c in channels if c["type"] == 0]

    # Fetch Settings
    settings = {
        "autorole": db["autorole_settings"].find_one({"guild_id": guild_id}),
        "welcome": db["welcome_settings"].find_one({"guild_id": guild_id}),
        "logging": db["log_settings"].find_one({"guild_id": guild_id}),
        "automod": db["automod_settings"].find_one({"guild_id": guild_id}),
        "config": db["bot_config"].find_one({"guild_id": guild_id}),
        "applications": list(db["applications_config"].find({"guild_id": guild_id}))
    }
    
    guild_name = "Unknown Server"
    for g in session.get("guilds", []):
        if int(g["id"]) == guild_id:
            guild_name = g["name"]
            break

    return render_template("settings.html", guild_id=guild_id, guild_name=guild_name, roles=roles, channels=text_channels, settings=settings)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))