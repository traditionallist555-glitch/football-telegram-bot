import datetime
import os
import requests
from curl_cffi import requests as c_requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 1xBet Direct Mobile API (Soccer = Sport 1)
ONEXBET_FEED_URL = "https://1xbet.com/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=100&lng=en&subgames=true"

# Stat sub-game names as listed inside 1xBet's system
STAT_CATEGORIES = [
    {"name": "FOULS", "keywords": ["foul", "fouls"], "unit": "Fouls"},
    {"name": "CORNERS", "keywords": ["corner", "corners"], "unit": "Corners"},
    {"name": "CARDS / DISCIPLINE", "keywords": ["card", "yellow card", "booking"], "unit": "Cards"},
    {"name": "OFFSIDES", "keywords": ["offside", "offsides"], "unit": "Offsides"},
    {"name": "SHOTS ON TARGET", "keywords": ["shots on target", "shots towards"], "unit": "Shots"},
    {"name": "THROW-INS", "keywords": ["throw", "throw-in", "throwin"], "unit": "Throw-ins"},
    {"name": "GOALKEEPER SAVES", "keywords": ["saves", "goalkeeper saves"], "unit": "Saves"},
]

def fetch_1xbet_raw_feed():
    """Fetch live pre-match line directly from 1xBet using browser TLS impersonation."""
    print("🔍 Requesting live feed directly from 1xBet API...")
    try:
        # Impersonate Chrome 120 browser TLS fingerprint to pass Cloudflare
        res = c_requests.get(ONEXBET_FEED_URL, impersonate="chrome120", timeout=20)
        if res.status_code == 200:
            data = res.json()
            games = data.get("Value", [])
            print(f"✅ Successfully retrieved {len(games)} live matches from 1xBet.")
            return games
        else:
            print(f"❌ 1xBet HTTP Error {res.status_code}: Cloudflare or IP block.")
    except Exception as e:
        print(f"❌ Error fetching 1xBet feed: {e}")
    return []

def extract_over_pick(events, unit_label):
    """Extract the primary Over bet line with realistic odds around 1.60 - 2.00."""
    overs = []
    for ev in events:
        bet_type = ev.get("T")   # 9 = Total Over in 1xBet system
        param = ev.get("P")      # Barrier line (e.g. 23.5, 2.5)
        price = ev.get("C")      # Decimal Odds (e.g. 1.67)

        if bet_type == 9 and param and price:
            overs.append({
                "pick": f"Over ({param}) {unit_label}",
                "odd": f"{float(price):.2f}",
                "raw_odd": float(price)
            })

    if overs:
        # Select balanced odds closest to 1.80
        return min(overs, key=lambda x: abs(x["raw_odd"] - 1.80))
    return None

def extract_double_chance(events):
    """Extract 1X or X2 Double Chance from match events."""
    for ev in events:
        bet_type = ev.get("T") # 4 = 1X, 6 = X2
        price = ev.get("C")

        if bet_type == 4 and price:
            return {"pick": "Double Chance (1X)", "odd": f"{float(price):.2f}"}
        elif bet_type == 6 and price:
            return {"pick": "Double Chance (X2)", "odd": f"{float(price):.2f}"}
    return None

def build_predictions():
    games = fetch_1xbet_raw_feed()
    if not games:
        print("⚠️ No matches available to process.")
        return [], []

    stat_props = []
    anchors = []
    used_matches = set()

    print("\n📊 Extracting Stat Props and Anchors from 1xBet payload...")

    for game in games:
        home = game.get("O1", "")
        away = game.get("O2", "")
        league = game.get("LE", "Soccer")
        match_id = game.get("I")

        if not home or not away or match_id in used_matches:
            continue

        match_name = f"{home} vs {away}"

        # 1. Inspect SubGames (SG) where 1xBet stores Fouls, Cards, Offsides, etc.
        sub_games = game.get("SG", [])
        
        for cat in STAT_CATEGORIES:
            if len(stat_props) >= 7:
                break

            for sg in sub_games:
                sub_title = (sg.get("PN") or sg.get("SN") or "").lower()
                
                # Match stat sub-tab (e.g. "Fouls", "Offsides", "Yellow Cards")
                if any(kw in sub_title for kw in cat["keywords"]):
                    events = sg.get("E", [])
                    pick_data = extract_over_pick(events, cat["unit"])
                    if pick_data:
                        stat_props.append({
                            "category": cat["name"],
                            "teams": match_name,
                            "league": league,
                            "pick": pick_data["pick"],
                            "odd": pick_data["odd"]
                        })
                        used_matches.add(match_id)
                        print(f"  └─ Captured [{cat['name']}]: {match_name} -> {pick_data['pick']} @ {pick_data['odd']}")
                        break

        # 2. Extract Anchor (Double Chance) from Main Game
        if len(anchors) < 3 and match_id not in used_matches:
            main_events = game.get("E", [])
            anchor_pick = extract_double_chance(main_events)
            if anchor_pick:
                anchors.append({
                    "teams": match_name,
                    "league": league,
                    "pick": anchor_pick["pick"],
                    "odd": anchor_pick["odd"]
                })
                used_matches.add(match_id)
                print(f"  └─ Captured [ANCHOR]: {match_name} -> {anchor_pick['pick']} @ {anchor_pick['odd']}")

        if len(stat_props) >= 7 and len(anchors) >= 3:
            break

    return stat_props, anchors

def send_telegram_post(stat_props, anchors):
    if not stat_props and not anchors:
        print("\n❌ No predictions gathered. Telegram post aborted.")
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = f"🔥 *1XBET REAL-TIME STAT PREDICTIONS* ({today_str})\n"
    msg += "💯 *Verified Live 1xBet Feed*\n\n"

    if stat_props:
        msg += f"⚡ *{len(stat_props)} HEAVY MATCH STAT PROPS*\n-----------------------------------\n"
        for i, p in enumerate(stat_props, 1):
            msg += f"*{i}. [{p['category']}]*\n🏆 {p['league']}\n⚔️ {p['teams']}\n🎯 *Pick:* {p['pick']}\n💵 *Odds:* @ {p['odd']}\n\n"

    if anchors:
        msg += f"🛡️ *{len(anchors)} SURE DAILY ANCHORS*\n-----------------------------------\n"
        for i, a in enumerate(anchors, 1):
            msg += f"*{i}. {a['teams']}*\n🏆 {a['league']}\n🔒 *Pick:* {a['pick']}\n💵 *Odds:* @ {a['odd']}\n\n"

    msg += "📱 *Join Telegram VIP Channel for In-Play Live Value Alerts!*"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    res = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    
    if res.status_code == 200:
        print("\n✅ Telegram post sent successfully!")
    else:
        print(f"\n❌ Telegram Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    stats, anchors = build_predictions()
    send_telegram_post(stats, anchors)
        
