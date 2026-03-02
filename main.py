from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from datetime import datetime
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

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
HEADERS = {
    "x-rapidapi-host": "v3.football.api-sports.io",
    "x-rapidapi-key": RAPIDAPI_KEY,
}

LEAGUES = {
    "serie_a":    {"id": 135, "season": 2024, "name": "Serie A",    "flag": "🇮🇹"},
    "la_liga":    {"id": 140, "season": 2024, "name": "LaLiga",     "flag": "🇪🇸"},
    "bundesliga": {"id": 78,  "season": 2024, "name": "Bundesliga", "flag": "🇩🇪"},
}

def map_status(type_str: str) -> str:
    t = type_str.lower()
    if any(x in t for x in ["suspended", "yellow", "red card"]): return "suspended"
    if any(x in t for x in ["doubtful", "questionable"]):        return "doubtful"
    return "injured"

async def fetch_league(league_key: str, info: dict) -> list:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            "https://v3.football.api-sports.io/injuries",
            headers=HEADERS,
            params={"league": info["id"], "season": info["season"]},
        )
        resp.raise_for_status()
        data = resp.json()

    players, seen = [], set()
    for item in data.get("response", []):
        p, t = item.get("player", {}), item.get("team", {})
        key = f"{p.get('name')}_{t.get('name')}"
        if key in seen: continue
        seen.add(key)
        players.append({
            "id":          f"{league_key}_{p.get('id')}",
            "name":        p.get("name", ""),
            "team":        t.get("name", ""),
            "league":      league_key,
            "league_name": info["name"],
            "league_flag": info["flag"],
            "status":      map_status(p.get("type", "")),
            "desc":        p.get("reason", "Bilinmiyor"),
            "ret":         (item.get("fixture") or {}).get("date", "")[:10],
        })
    return players

async def fetch_all():
    all_players, errors = [], []
    for key, info in LEAGUES.items():
        try:
            players = await fetch_league(key, info)
            if len(players) < 3:
                errors.append(f"{info['name']}: Az veri")
            else:
                all_players.extend(players)
                print(f"✅ {info['name']}: {len(players)} oyuncu")
        except Exception as e:
            errors.append(f"{info['name']}: {e}")
            print(f"❌ {info['name']}: {e}")

    if len(all_players) < 5:
        return {"status": "error", "message": "Yeterli veri gelmedi", "errors": errors}

    CACHE["players"]      = all_players
    CACHE["last_updated"] = datetime.now().strftime("%d %b %Y · %H:%M")
    CACHE["status"]       = "ok"
    return {"status": "success", "updated": len(all_players), "errors": errors, "last_updated": CACHE["last_updated"]}

# ── ENDPOINTS ──────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Batingun Master Tool API çalışıyor 🟢", "players": len(CACHE["players"])}

@app.get("/api/players")
def get_players(league: str = None, team: str = None, status: str = None, q: str = None):
    players = CACHE["players"]
    if league and league != "all":         players = [p for p in players if p["league"] == league]
    if team and team != "Tüm Takımlar":   players = [p for p in players if p["team"] == team]
    if status and status != "all":         players = [p for p in players if p["status"] == status]
    if q:
        ql = q.lower()
        players = [p for p in players if ql in p["name"].lower() or ql in p["team"].lower()]
    return {"players": players, "total": len(players), "last_updated": CACHE["last_updated"]}

@app.get("/api/teams")
def get_teams(league: str = None):
    players = CACHE["players"]
    if league and league != "all": players = [p for p in players if p["league"] == league]
    return {"teams": sorted(set(p["team"] for p in players))}

@app.post("/api/refresh")
async def manual_refresh():
    return await fetch_all()

@app.get("/api/status")
def get_status():
    counts = {}
    for p in CACHE["players"]: counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {"total": len(CACHE["players"]), "counts": counts, "last_updated": CACHE["last_updated"]}

# ── SCHEDULER ──────────────────────────────────────────────────────────

def scheduled_job():
    import asyncio
    asyncio.run(fetch_all())

scheduler = BackgroundScheduler(timezone="Europe/Istanbul")
scheduler.add_job(scheduled_job, CronTrigger(day_of_week="mon", hour=22, minute=0))
scheduler.start()

@app.on_event("startup")
async def startup():
    print("🚀 Batingun Master Tool başlatılıyor...")
    await fetch_all()
