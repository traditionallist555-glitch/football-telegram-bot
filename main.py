import datetime
import html
import os
import requests
from curl_cffi import requests as c_requests

# Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PROXY_URL = os.environ.get("HTTP_PROXY") or os.environ.get("PROXY_URL")

# Primary and Mirror Endpoints for 1xBet Live Line Feeds
FEED_ENDPOINTS = [
    "https://1xbet.com/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=100&lng=en&subgames=true",
    "https://1xbet.ng/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=100&lng=en&subgames=true",
    "https://888starz.bet/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=100&lng=en&subgames=true",
    "https://melbet.com/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=100&lng=en&subgames=true",
    "https://1xstavka.ru/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=100&lng=en&subgames=true",
]

CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://1xbet.com/",
}

STAT_CATEGORIES = [
    {"name": "FOULS", "keywords": ["foul", "fouls"], "unit": "Fouls"},
    {"name": "CORNERS", "keywords": ["corner", "corners"], "unit": "Corners"},
    {"name": "CARDS / DISCIPLINE", "keywords": ["card", "yellow card", "booking"], "unit": "Cards"},
    {"name": "OFFSIDES", "keywords": ["offside", "offsides"], "unit": "Offsides"},
    {"name": "SHOTS ON TARGET", "keywords": ["shots on target", "shots towards"], "unit": "Shots"},
    {"name": "THROW-INS", "keywords": ["throw", "throw-in", "throwin"], "unit": "Throw-ins"},
    {"name": "GOALKEEPER SAVES", "keywords": ["saves", "goalkeeper saves"], "unit": "Saves"},
]

def escape_html(text: str) -> str:
    """Safely escapes HTML special characters to prevent Telegram API 400 errors."""
    if not text:
        return ""
    return html.escape(str(text))

def fetch_1xbet_raw_feed():
    """Fetch line feed from 1xBet endpoints with mirror failover and proxy support."""
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

    for url in FEED_ENDPOINTS:
        print(f"🔍 Connecting to endpoint: {url[:38]}...")
        try:
            res = c_requests.get(
                url,
                headers=CUSTOM_HEADERS,
                impersonate="chrome124",
                proxies=proxies,
                timeout=15
            )
            
            if res.status_code == 200:
                data = res.json()
                games = data.get("Value", [])
                if games:
                    print(f"✅ Successfully retrieved {len(games)} live matches!")
                    return games
                else:
                    print(f"⚠️ 200 OK received, but payload contained 0 games.")
            else:
                print(f"⚠️ HTTP Status {res.status_code} on {url[:38]}. Trying mirror fallback...")
        except Exception as e:
            print(f"⚠️ Mirror connection error: {e}")

    return []

def extract_over_pick(events, unit_label):
    overs = []
    for ev in events:
        bet_type = ev.get("T")   # 9 = Total Over in 1xBet API system
        param = ev.get("P")
        price = ev.get("C")

        if bet_type == 9 and param is not None and price is not None:
            overs.append({
                "pick": f"Over ({param}) {unit_label}",
                "odd": f"{float(price):.2f}",
                "raw_odd": float(price)
            })

    if overs:
        # Select bet line closest to ~1.80 odds for optimal value
        return min(overs, key=lambda x: abs(x["raw_odd"] - 1.80))
    return None

def extract_double_chance(events):
    for ev in events:
        bet_type = ev.get("T") # 4 = 1X, 6 = X2
        price = ev.get("C")

        if bet_type in (4, 6) and price:
            pick_label = "Double Chance (1X)" if bet_type == 4 else "Double Chance (X2)"
            return {"pick": pick_label, "odd": f"{float(price):.2f}"}
    return None

def build_predictions():
    games = fetch_1xbet_raw_feed()
    if not games:
        print("❌ All 1xBet mirrors blocked or returned 0 games.")
        return [], []

    stat_props = []
    anchors = []
    used_matches = set()

    print("\n📊 Extracting Stat Props and Daily Anchors...")

    for game in games:
        # Exit early if quotas are met (7 stat props, 3 anchors)
        if len(stat_props) >= 7 and len(anchors) >= 3:
            break

        home = game.get("O1", "")
        away = game.get("O2", "")
        league = game.get("LE", "Soccer")
        match_id = game.get("I")

        if not home or not away or not match_id or match_id in used_matches:
            continue

        match_name = f"{home} vs {away}"
        sub_games = game.get("SG", [])

        # 1. Extract Stat Props from SubGames (SG) payload
        if len(stat_props) < 7:
            match_captured = False
            for cat in STAT_CATEGORIES:
                for sg in sub_games:
                    sub_title = (sg.get("PN") or sg.get("SN") or "").lower()
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
                            match_captured = True
                            break
                if match_captured:
                    break  # Ensure max 1 stat prop per match

        # 2. Extract Daily Anchors from main match lines
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

    return stat_props, anchors

def send_telegram_post(stat_props, anchors):
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram credentials missing! Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return

    if not stat_props and not anchors:
        msg = (
            f"⚠️ <b>1XBET STAT BOT NOTICE</b> ({today_str})\n\n"
            "Live feed endpoints are currently updating or rate-limited by Cloudflare. "
            "Will re-attempt on next scheduled trigger."
        )
    else:
        msg = (
            f"🔥 <b>1XBET REAL-TIME STAT PREDICTIONS</b> ({today_str})\n"
            "💯 <b>Direct Live Bookmaker Feed</b>\n\n"
        )

        if stat_props:
            msg += f"⚡ <b>{len(stat_props)} HEAVY MATCH STAT PROPS</b>\n-----------------------------------\n"
            for i, p in enumerate(stat_props, 1):
                msg += (
                    f"<b>{i}. [{escape_html(p['category'])}]</b>\n"
                    f"🏆 {escape_html(p['league'])}\n"
                    f"⚔️ {escape_html(p['teams'])}\n"
                    f"🎯 <b>Pick:</b> {escape_html(p['pick'])}\n"
                    f"💵 <b>Odds:</b> @ {p['odd']}\n\n"
                )

        if anchors:
            msg += f"🛡️ <b>{len(anchors)} SURE DAILY ANCHORS</b>\n-----------------------------------\n"
            for i, a in enumerate(anchors, 1):
                msg += (
                    f"<b>{i}. {escape_html(a['teams'])}</b>\n"
                    f"🏆 {escape_html(a['league'])}\n"
                    f"🔒 <b>Pick:</b> {escape_html(a['pick'])}\n"
                    f"💵 <b>Odds:</b> @ {a['odd']}\n\n"
                )

        msg += "📱 <b>Join Telegram VIP Channel for In-Play Live Value Alerts!</b>"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("\n✅ Telegram notification successfully posted!")
        else:
            print(f"\n❌ Telegram API Error ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"\n❌ Failed to post message to Telegram: {e}")

if __name__ == "__main__":
    stats, anchors = build_predictions()
    send_telegram_post(stats, anchors)
