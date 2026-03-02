from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

app = FastAPI(title="Batingun Master Tool API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE = {"players": [], "last_updated": None, "status": "empty"}

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
HEADERS = {
    "x-rapidapi-host": "v3.football.api-sports.io",
    "x-rapidapi-key": RAPIDAPI_KEY,
}

LEAGUES = {
    "serie_a":    {"id": 135, "season": 2024, "name": "Serie A",    "flag": "🇮🇹"},
    "la_liga":    {"id": 140, "season": 2024, "name": "LaLiga",     "flag": "🇪🇸"},
    "bundesliga": {"id": 78,  "season": 2024, "name": "Bundesliga", "flag": "🇩🇪"},
}

def map_status(type_str: str, reason_str: str) -> str:
    combined = (type_str + " " + reason_str).lower()
    if any(k in combined for k in ["suspended", "yellow cards", "yellow card", "red card", "suspension", "ban"]):
        return "suspended"
    if any(k in combined for k in ["doubtful", "questionable", "50/50"]):
        return "doubtful"
    return "injured"

async def fetch_league(league_key: str, league_info: dict) -> list:
    url = "https://v3.football.api-sports.io/injuries"
    params = {"league": league_info["id"], "season": league_info["season"]}
    today = date.today()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()

    players = []
    seen = set()

    for item in data.get("response", []):
        player = item.get("player", {})
        team   = item.get("team", {})
        name      = player.get("name", "")
        team_name = team.get("name", "")
        type_str  = player.get("type", "")
        reason    = player.get("reason", "")

        # Deduplicate
        key = f"{name}_{team_name}"
        if key in seen:
            continue
        seen.add(key)

        # Return date
        ret_raw = item.get("fixture", {}).get("date", "") if item.get("fixture") else ""
        ret_date = ret_raw[:10] if ret_raw else ""

        # Eski tarihleri filtrele: dönüş tarihi geçmişte ise gösterme
        if ret_date:
            try:
                rd = date.fromisoformat(ret_date)
                if rd < today:
                    continue
            except:
                pass

        status = map_status(type_str, reason)

        players.append({
            "id":          f"{league_key}_{player.get('id')}",
            "name":        name,
            "team":        team_name,
            "league":      league_key,
            "league_name": league_info["name"],
            "league_flag": league_info["flag"],
            "status":      status,
            "desc":        reason or type_str or "Bilinmiyor",
            "ret":         ret_date,
        })

    return players

async def fetch_all() -> dict:
    all_players = []
    errors = []

    for key, info in LEAGUES.items():
        try:
            players = await fetch_league(key, info)
            all_players.extend(players)
            print(f"✅ {info['name']}: {len(players)} oyuncu")
        except Exception as e:
            errors.append(f"{info['name']}: {str(e)}")
            print(f"❌ {info['name']}: {e}")

    if len(all_players) < 3:
        return {"status": "error", "message": "Yeterli veri gelmedi", "errors": errors}

    CACHE["players"]      = all_players
    CACHE["last_updated"] = datetime.now().strftime("%d %b %Y · %H:%M")
    CACHE["status"]       = "ok"

    return {
        "status":       "success",
        "updated":      len(all_players),
        "errors":       errors,
        "last_updated": CACHE["last_updated"],
    }

@app.get("/api/players")
def get_players(league: str = None, team: str = None, status: str = None, q: str = None):
    players = CACHE["players"]
    if league and league != "all":
        players = [p for p in players if p["league"] == league]
    if team and team != "Tüm Takımlar":
        players = [p for p in players if p["team"] == team]
    if status and status != "all":
        players = [p for p in players if p["status"] == status]
    if q:
        ql = q.lower()
        players = [p for p in players if ql in p["name"].lower() or ql in p["team"].lower()]
    return {"players": players, "total": len(players), "last_updated": CACHE["last_updated"], "cache_status": CACHE["status"]}

@app.get("/api/teams")
def get_teams(league: str = None):
    players = CACHE["players"]
    if league and league != "all":
        players = [p for p in players if p["league"] == league]
    return {"teams": sorted(set(p["team"] for p in players))}

@app.post("/api/refresh")
async def manual_refresh():
    return await fetch_all()

@app.get("/api/status")
def get_status():
    counts = {}
    for p in CACHE["players"]:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {"total": len(CACHE["players"]), "counts": counts, "last_updated": CACHE["last_updated"], "status": CACHE["status"]}

def scheduled_job():
    import asyncio
    print("⏰ Otomatik güncelleme (Pazartesi 22:00)")
    asyncio.run(fetch_all())

scheduler = BackgroundScheduler(timezone="Europe/Istanbul")
scheduler.add_job(scheduled_job, CronTrigger(day_of_week="mon", hour=22, minute=0))
scheduler.start()

@app.on_event("startup")
async def startup():
    print("🚀 Batingun Master Tool başlatılıyor...")
    await fetch_all()
