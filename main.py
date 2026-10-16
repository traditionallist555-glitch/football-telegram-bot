import datetime
import html
import json
import os
import time
import requests
from curl_cffi import requests as c_requests
from pathlib import Path

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PROXY_URL = os.environ.get("HTTP_PROXY") or os.environ.get("PROXY_URL")

FEED_ENDPOINTS = [
    # Live
    "https://1xbet.com/LiveFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    "https://1xbet.ng/LiveFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    "https://888starz.bet/LiveFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    "https://melbet.com/LiveFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    # Pre-match (more stable)
    "https://1xbet.com/LineFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    "https://1xbet.ng/LineFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    "https://melbet.com/LineFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
    "https://22bet.com/LineFeed/GetGamesZip?sports=1&count=150&lng=en&subgames=true",
]

CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://1xbet.com/",
    "Origin": "https://1xbet.com",
}

STAT_CATEGORIES = [
    {"name": "Throw-Ins", "keywords": ["throw", "throw-in", "throwin"], "unit": "Throw-Ins"},
    {"name": "Fouls", "keywords": ["foul", "fouls"], "unit": "Fouls"},
    {"name": "Corners", "keywords": ["corner", "corners"], "unit": "Corners"},
    {"name": "Cards", "keywords": ["card", "yellow card", "booking"], "unit": "Cards"},
    {"name": "Shots on Target", "keywords": ["shots on target"], "unit": "Shots on Target"},
    {"name": "Tackles", "keywords": ["tackle", "tackles"], "unit": "Tackles"},
    {"name": "Goal Kicks", "keywords": ["goal kick", "goal kicks"], "unit": "Goal Kicks"},
    {"name": "Shots Towards Goal", "keywords": ["shots towards", "total shots", "shots"], "unit": "Shots Towards Goal"},
]

def escape_html(text: str) -> str:
    return html.escape(str(text)) if text else ""

def fetch_1xbet_raw_feed():
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
    for url in FEED_ENDPOINTS:
        domain = url.split("/")[2]
        feed_type = "LIVE" if "LiveFeed" in url else "LINE"
        print(f"🔍 Trying [{feed_type}] → {domain}")
        try:
            res = c_requests.get(
                url,
                headers=CUSTOM_HEADERS,
                impersonate="chrome124",
                proxies=proxies,
                timeout=15
            )
            if res.status_code == 200:
                games = res.json().get("Value", [])
                if games and len(games) > 5:
                    print(f"✅ Success! {len(games)} matches from {domain}")
                    return games
                else:
                    print(f"⚠️ Empty or too few games from {domain}")
            else:
                print(f"❌ Status {res.status_code} from {domain}")
        except Exception as e:
            print(f"⚠️ Error on {domain}: {e}")
        time.sleep(1.2)
    return []

def extract_over_pick(events, unit_label, prefer_range=(1.65, 2.15)):
    overs = []
    for ev in events:
        if ev.get("T") == 9 and ev.get("P") is not None and ev.get("C") is not None:
            odd = float(ev["C"])
            param = float(ev["P"])
            if prefer_range[0] <= odd <= prefer_range[1]:
                overs.append({
                    "param": param,
                    "odd": odd,
                    "pick": f"Over {param} Total {unit_label}",
                    "score": abs(odd - 1.85)  # closer to 1.85 = better
                })
    if overs:
        return min(overs, key=lambda x: x["score"])
    return None

def build_predictions():
    games = fetch_1xbet_raw_feed()
    if not games:
        print("❌ No games retrieved from any endpoint")
        return [], [], 0, []

    props = []
    special_shots = []
    used = set()
    total_matches = len(games)

    # ========== NORMAL PROPS (max 7) ==========
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
            if cat["name"] == "Shots Towards Goal":
                continue  # we handle this separately for the special section
            for sg in game.get("SG", []):
                title = (sg.get("PN") or sg.get("SN") or "").lower()
                if any(k in title for k in cat["keywords"]):
                    pick = extract_over_pick(sg.get("E", []), cat["unit"])
                    if pick:
                        model_pct = max(68, min(84, int(92 - abs(pick["odd"] - 1.85) * 28)))
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
                            "reason": "Selected from live bookmaker feed with value filter (1.65–2.15)."
                        })
                        used.add(mid)
                        break
            if mid in used:
                break

    # ========== 3 CAREFULLY SELECTED SHOTS TOWARDS GOAL ==========
    # Very strict: only good odds + clear market
    for game in games:
        if len(special_shots) >= 3:
            break
        home = game.get("O1", "")
        away = game.get("O2", "")
        league = game.get("LE", "Soccer")
        mid = game.get("I")
        if not home or not away or not mid or mid in used:
            continue

        for sg in game.get("SG", []):
            title = (sg.get("PN") or sg.get("SN") or "").lower()
            if any(k in title for k in ["shots towards", "total shots", "shots"]):
                pick = extract_over_pick(sg.get("E", []), "Shots Towards Goal", prefer_range=(1.70, 2.05))
                if pick and pick["odd"] <= 2.00:  # extra strict
                    model_pct = max(72, min(86, int(94 - abs(pick["odd"] - 1.85) * 30)))
                    special_shots.append({
                        "num": f"{len(special_shots)+1:02d}",
                        "cat": "Shots Towards Goal",
                        "pct": model_pct,
                        "league": league,
                        "home": home,
                        "away": away,
                        "form": "— · —",
                        "pick": pick["pick"],
                        "meta": f"Special board {pick['odd']:.2f} · carefully filtered",
                        "reason": "Strictly selected Shots Towards Goal prop. Only strong value lines accepted."
                    })
                    used.add(mid)
                    break

    return props, total_matches, len(used), special_shots

def save_daily_json(props, total_matches, sampled, special_shots):
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
        "special_shots": special_shots,
        "special": {
            "odds": "—",
            "league": "Special appears when strong 3.00+ price is found",
            "match": "—",
            "pick": "—",
            "reason": "Price special is selected only when a strong 3.00+ opportunity exists."
        }
    }

    Path("data").mkdir(exist_ok=True)
    path = Path(f"data/{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved {path}")

    # Update index
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

def send_telegram_post(props, special_shots):
    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram credentials missing")
        return

    if not props and not special_shots:
        msg = f"⚠️ <b>SPRINTKILLER</b> ({today_str})\nNo strong props found today from live feed."
    else:
        msg = f"🔥 <b>SPRINTKILLER MODEL BOARD</b> ({today_str})\n💯 West Africa Window\n\n"
        if props:
            msg += f"⚡ <b>{len(props)} HEAVY STAT PROPS</b>\n-----------------------------------\n"
            for p in props:
                msg += (
                    f"<b>{p['num']}. [{escape_html(p['cat'])}]</b> · {p['pct']}%\n"
                    f"🏆 {escape_html(p['league'])}\n"
                    f"⚔️ {escape_html(p['home'])} vs {escape_html(p['away'])}\n"
                    f"🎯 <b>{escape_html(p['pick'])}</b>\n\n"
                )
        if special_shots:
            msg += f"🎯 <b>{len(special_shots)} CAREFULLY SELECTED SHOTS TOWARDS GOAL</b>\n-----------------------------------\n"
            for p in special_shots:
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
    props, total, sampled, special_shots = build_predictions()
    save_daily_json(props, total, sampled, special_shots)
    send_telegram_post(props, special_shots)
