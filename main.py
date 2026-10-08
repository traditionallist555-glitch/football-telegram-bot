import datetime
import os
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Direct 1xBet Public Line Feed API (Soccer / Football = Sport ID 1)
ONEXBET_API_URL = "https://1xbet.com/LineFeed/GetGamesZip?sports=1&typeG=1&mCount=50&lng=en"

# 1xBet Sub-Market Mapping IDs
# 1xBet uses specific Sub-Type IDs (SubId) for detailed props:
# Fouls = 78, Corners = 28, Yellow Cards = 30, Shots on Target = 139, Offsides = 79
MARKET_SUB_TYPES = {
    78: "FOULS",
    28: "CORNERS",
    30: "CARDS",
    139: "SHOTS ON TARGET",
    79: "OFFSIDES"
}

def fetch_1xbet_live_games():
    """Fetch live pre-match fixtures and odds directly from 1xBet feed."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(ONEXBET_API_URL, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("Value", [])
    except Exception as e:
        print(f"Error fetching 1xBet Feed: {e}")
    return []

def parse_1xbet_markets(game):
    """Extract real live odds lines directly from 1xBet game objects without any synthetic estimates."""
    extracted_props = []
    
    home_team = game.get("O1", "Home")
    away_team = game.get("O2", "Away")
    league = game.get("LE", "Soccer League")
    match_name = f"{home_team} vs {away_team}"
    
    # Check all active odds lines (Events)
    events = game.get("E", [])
    for ev in events:
        sub_id = ev.get("GS") # Sub-market ID in 1xBet structure
        param = ev.get("P")   # Line barrier (e.g., 23.5, 2.5, 1.5)
        price = ev.get("C")   # Decimal Odds (e.g., 1.67, 1.37)
        market_type = ev.get("T") # Bet type ID
        
        if not price or not param:
            continue
            
        # Parse Fouls / Corners / Cards Over lines (1xBet Over Type ID = 9 or 11)
        if sub_id in MARKET_SUB_TYPES and market_type in [9, 11]:
            category_name = MARKET_SUB_TYPES[sub_id]
            extracted_props.append({
                "type": "STAT",
                "category": category_name,
                "league": league,
                "teams": match_name,
                "pick": f"Over ({param}) {category_name.capitalize()}",
                "odd": f"{price:.2f}"
            })

        # Parse Double Chance (1X2 / DC Type IDs)
        if market_type == 4: # 1X Double Chance
            extracted_props.append({
                "type": "ANCHOR",
                "league": league,
                "teams": match_name,
                "pick": f"Double Chance (1X)",
                "odd": f"{price:.2f}"
            })
        elif market_type == 6: # X2 Double Chance
            extracted_props.append({
                "type": "ANCHOR",
                "league": league,
                "teams": match_name,
                "pick": f"Double Chance (X2)",
                "odd": f"{price:.2f}"
            })

    return extracted_props

def build_daily_predictions():
    games = fetch_1xbet_live_games()
    if not games:
        print("No games retrieved from 1xBet feed.")
        return [], []

    stat_props = []
    anchors = []
    processed_matches = set()

    for game in games:
        match_id = game.get("I")
        if match_id in processed_matches:
            continue

        props = parse_1xbet_markets(game)
        
        for item in props:
            if item["type"] == "STAT" and len(stat_props) < 7:
                stat_props.append(item)
                processed_matches.add(match_id)
            elif item["type"] == "ANCHOR" and len(anchors) < 3 and match_id not in processed_matches:
                anchors.append(item)
                processed_matches.add(match_id)

            if len(stat_props) >= 7 and len(anchors) >= 3:
                break

    return stat_props, anchors

def send_telegram_post(stat_props, anchors):
    if not stat_props and not anchors:
        print("No live 1xBet odds retrieved.")
        return

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = f"🔥 *1XBET REAL-TIME STAT PREDICTIONS* ({today_str})\n"
    msg += "💯 *Direct Live Bookmaker Feed*\n\n"

    if stat_props:
        msg += f"⚡ *7 HEAVY MATCH STAT PROPS*\n-----------------------------------\n"
        for i, p in enumerate(stat_props, 1):
            msg += f"*{i}. [{p['category']}]*\n🏆 {p['league']}\n⚔️ {p['teams']}\n🎯 *Pick:* {p['pick']}\n💵 *Odds:* @ {p['odd']}\n\n"

    if anchors:
        msg += f"🛡️ *3 SURE DAILY ANCHORS*\n-----------------------------------\n"
        for i, a in enumerate(anchors, 1):
            msg += f"*{i}. {a['teams']}*\n🏆 {a['league']}\n🔒 *Pick:* {a['pick']}\n💵 *Odds:* @ {a['odd']}\n\n"

    msg += "📱 *Join Telegram VIP Channel for In-Play Live Value Alerts!*"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    res = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    print("Telegram Status:", res.status_code)

if __name__ == "__main__":
    stats, anchors = build_daily_predictions()
    send_telegram_post(stats, anchors)
    
