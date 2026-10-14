import datetime
import html
import json
import os
import requests
from curl_cffi import requests as c_requests
from pathlib import Path

# Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PROXY_URL = os.environ.get("HTTP_PROXY") or os.environ.get("PROXY_URL")

FEED_ENDPOINTS = [
    "https://1xbet.com/LiveFeed/GetGamesZip?sports=1&count=100&lng=en&subgames=true",
    "https://1xbet.ng/LiveFeed/GetGamesZip?sports=1&count=100&lng=en&subgames=true",
    "https://888starz.bet/LiveFeed/GetGamesZip?sports=1&count=100&lng=en&subgames=true",
    "https://1xbet.com/LineFeed/GetGamesZip?sports=1&count=100&lng=en&subgames=true",
    "https://1xbet.ng/LineFeed/GetGamesZip?sports=1&count=100&lng=en&subgames=true",
    "https://melbet.com/LineFeed/GetGamesZip?sports=1&count=100&lng=en&subgames=true",
]

CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://1xbet.com/",
}

STAT_CATEGORIES = [
    {"name": "Throw-Ins", "keywords": ["throw", "throw-in", "throwin"], "unit": "Throw-Ins"},
    {"name": "Fouls", "keywords": ["foul", "fouls"], "unit": "Fouls"},
    {"name": "Corners", "keywords": ["corner", "corners"], "unit": "Corners"},
    {"name": "Cards", "keywords": ["card", "yellow card", "booking"], "unit": "Cards"},
    {"name": "Shots on Target", "keywords": ["shots on target", "shots towards"], "unit": "Shots on Target"},
    {"name": "Tackles", "keywords": ["tackle", "tackles"], "unit": "Tackles"},
    {"name": "Goal Kicks", "keywords": ["goal kick", "goal kicks"], "unit": "Goal Kicks"},
]

def escape_html(text: str) -> str:
    return html.escape(str(text)) if text else ""

def fetch_1xbet_raw_feed():
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
    for url in FEED_ENDPOINTS:
        domain = url.split("/")[2]
        feed_type = "LIVE" if "LiveFeed" in url else "LINE"
        print(f"🔍 Testing [{feed_type}] via {domain}...")
        try:
            res = c_requests.get(url, headers=CUSTOM_HEADERS, impersonate="chrome124",
                                 proxies=proxies, timeout=12)
            if res.status_code == 200:
                games = res.json().get("Value", [])
                if games:
                    print(f"✅ Got {len(games)} matches from {domain} ({feed_type})")
                    return games
        except Exception as e:
            print(f"⚠️ {domain}: {e}")
    return []

def extract_over_pick(events, unit_label):
    overs = []
    for ev in events:
        if ev.get("T") == 9 and ev.get("P") is not None and ev.get("C") is not None:
            overs.append({
                "param": float(ev["P"]),
                "odd": float(ev["C"]),
                "pick": f"Over {ev['P']} Total {unit_label}"
            })
    if overs:
        # Prefer odds closest to 1.80–1.90 (value zone)
        best = min(overs, key=lambda x: abs(x["odd"] - 1.85))
        return best
    return None

def build_predictions():
    games = fetch_1xbet_raw_feed()
    if not games:
        return [], [], 0

    props = []
    used = set()
    total_matches = len(games)

    for game in games:
        if len(props) >= 7:
            break
        home = game.get("O1", "")
        away = game.get("O2", "")
        league = game.get("LE", "Soccer")
        mid = game.get("I")
        if not home or not away or not mid or mid in used:
            continue

        for cat in STAT_CATEGORIES:
            for sg in game.get("SG", []):
                title = (sg.get("PN") or sg.get("SN") or "").lower()
                if any(k in title for k in cat["keywords"]):
                    pick = extract_over_pick(sg.get("E", []), cat["unit"])
                    if pick:
                        # Simple model % (higher when odd is closer to 1.85 and param is reasonable)
                        model_pct = max(65, min(85, int(90 - abs(pick["odd"] - 1.85) * 25)))
                        props.append({
                            "num": f"{len(props)+1:02d}",
                            "cat": cat["name"],
                            "pct": model_pct,
                            "league": league,
                            "home": home,
                            "away": away,
                            "form": "— · —",
                            "pick": pick["pick"],
                            "meta": f"Model board {pick['odd']:.2f} · live feed",
                            "reason": f"Selected from live 1xBet feed. Closest value line around 1.85."
                        })
                        used.add(mid)
                        break
            if mid in used:
                break

    return props, total_matches, len(used)

def save_daily_json(props, total_matches, sampled):
    today = datetime.datetime.utcnow()
    date_str = today.strftime("%Y-%m-%d")
    label = today.strftime("%a %d %b")

    data = {
        "date": date_str,
        "label": label,
        "sub": "Live",
        "matches": total_matches,
        "sampled": sampled,
        "posted": len(props),
        "filled": 0,
        "props": props,
        "special": {
            "odds": "—",
            "league": "Special appears when strong 3.00+ price is found",
            "match": "—",
            "pick": "—",
            "reason": "Price special is selected only when a strong 3.00+ opportunity exists."
        }
    }

    # Save into data/ folder
    Path("data").mkdir(exist_ok=True)
    path = Path(f"data/{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved {path}")

    # Also update index of available dates
    index_path = Path("data/index.json")
    dates = []
    if index_path.exists():
        with open(index_path) as f:
            dates = json.load(f)
    if date_str not in dates:
        dates.append(date_str)
        dates.sort(reverse=True)
        with open(index_path, "w") as f:
            json.dump(dates, f, indent=2)

def send_telegram_post(props):
    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram credentials missing")
        return

    if not props:
        msg = f"⚠️ <b>SPRINTKILLER</b> ({today_str})\nNo strong props found today from live feed."
    else:
        msg = f"🔥 <b>SPRINTKILLER MODEL BOARD</b> ({today_str})\n💯 West Africa Window\n\n"
        for p in props:
            msg += (
                f"<b>{p['num']}. [{escape_html(p['cat'])}]</b> · {p['pct']}%\n"
                f"🏆 {escape_html(p['league'])}\n"
                f"⚔️ {escape_html(p['home'])} vs {escape_html(p['away'])}\n"
                f"🎯 <b>{escape_html(p['pick'])}</b>\n\n"
            )
        msg += "18+ · Model board, not a bookmaker receipt."

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    print("✅ Posted to Telegram")

if __name__ == "__main__":
    props, total, sampled = build_predictions()
    save_daily_json(props, total, sampled)
    send_telegram_post(props)
