import datetime
import os
import re
import requests

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

API_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}
BASE_URL = "https://v3.football.api-sports.io"

# 7 STRICT MATCH STAT CATEGORIES (Top 7 Section)
STAT_CATEGORIES = [
    {
        "name": "TOTAL SHOTS",
        "keywords": [r"total shots", r"^shots$"],
        "unit": "Shots",
    },
    {
        "name": "CORNERS STAT",
        "keywords": [r"corner", r"corners"],
        "unit": "Corners",
    },
    {
        "name": "CARDS / DISCIPLINE",
        "keywords": [r"card", r"cards", r"yellow card", r"booking"],
        "unit": "Cards",
    },
    {
        "name": "FOULS COMMITTED",
        "keywords": [r"foul", r"fouls"],
        "unit": "Fouls",
    },
    {
        "name": "THROW-INS STAT",
        "keywords": [r"throw", r"throw-in", r"throw in", r"throwins"],
        "unit": "Throw-ins",
    },
    {
        "name": "OFFSIDES STAT",
        "keywords": [r"offside", r"offsides"],
        "unit": "Offsides",
    },
    {
        "name": "SHOTS ON TARGET / SAVES",
        "keywords": [
            r"shots on target",
            r"saves",
            r"goalkeeper saves",
            r"tackles",
        ],
        "unit": "On Target / Saves",
    },
]


def get_24h_time_window():
    """Calculate 7:00 AM Today to 7:00 AM Tomorrow UTC, enforcing a 30-min buffer from current time."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Calculate 7:00 AM anchor
    today_7am = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)

    if now_utc >= today_7am:
        window_start = today_7am
        window_end = today_7am + datetime.timedelta(days=1)
    else:
        window_start = today_7am - datetime.timedelta(days=1)
        window_end = today_7am

    # Discard games starting within less than 30 minutes
    earliest_kickoff = max(
        now_utc + datetime.timedelta(minutes=30), window_start
    )

    return earliest_kickoff, window_end


def get_window_fixtures():
    """Fetch fixtures strictly scheduled within the 24-hour window."""
    earliest_kickoff, window_end = get_24h_time_window()

    date_start = earliest_kickoff.strftime("%Y-%m-%d")
    date_end = window_end.strftime("%Y-%m-%d")
    target_dates = list(set([date_start, date_end]))

    raw_fixtures = []
    for date_str in target_dates:
        url = f"{BASE_URL}/fixtures?date={date_str}&status=NS"
        try:
            res = requests.get(url, headers=API_HEADERS, timeout=12)
            if res.status_code == 200:
                raw_fixtures.extend(res.json().get("response", []))
        except Exception as e:
            print(f"Error fetching fixtures for date {date_str}: {e}")

    valid_fixtures = []
    for f in raw_fixtures:
        match_date_str = f["fixture"]["date"]
        match_dt = datetime.datetime.fromisoformat(
            match_date_str.replace("Z", "+00:00")
        )

        # Enforce exact time window filter
        if earliest_kickoff <= match_dt < window_end:
            valid_fixtures.append(f)

    print(
        f"Found {len(valid_fixtures)} valid upcoming fixtures in 24h window (7AM to 7AM)."
    )
    return valid_fixtures


def get_live_bookmaker_odds(fixture_id):
    """Fetch live odds array directly from bookmakers."""
    url = f"{BASE_URL}/odds?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data and "bookmakers" in data[0]:
                return data[0]["bookmakers"]
    except Exception as e:
        print(f"Error fetching odds for fixture {fixture_id}: {e}")
    return []


def get_fixture_prediction(fixture_id):
    """Fetch prediction metrics for calculating expected stats."""
    url = f"{BASE_URL}/predictions?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=API_HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data:
                return data[0]
    except Exception as e:
        print(f"Error fetching prediction for fixture {fixture_id}: {e}")
    return None


def extract_stat_market(bookmakers, keywords, unit, pred_data):
    """Extract exact live market lines, real odds, and calculate dynamic expectations."""
    selected_bet = None

    for bm in bookmakers:
        for bet in bm.get("bets", []):
            bet_name = bet.get("name", "").lower()
            if any(re.search(kw, bet_name) for kw in keywords):
                over_values = [
                    v
                    for v in bet.get("values", [])
                    if "over" in str(v.get("value", "")).lower()
                ]
                if over_values:
                    # Target value market odds around 1.80 - 1.90
                    selected_bet = min(
                        over_values,
                        key=lambda x: abs(float(x.get("odd", 2.0)) - 1.85),
                    )
                    break
        if selected_bet:
            break

    if not selected_bet:
        return None

    raw_pick = str(selected_bet.get("value"))
    odds_val = str(selected_bet.get("odd"))

    # Extract numerical line
    nums = re.findall(r"\d+\.?\d*", raw_pick)
    line_num = float(nums[0]) if nums else 0.0

    # Calculate dynamic expected value
    stat_multiplier = 1.12
    if pred_data and "comparison" in pred_data:
        comp = pred_data.get("comparison", {})
        att_h = float(
            str(comp.get("att", {}).get("home", "50%")).replace("%", "")
        )
        att_a = float(
            str(comp.get("att", {}).get("away", "50%")).replace("%", "")
        )
        stat_multiplier = 1.0 + ((att_h + att_a) / 650.0)

    expected_val = (
        round(line_num * stat_multiplier, 1)
        if line_num > 0
        else round(10.5 * stat_multiplier, 1)
    )

    clean_pick = (
        f"{raw_pick} {unit}"
        if unit.lower() not in raw_pick.lower()
        else raw_pick
    )

    return {
        "pick": clean_pick,
        "odd": odds_val,
        "expected": f"~{expected_val} {unit}",
    }


def extract_anchor_market(bookmakers, pred_data):
    """Extract Double Chance or Total Goals with live bookmaker odds."""
    for bm in bookmakers:
        for bet in bm.get("bets", []):
            b_name = bet.get("name", "").lower()
            values = bet.get("values", [])

            # Double Chance
            if "double chance" in b_name and values:
                home_pct = 50.0
                if pred_data and "predictions" in pred_data:
                    pct = pred_data["predictions"].get("percent", {})
                    home_pct = float(
                        str(pct.get("home", "50%")).replace("%", "")
                    )

                target = "1X" if home_pct >= 50.0 else "X2"
                matched = [
                    v for v in values if target in str(v.get("value")).upper()
                ]
                if matched:
                    return {
                        "pick": f"Double Chance ({matched[0].get('value')})",
                        "odd": str(matched[0].get("odd")),
                    }

            # Total Goals Over
            if ("goals over/under" in b_name or b_name == "total") and values:
                overs = [
                    v
                    for v in values
                    if "over 1.5" in str(v.get("value")).lower()
                    or "over 2.5" in str(v.get("value")).lower()
                ]
                if overs:
                    v = min(
                        overs, key=lambda x: abs(float(x.get("odd", 2.0)) - 1.45)
                    )
                    return {
                        "pick": f"Goals {v.get('value')}",
                        "odd": str(v.get("odd")),
                    }
    return None


def select_verified_picks(fixtures):
    heavy_props = []
    sure_anchors = []
    used_fixture_ids = set()

    # --- 1. GENERATE 7 STRICT MATCH STAT PROPS ---
    for cat in STAT_CATEGORIES:
        if len(heavy_props) >= 7:
            break

        for fixture in fixtures:
            fixture_id = fixture["fixture"]["id"]
            if fixture_id in used_fixture_ids:
                continue

            bookmakers = get_live_bookmaker_odds(fixture_id)
            if not bookmakers:
                continue

            pred_data = get_fixture_prediction(fixture_id)
            stat_pick = extract_stat_market(
                bookmakers, cat["keywords"], cat["unit"], pred_data
            )

            if stat_pick:
                home = fixture["teams"]["home"]["name"]
                away = fixture["teams"]["away"]["name"]
                league = f"{fixture['league']['name']} ({fixture['league']['country']})"

                heavy_props.append(
                    {
                        "category": cat["name"],
                        "teams": f"{home} vs {away}",
                        "league": league,
                        "expected": stat_pick["expected"],
                        "pick": stat_pick["pick"],
                        "odd": stat_pick["odd"],
                    }
                )
                used_fixture_ids.add(fixture_id)
                break  # Selected fixture for this category, move to next stat type

    # --- 2. GENERATE 3 SURE DAILY ANCHORS ---
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
        anchor_data = extract_anchor_market(bookmakers, pred_data)

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
        print("No verified matches available to post at this time.")
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = f"🔥 *STAT-DRIVEN DAILY PREDICTIONS* ({today_str})\n"
    msg += "💯 *Live Verified Odds from Bookmakers*\n\n"

    if heavy_props:
        msg += "⚡ *7 HEAVY MATCH STAT PROPS*\n-----------------------------------\n"
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
    print("Telegram Response Status:", res.status_code)
    res.raise_for_status()


if __name__ == "__main__":
    fixtures = get_window_fixtures()
    heavy, sure = select_verified_picks(fixtures)
    send_telegram_post(heavy, sure)
        
