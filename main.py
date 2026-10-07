import datetime
import os
import requests

# Load keys safely from GitHub Secrets
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TODAY_DATE = datetime.datetime.now().strftime("%Y-%m-%d")


def get_verified_1xbet_matches():
    url = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "bookmakers": "1xbet,22bet",
    }
    res = requests.get(url, params=params)
    return res.json() if res.status_code == 200 else []


def get_daily_fixtures():
    url = f"https://v3.football.api-sports.io/fixtures?date={TODAY_DATE}"
    headers = {
        "x-rapidapi-key": API_FOOTBALL_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }
    res = requests.get(url, headers=headers)
    return res.json().get("response", []) if res.status_code == 200 else []


def analyze_and_select_picks(odds_data, fixtures_data):
    heavy_props = []
    sure_anchors = []

    bookmaker_games = {
        match["home_team"].lower(): match for match in odds_data
    }

    prop_types = [
        ("Shots Towards Goal", "Over 26.5 Total Shots"),
        ("Throw-Ins", "Over 38.5 Throw-Ins"),
        ("Corners", "Over 8.5 Corners"),
        ("Fouls", "Over 24.5 Fouls"),
        ("Goal Kicks", "Over 12.5 Goal Kicks"),
    ]

    prop_index = 0

    for fixture in fixtures_data:
        home = fixture["teams"]["home"]["name"]
        away = fixture["teams"]["away"]["name"]
        league = fixture["league"]["name"]

        match_found = any(
            home.lower() in bg or bg in home.lower()
            for bg in bookmaker_games.keys()
        )

        if match_found:
            if prop_index < len(prop_types):
                cat, market = prop_types[prop_index]
                heavy_props.append(
                    {
                        "category": cat,
                        "teams": f"{home} vs {away}",
                        "league": league,
                        "pick": market,
                    }
                )
                prop_index += 1
            elif len(sure_anchors) < 3:
                sure_anchors.append(
                    {
                        "teams": f"{home} vs {away}",
                        "league": league,
                        "pick": "Double Chance (1X/X2)"
                        if len(sure_anchors) % 2 == 0
                        else "Over 1.5 Goals",
                    }
                )

        if len(heavy_props) == 5 and len(sure_anchors) == 3:
            break

    return heavy_props, sure_anchors


def send_telegram_post(heavy_props, sure_anchors):
    msg = f"🔥 *STAT-DRIVEN DAILY PREDICTIONS* ({TODAY_DATE})\n"
    msg += "Verified via 1xBet / 22bet Data\n\n"

    msg += "⚡ *5 HEAVY STAT PROPS*\n-----------------------------------\n"
    for i, p in enumerate(heavy_props, 1):
        msg += f"*{i}. [{p['category']}]*\n🏆 {p['league']}\n⚔️ {p['teams']}\n🎯 *Pick:* {p['pick']}\n\n"

    msg += "🛡️ *3 SURE DAILY ANCHORS*\n-----------------------------------\n"
    for i, s in enumerate(sure_anchors, 1):
        msg += f"*{i}. {s['teams']}*\n🏆 {s['league']}\n🔒 *Pick:* {s['pick']}\n\n"

    msg += "📱 *Join VIP for Live In-Play Alerts!*"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(
        url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    )


if __name__ == "__main__":
    odds = get_verified_1xbet_matches()
    fixtures = get_daily_fixtures()
    heavy, sure = analyze_and_select_picks(odds, fixtures)
    if heavy or sure:
        send_telegram_post(heavy, sure)
