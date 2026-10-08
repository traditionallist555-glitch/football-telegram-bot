import datetime
import os
import re
import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TODAY_DATE = datetime.datetime.now().strftime("%Y-%m-%d")
API_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}


def get_daily_fixtures():
    """Fetch today's scheduled upcoming fixtures."""
    url = f"https://v3.football.api-sports.io/fixtures?date={TODAY_DATE}&status=NS"
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=12)
        if res.status_code == 200:
            fixtures = res.json().get("response", [])
            print(f"Total upcoming fixtures found for today: {len(fixtures)}")
            return fixtures
        print(f"Fixtures API Error: {res.status_code} - {res.text}")
        return []
    except Exception as e:
        print(f"Exception fetching fixtures: {e}")
        return []


def get_live_bookmaker_odds(fixture_id):
    """Fetch live odds array directly from bookmakers for exact market lines."""
    url = f"https://v3.football.api-sports.io/odds?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=12)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data and "bookmakers" in data[0]:
                return data[0]["bookmakers"]
    except Exception as e:
        print(f"Error fetching odds for fixture {fixture_id}: {e}")
    return []


def get_fixture_prediction(fixture_id):
    """Fetch match statistics engine data for expected value calculations."""
    url = (
        f"https://v3.football.api-sports.io/predictions?fixture={fixture_id}"
    )
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=12)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data:
                return data[0]
    except Exception as e:
        print(f"Error fetching prediction for fixture {fixture_id}: {e}")
    return None


def parse_stat_market_dynamically(
    bookmakers, keywords, category_name, pred_data
):
    """Extract exact live market lines, real bookmaker odds, and calculate dynamic expected stats."""
    target_value_obj = None

    # Search through active bookmakers for matching stat markets
    for bm in bookmakers:
        for bet in bm.get("bets", []):
            bet_name = bet.get("name", "").lower()
            if any(kw in bet_name for kw in keywords):
                # Filter 'Over' selections
                over_values = [
                    v
                    for v in bet.get("values", [])
                    if "over" in str(v.get("value", "")).lower()
                ]
                if over_values:
                    # Pick the balanced market line (odds closest to 1.85)
                    target_value_obj = min(
                        over_values,
                        key=lambda x: abs(float(x.get("odd", 2.0)) - 1.85),
                    )
                    break
        if target_value_obj:
            break

    if not target_value_obj:
        return None

    raw_pick = str(target_value_obj.get("value"))  # e.g., "Over 28.5"
    odds_val = str(target_value_obj.get("odd"))  # e.g., "1.90"

    # Extract dynamic numerical line (e.g., 28.5 from "Over 28.5")
    line_numbers = re.findall(r"\d+\.?\d*", raw_pick)
    line_num = float(line_numbers[0]) if line_numbers else 0.0

    # Calculate dynamic Expected Stat Output based on match metrics
    stat_multiplier = 1.15
    if pred_data and "comparison" in pred_data:
        comp = pred_data["comparison"]
        att_h = float(comp.get("att", {}).get("home", "50%").replace("%", ""))
        att_a = float(comp.get("att", {}).get("away", "50%").replace("%", ""))
        stat_multiplier = 1.0 + ((att_h + att_a) / 600.0)

    expected_stat = (
        round(line_num * stat_multiplier, 1)
        if line_num > 0
        else round(10.5 * stat_multiplier, 1)
    )

    # Format output pick text clean
    unit = category_name.split()[0].title()
    full_pick_text = (
        raw_pick
        if unit.lower() in raw_pick.lower()
        else f"{raw_pick} {unit}"
    )

    return {
        "pick": full_pick_text,
        "odd": odds_val,
        "expected": expected_stat,
        "unit": unit,
    }


def parse_anchor_market_dynamically(bookmakers, pred_data):
    """Dynamically parse Double Chance or Goals market with live bookmaker odds."""
    for bm in bookmakers:
        for bet in bm.get("bets", []):
            bet_name = bet.get("name", "").lower()

            # Dynamic Double Chance Market
            if "double chance" in bet_name:
                values = bet.get("values", [])
                home_pct = 50.0
                if pred_data and "predictions" in pred_data:
                    pct = pred_data["predictions"].get("percent", {})
                    home_pct = float(pct.get("home", "50%").replace("%", ""))

                pref = "1X" if home_pct >= 50.0 else "X2"
                matched = [
                    v
                    for v in values
                    if pref in str(v.get("value")).upper()
                    or ("Home" in str(v.get("value")) and "Draw" in str(v.get("value")))
                ]
                if matched:
                    v = matched[0]
                    return {
                        "pick": f"Double Chance ({v.get('value')})",
                        "odd": str(v.get("odd")),
                    }

            # Dynamic Goals Market
            if "goals over/under" in bet_name or "total goals" in bet_name:
                over_values = [
                    v
                    for v in bet.get("values", [])
                    if "over 1.5" in str(v.get("value")).lower()
                    or "over 2.5" in str(v.get("value")).lower()
                ]
                if over_values:
                    v = over_values[0]
                    return {
                        "pick": str(v.get("value")),
                        "odd": str(v.get("odd")),
                    }
    return None


def select_verified_picks(fixtures):
    heavy_props = []
    sure_anchors = []
    used_fixture_ids = set()

    # PURE MATCH STAT POOL (Strictly Match Stats)
    stat_categories = [
        ("SHOTS TOWARDS GOAL", ["shot", "shots"]),
        ("CORNERS STAT", ["corner", "corners"]),
        ("CARDS / DISCIPLINE", ["card", "cards", "booking", "bookings"]),
        ("FOULS COMMITTED", ["foul", "fouls"]),
        ("OFFSIDES / THROW-INS", ["offside", "throw"]),
    ]

    # --- 1. GENERATE 5 STRICT DYNAMIC MATCH STAT PROPS ---
    for cat_name, keywords in stat_categories:
        if len(heavy_props) >= 5:
            break

        for fixture in fixtures:
            fixture_id = fixture["fixture"]["id"]
            if fixture_id in used_fixture_ids:
                continue

            bookmakers = get_live_bookmaker_odds(fixture_id)
            if not bookmakers:
                continue

            pred_data = get_fixture_prediction(fixture_id)
            stat_pick = parse_stat_market_dynamically(
                bookmakers, keywords, cat_name, pred_data
            )

            if stat_pick:
                home = fixture["teams"]["home"]["name"]
                away = fixture["teams"]["away"]["name"]
                league = f"{fixture['league']['name']} ({fixture['league']['country']})"

                heavy_props.append(
                    {
                        "category": cat_name,
                        "teams": f"{home} vs {away}",
                        "league": league,
                        "expected": f"~{stat_pick['expected']} {stat_pick['unit']}",
                        "pick": stat_pick["pick"],
                        "odd": stat_pick["odd"],
                    }
                )
                used_fixture_ids.add(fixture_id)
                break

    # --- 2. GENERATE 3 SURE DAILY ANCHORS (DYNAMIC ODDS) ---
    for fixture in fixtures:
        if len(sure_anchors) >= 3:
            break

        fixture_id = fixture["fixture"]["id"]
        if fixture_id in used_fixture_ids:
            continue

        bookmakers = get_live_bookmaker_odds(fixture_id)
        if not bookmakers:
            continue

        pred_data = get_fixture_prediction(fixture_id)
        anchor_data = parse_anchor_market_dynamically(bookmakers, pred_data)

        if anchor_data:
            home = fixture["teams"]["home"]["name"]
            away = fixture["teams"]["away"]["name"]
            league = (
                f"{fixture['league']['name']} ({fixture['league']['country']})"
            )

            sure_anchors.append(
                {
                    "teams": f"{home} vs {away}",
                    "league": league,
                    "pick": anchor_data["pick"],
                    "odd": anchor_data["odd"],
                }
            )
            used_fixture_ids.add(fixture_id)

    return heavy_props, sure_anchors


def send_telegram_post(heavy_props, sure_anchors):
    if not heavy_props and not sure_anchors:
        print("No verified matches available to post today.")
        return

    msg = f"🔥 *STAT-DRIVEN DAILY PREDICTIONS* ({TODAY_DATE})\n"
    msg += "💯 *Live Verified Odds from Bookmakers*\n\n"

    if heavy_props:
        msg += "⚡ *5 HEAVY MATCH STAT PROPS*\n-----------------------------------\n"
        for i, p in enumerate(heavy_props, 1):
            msg += f"*{i}. [{p['category']}]*\n🏆 {p['league']}\n⚔️ {p['teams']}\n📊 *Expected:* {p['expected']}\n🎯 *Pick:* {p['pick']}\n💵 *Odds:* @ {p['odd']}\n\n"

    if sure_anchors:
        msg += "🛡️ *3 SURE DAILY ANCHORS*\n-----------------------------------\n"
        for i, s in enumerate(sure_anchors, 1):
            msg += f"*{i}. {s['teams']}*\n🏆 {s['league']}\n🔒 *Pick:* {s['pick']}\n💵 *Odds:* @ {s['odd']}\n\n"

    msg += "📱 *Join VIP Channel for In-Play Live Value Alerts!*"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    res = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        },
    )
    print("Telegram Post Status:", res.status_code, res.text)
    res.raise_for_status()


if __name__ == "__main__":
    fixtures = get_daily_fixtures()
    heavy, sure = select_verified_picks(fixtures)
    send_telegram_post(heavy, sure)
            
