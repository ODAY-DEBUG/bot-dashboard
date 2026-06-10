import os
from flask import Flask, render_template, redirect, request, session
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "make_up_a_random_string_here")

# --- FIX: Force Flask to use secure cookies for HTTPS (Render) ---
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# -----------------------------------------------------------------

# Discord OAuth2 Config
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

# --- Connect to MongoDB ---
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
        return "No code provided by Discord.", 400

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

    # --- FIX: Show the actual error if Discord rejects the login ---
    if "access_token" not in tokens:
        error_desc = tokens.get("error_description", tokens.get("error", "Unknown error"))
        return f"<h1>Login Failed</h1><p>Discord said: {error_desc}</p><p>Check if your REDIRECT_URI in Render exactly matches the Discord Developer Portal!</p>", 400
    # -----------------------------------------------------------------

    session["access_token"] = tokens["access_token"]

    # Get user's servers
    guild_response = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"})
    guilds = guild_response.json()

    # Check if guilds is a list (success) or dict (error)
    if not isinstance(guilds, list):
        return "Failed to fetch user guilds.", 400

    # Filter to servers where the user is Admin or has Manage Server
    manageable_guilds = []
    for guild in guilds:
        permissions = int(guild.get("permissions", 0))
        if (permissions & 0x8) == 0x8 or (permissions & 0x20) == 0x20:
            manageable_guilds.append(guild)

    session["guilds"] = manageable_guilds
    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect("/")
    
    guilds = session.get("guilds", [])
    return render_template("dashboard.html", guilds=guilds)

@app.route("/dashboard/<int:guild_id>", methods=["GET", "POST"])
def guild_dashboard(guild_id):
    if "access_token" not in session:
        return redirect("/")

    if request.method == "POST":
        autorole_id = request.form.get("autorole_id")
        if autorole_id:
            autorole_id = autorole_id.strip("<@&").strip(">") 
            
            db["autorole_settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {"role_id": int(autorole_id)}},
                upsert=True
            )
        return redirect(f"/dashboard/{guild_id}")

    # GET request: Show the current settings
    settings = {}
    settings["autorole"] = db["autorole_settings"].find_one({"guild_id": guild_id})
    
    guild_name = "Unknown Server"
    for g in session.get("guilds", []):
        if int(g["id"]) == guild_id:
            guild_name = g["name"]
            break

    return render_template("settings.html", guild_id=guild_id, guild_name=guild_name, settings=settings)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))