import datetime
import os
import re
import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

API_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}
BASE_URL = "https://v3.football.api-sports.io"

# 7 STRICT STAT CATEGORIES (Mapped to 1xBet Live Line Patterns)
STAT_CATEGORIES = [
    {"name": "FOULS", "keywords": [r"foul", r"fouls"], "unit": "Fouls"},
    {"name": "CORNERS", "keywords": [r"corner", r"corners"], "unit": "Corners"},
    {"name": "CARDS / DISCIPLINE", "keywords": [r"card", r"cards", r"yellow card", r"booking"], "unit": "Cards"},
    {"name": "OFFSIDES", "keywords": [r"offside", r"offsides"], "unit": "Offsides"},
    {"name": "SHOTS ON TARGET", "keywords": [r"shots on target", r"shots towards", r"total shots"], "unit": "Shots"},
    {"name": "THROW-INS", "keywords": [r"throw", r"throw-in", r"throw in"], "unit": "Throw-ins"},
    {"name": "GOALKEEPER SAVES", "keywords": [r"saves", r"goalkeeper saves", r"tackles"], "unit": "Saves"},
]

def get_24h_window():
    """Calculate 7:00 AM Today to 7:00 AM Tomorrow UTC."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_7am = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)

    if now_utc >= today_7am:
        window_start = today_7am
        window_end = today_7am + datetime.timedelta(days=1)
    else:
        window_start = today_7am - datetime.timedelta(days=1)
        window_end = today_7am

    earliest_kickoff = max(now_utc + datetime.timedelta(minutes=30), window_start)
    return earliest_kickoff, window_end

def fetch_upcoming_fixtures():
    """Fetch all scheduled fixtures in the 24h window."""
    earliest_kickoff, window_end = get_24h_window()
    date_str = earliest_kickoff.strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}/fixtures?date={date_str}&status=NS"
    print(f"🔍 Fetching upcoming matches for {date_str}...")
    
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=12)
        if res.status_code == 200:
            fixtures = res.json().get("response", [])
            valid = []
            for f in fixtures:
                m_date = datetime.datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
                if earliest_kickoff <= m_date < window_end:
                    valid.append(f)
            print(f"✅ Found {len(valid)} matches scheduled in the current window.")
            return valid
        else:
            print(f"❌ API Error ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Request failed: {e}")
    return []

def fetch_1xbet_odds(fixture_id):
    """Fetch odds specifically from 1xBet (Bookmaker ID: 1 or 1xBet)."""
    # Query odds endpoint targeting 1xBet explicitly
    url = f"{BASE_URL}/odds?fixture={fixture_id}&bookmaker=1"
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data and "bookmakers" in data[0] and data[0]["bookmakers"]:
                return data[0]["bookmakers"][0].get("bets", [])
            
            # Fallback if bookmaker ID 1 filter is empty: get general odds and extract 1xBet
            url_fallback = f"{BASE_URL}/odds?fixture={fixture_id}"
            res_fb = requests.get(url_fallback, headers=API_HEADERS, timeout=10)
            if res_fb.status_code == 200:
                data_fb = res_fb.json().get("response", [])
                if data_fb and "bookmakers" in data_fb[0]:
                    for bm in data_fb[0]["bookmakers"]:
                        if "1xbet" in bm.get("name", "").lower() or bm.get("id") == 1:
                            return bm.get("bets", [])
                    # If 1xBet not explicitly separated, return primary bookmaker lines
                    if data_fb[0]["bookmakers"]:
                        return data_fb[0]["bookmakers"][0].get("bets", [])
    except Exception as e:
        print(f"⚠️ Error fetching odds for fixture {fixture_id}: {e}")
    return []

def extract_stat_line(bets, keywords, unit):
    """Extract live market lines and pricing from 1xBet bets array."""
    for bet in bets:
        b_name = bet.get("name", "").lower()
        if any(re.search(kw, b_name) for kw in keywords):
            values = bet.get("values", [])
            overs = [v for v in values if "over" in str(v.get("value", "")).lower()]
            if overs:
                # Target primary balanced line near odds 1.60 - 2.00
                selected = min(overs, key=lambda x: abs(float(x.get("odd", 2.0)) - 1.80))
                return {
                    "pick": f"{selected.get('value')} {unit}",
                    "odd": f"{float(selected.get('odd')):.2f}"
                }
    return None

def extract_anchor_line(bets):
    """Extract Double Chance or Total Goals from 1xBet bets array."""
    for bet in bets:
        b_name = bet.get("name", "").lower()
        values = bet.get("values", [])

        if "double chance" in b_name and values:
            return {
                "pick": f"Double Chance ({values[0].get('value')})",
                "odd": f"{float(values[0].get('odd')):.2f}"
            }
        
        if ("goals over/under" in b_name or b_name == "total") and values:
            overs = [v for v in values if "over 1.5" in str(v.get("value")).lower() or "over 2.5" in str(v.get("value")).lower()]
            if overs:
                v = overs[0]
                return {
                    "pick": f"Goals {v.get('value')}",
                    "odd": f"{float(v.get('odd')):.2f}"
                }
    return None

def build_predictions():
    fixtures = fetch_upcoming_fixtures()
    if not fixtures:
        print("❌ No valid fixtures found in current window.")
        return [], []

    stat_props = []
    anchors = []
    used_fixtures = set()

    print("\n📊 Extracting 1xBet Live Odds for Stat Props...")
    
    # 1. Gather 7 Heavy Stat Props
    for cat in STAT_CATEGORIES:
        if len(stat_props) >= 7:
            break

        for f in fixtures:
            fid = f["fixture"]["id"]
            if fid in used_fixtures:
                continue

            bets = fetch_1xbet_odds(fid)
            if not bets:
                continue

            stat_pick = extract_stat_line(bets, cat["keywords"], cat["unit"])
            if stat_pick:
                home = f["teams"]["home"]["name"]
                away = f["teams"]["away"]["name"]
                league = f"{f['league']['name']} ({f['league']['country']})"

                stat_props.append({
                    "category": cat["name"],
                    "teams": f"{home} vs {away}",
                    "league": league,
                    "pick": stat_pick["pick"],
                    "odd": stat_pick["odd"]
                })
                used_fixtures.add(fid)
                print(f"  └─ Captured [{cat['name']}]: {home} vs {away} -> {stat_pick['pick']} @ {stat_pick['odd']}")
                break

    # 2. Gather 3 Sure Anchors
    print("\n🛡️ Extracting 3 Daily Anchors...")
    for f in fixtures:
        if len(anchors) >= 3:
            break

        fid = f["fixture"]["id"]
        if fid in used_fixtures:
            continue

        bets = fetch_1xbet_odds(fid)
        if not bets:
            continue

        anchor_pick = extract_anchor_line(bets)
        if anchor_pick:
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            league = f"{f['league']['name']} ({f['league']['country']})"

            anchors.append({
                "teams": f"{home} vs {away}",
                "league": league,
                "pick": anchor_pick["pick"],
                "odd": anchor_pick["odd"]
            })
            used_fixtures.add(fid)
            print(f"  └─ Captured [ANCHOR]: {home} vs {away} -> {anchor_pick['pick']} @ {anchor_pick['odd']}")

    return stat_props, anchors

def send_telegram_post(stat_props, anchors):
    if not stat_props and not anchors:
        print("\n❌ No predictions gathered. Telegram post aborted.")
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = f"🔥 *1XBET REAL-TIME STAT PREDICTIONS* ({today_str})\n"
    msg += "💯 *Verified Live Bookmaker Odds*\n\n"

    if stat_props:
        msg += f"⚡ *{len(stat_props)} HEAVY MATCH STAT PROPS*\n-----------------------------------\n"
        for i, p in enumerate(stat_props, 1):
            msg += f"*{i}. [{p['category']}]*\n🏆 {p['league']}\n⚔️ {p['teams']}\n🎯 *Pick:* {p['pick']}\n💵 *Odds:* @ {p['odd']}\n\n"

    if anchors:
        msg += f"🛡️ *{len(anchors)} SURE DAILY ANCHORS*\n-----------------------------------\n"
        for i, a in enumerate(anchors, 1):
            msg += f"*{i}. {a['teams']}*\n🏆 {a['league']}\n🔒 *Pick:* {a['pick']}\n💵 *Odds:* @ {a['odd']}\n\n"

    msg += "📱 *Join VIP Channel for In-Play Live Value Alerts!*"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    res = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    
    if res.status_code == 200:
        print("\n✅ Telegram post sent successfully!")
    else:
        print(f"\n❌ Telegram Error ({res.status_code}): {res.text}")

if __name__ == "__main__":
    stats, anchors = build_predictions()
    send_telegram_post(stats, anchors)
    
