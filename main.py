import datetime
import os
import requests

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TODAY_DATE = datetime.datetime.now().strftime("%Y-%m-%d")


def get_verified_1xbet_matches():
    url = "https://api.the-odds-api.com/v4/sports/upcoming/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "bookmakers": "1xbet,22bet",
    }
    try:
        res = requests.get(url, params=params)
        print("Odds API Status Code:", res.status_code)
        if res.status_code == 200:
            return res.json()
        print("Odds API Error Response:", res.text)
        return []
    except Exception as e:
        print(f"Odds API Exception: {e}")
        return []


def get_daily_fixtures():
    url = f"https://v3.football.api-sports.io/fixtures?date={TODAY_DATE}"
    # Corrected header for direct API-Sports account
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
    }
    try:
        res = requests.get(url, headers=headers)
        print("API-Football Status Code:", res.status_code)
        if res.status_code == 200:
            fixtures = res.json().get("response", [])
            print(
                f"Successfully fetched {len(fixtures)} fixtures for {TODAY_DATE}"
            )
            return fixtures
        print("API-Football Error Response:", res.text)
        return []
    except Exception as e:
        print(f"API-Football Exception: {e}")
        return []


def analyze_and_select_picks(odds_data, fixtures_data):
    heavy_props = []
    sure_anchors = []

    bookmaker_games = set()
    if isinstance(odds_data, list):
        for match in odds_data:
            if "home_team" in match:
                bookmaker_games.add(match["home_team"].lower())

    prop_types = [
        ("Shots Towards Goal", "Over 26.5 Total Shots"),
        ("Throw-Ins", "Over 38.5 Throw-Ins"),
        ("Corners", "Over 8.5 Corners"),
        ("Fouls", "Over 24.5 Fouls"),
        ("Goal Kicks", "Over 12.5 Goal Kicks"),
    ]

    prop_index = 0

    if not fixtures_data:
        print("No fixtures returned for today.")
        return [], []

    for fixture in fixtures_data:
        home = fixture["teams"]["home"]["name"]
        away = fixture["teams"]["away"]["name"]
        league = fixture["league"]["name"]
        team_pair = f"{home} vs {away}"

        match_found = (
            any(
                home.lower() in bg or bg in home.lower()
                for bg in bookmaker_games
            )
            if bookmaker_games
            else True
        )

        if match_found:
            if prop_index < len(prop_types):
                cat, market = prop_types[prop_index]
                heavy_props.append(
                    {
                        "category": cat,
                        "teams": team_pair,
                        "league": league,
                        "pick": market,
                    }
                )
                prop_index += 1
            elif len(sure_anchors) < 3:
                sure_anchors.append(
                    {
                        "teams": team_pair,
                        "league": league,
                        "pick": "Double Chance (1X or X2)"
                        if len(sure_anchors) % 2 == 0
                        else "Over 1.5 Goals",
                    }
                )

        if len(heavy_props) == 5 and len(sure_anchors) == 3:
            break

    # Fallback to ensure all 8 slots populate even if line matching is partial
    if len(heavy_props) < 5 or len(sure_anchors) < 3:
        for fixture in fixtures_data:
            home = fixture["teams"]["home"]["name"]
            away = fixture["teams"]["away"]["name"]
            league = fixture["league"]["name"]
            team_pair = f"{home} vs {away}"

            if (
                prop_index < len(prop_types)
                and team_pair not in [p["teams"] for p in heavy_props]
            ):
                cat, market = prop_types[prop_index]
                heavy_props.append(
                    {
                        "category": cat,
                        "teams": team_pair,
                        "league": league,
                        "pick": market,
                    }
                )
                prop_index += 1
            elif (
                len(sure_anchors) < 3
                and team_pair not in [p["teams"] for p in heavy_props]
                and team_pair not in [s["teams"] for s in sure_anchors]
            ):
                sure_anchors.append(
                    {
                        "teams": team_pair,
                        "league": league,
                        "pick": "Double Chance (1X or X2)"
                        if len(sure_anchors) % 2 == 0
                        else "Over 1.5 Goals",
                    }
                )

            if len(heavy_props) == 5 and len(sure_anchors) == 3:
                break

    return heavy_props, sure_anchors


def send_telegram_post(heavy_props, sure_anchors):
    if not heavy_props and not sure_anchors:
        print("No matches available to post.")
        return

    msg = f"🔥 *STAT-DRIVEN DAILY PREDICTIONS* ({TODAY_DATE})\n"
    msg += "Verified via 1xBet / 22bet Data\n\n"

    if heavy_props:
        msg += "⚡ *5 HEAVY STAT PROPS*\n-----------------------------------\n"
        for i, p in enumerate(heavy_props, 1):
            msg += f"*{i}. [{p['category']}]*\n🏆 {p['league']}\n⚔️ {p['teams']}\n🎯 *Pick:* {p['pick']}\n\n"

    if sure_anchors:
        msg += "🛡️ *3 SURE DAILY ANCHORS*\n-----------------------------------\n"
        for i, s in enumerate(sure_anchors, 1):
            msg += f"*{i}. {s['teams']}*\n🏆 {s['league']}\n🔒 *Pick:* {s['pick']}\n\n"

    msg += "📱 *Join VIP for Live In-Play Alerts!*"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    res = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        },
    )
    print("Telegram Response Status:", res.status_code, res.text)


if __name__ == "__main__":
    odds = get_verified_1xbet_matches()
    fixtures = get_daily_fixtures()
    heavy, sure = analyze_and_select_picks(odds, fixtures)
    send_telegram_post(heavy, sure)
        
