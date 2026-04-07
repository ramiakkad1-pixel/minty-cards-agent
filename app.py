import os
import time
import threading
import requests
import traceback
from flask import Flask, jsonify
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# MINTY CARDS ARBITRAGE AGENT v3.0
# Uses pokemontcg.io API → real TCGPlayer market prices
# No scraping. No eBay. No PokeTrace. No blocking. Ever.
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__)

# ── Config ──
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
POKEMONTCG_KEY   = os.environ.get("POKEMONTCG_KEY", "")  # optional, higher rate limits
THRESHOLD        = float(os.environ.get("THRESHOLD", "0.20"))  # 20% below market
REFRESH_MINUTES  = int(os.environ.get("REFRESH_MINUTES", "10"))
WHATNOT_FEE      = 0.15
REQUEST_TIMEOUT  = 15  # seconds per API call

# ── Card targets ──
# Each card has a pokemontcg.io search query and card_id if known
# The API returns TCGPlayer market prices for every card
TARGETS = [
    # Prismatic Evolutions
    {"name": "Umbreon ex",    "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Umbreon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Sylveon ex",    "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Sylveon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Eevee ex",      "set": "Prismatic Evolutions", "rarity": "SIR", "q": 'name:"Eevee ex" set.name:"Prismatic Evolutions"'},
    {"name": "Glaceon ex",    "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Glaceon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Espeon ex",     "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Espeon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Flareon ex",    "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Flareon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Vaporeon ex",   "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Vaporeon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Jolteon ex",    "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Jolteon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Leafeon ex",    "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Leafeon ex" set.name:"Prismatic Evolutions"'},
    # Paldean Fates
    {"name": "Charizard ex",  "set": "Paldean Fates",        "rarity": "SAR", "q": 'name:"Charizard ex" set.name:"Paldean Fates"'},
    {"name": "Mew ex",        "set": "Paldean Fates",        "rarity": "SIR", "q": 'name:"Mew ex" set.name:"Paldean Fates"'},
    {"name": "Mimikyu ex",    "set": "Paldean Fates",        "rarity": "SAR", "q": 'name:"Mimikyu ex" set.name:"Paldean Fates"'},
    # 151
    {"name": "Charizard ex",  "set": "151",                  "rarity": "SAR", "q": 'name:"Charizard ex" set.name:"151"'},
    {"name": "Mewtwo ex",     "set": "151",                  "rarity": "SIR", "q": 'name:"Mewtwo ex" set.name:"151"'},
    {"name": "Mew ex",        "set": "151",                  "rarity": "SAR", "q": 'name:"Mew ex" set.name:"151"'},
    {"name": "Alakazam ex",   "set": "151",                  "rarity": "SIR", "q": 'name:"Alakazam ex" set.name:"151"'},
    # Destined Rivals
    {"name": "Mewtwo ex",     "set": "Destined Rivals",      "rarity": "SAR", "q": 'name:"Mewtwo ex" set.name:"Destined Rivals"'},
    {"name": "Giovanni",      "set": "Destined Rivals",      "rarity": "SAR", "q": 'name:"Giovanni" set.name:"Destined Rivals"'},
    {"name": "Dragapult ex",  "set": "Destined Rivals",      "rarity": "SAR", "q": 'name:"Dragapult ex" set.name:"Destined Rivals"'},
    # Surging Sparks
    {"name": "Pikachu ex",    "set": "Surging Sparks",       "rarity": "SAR", "q": 'name:"Pikachu ex" set.name:"Surging Sparks"'},
    {"name": "Arceus ex",     "set": "Surging Sparks",       "rarity": "SIR", "q": 'name:"Arceus ex" set.name:"Surging Sparks"'},
    # Stellar Crown
    {"name": "Terapagos ex",  "set": "Stellar Crown",        "rarity": "SIR", "q": 'name:"Terapagos ex" set.name:"Stellar Crown"'},
    # Twilight Masquerade
    {"name": "Bloodmoon Ursaluna ex", "set": "Twilight Masquerade", "rarity": "SIR", "q": 'name:"Bloodmoon Ursaluna ex" set.name:"Twilight Masquerade"'},
    # Obsidian Flames
    {"name": "Charizard ex",  "set": "Obsidian Flames",      "rarity": "SIR", "q": 'name:"Charizard ex" set.name:"Obsidian Flames"'},
]

# ── State ──
state = {
    "running": False,
    "last_scan": "never",
    "scan_count": 0,
    "total_cards_checked": 0,
    "deals_found": [],
    "all_prices": [],
    "alerts_sent": 0,
    "errors": [],
    "log": [],
}

# ═══ LOGGING ═══
def log(tag, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "tag": tag, "msg": msg}
    state["log"].append(entry)
    if len(state["log"]) > 200:
        state["log"] = state["log"][-200:]
    print(f"[{ts}] [{tag}] {msg}")


# ═══ TELEGRAM ═══
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("TG", "Telegram not configured — skipping alert")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code == 200:
            log("TG", "Alert sent!")
            return True
        else:
            log("TG", f"Failed: {resp.status_code} — {resp.text[:100]}")
            return False
    except Exception as e:
        log("TG", f"Error: {str(e)}")
        return False


# ═══ PRICE FETCHING — pokemontcg.io API ═══
def get_tcg_price(card):
    """
    Calls pokemontcg.io API to get TCGPlayer market prices.
    Returns dict with market_price, low_price, tcgplayer_url, or None on failure.
    """
    try:
        headers = {"Content-Type": "application/json"}
        if POKEMONTCG_KEY:
            headers["X-Api-Key"] = POKEMONTCG_KEY

        url = "https://api.pokemontcg.io/v2/cards"
        params = {"q": card["q"], "pageSize": 5}

        resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 429:
            log("API", f"Rate limited — waiting 30s")
            time.sleep(30)
            return None

        if resp.status_code != 200:
            log("API", f"HTTP {resp.status_code} for {card['name']} — {resp.text[:80]}")
            return None

        data = resp.json()
        cards = data.get("data", [])

        if not cards:
            log("API", f"No results for {card['name']} [{card['set']}]")
            return None

        # Find the best match — prefer the one with highest rarity / prices
        best = None
        best_price = 0

        for c in cards:
            tcg = c.get("tcgplayer", {})
            prices = tcg.get("prices", {})
            tcg_url = tcg.get("url", "")

            # Try all price types: holofoil, reverseHolofoil, normal, 1stEditionHolofoil
            for price_type in ["holofoil", "reverseHolofoil", "normal", "1stEditionHolofoil", "unlimitedHolofoil"]:
                p = prices.get(price_type, {})
                market = p.get("market", 0) or 0
                low = p.get("low", 0) or 0
                mid = p.get("mid", 0) or 0

                if market > best_price:
                    best_price = market
                    best = {
                        "market_price": round(market, 2),
                        "low_price": round(low, 2),
                        "mid_price": round(mid, 2),
                        "tcgplayer_url": tcg_url,
                        "card_id": c.get("id", ""),
                        "card_name": c.get("name", card["name"]),
                        "set_name": c.get("set", {}).get("name", card["set"]),
                        "rarity": c.get("rarity", card.get("rarity", "")),
                        "image": c.get("images", {}).get("small", ""),
                        "price_type": price_type,
                    }

        if best and best["market_price"] > 0:
            return best
        else:
            log("API", f"No price data for {card['name']} [{card['set']}]")
            return None

    except requests.exceptions.Timeout:
        log("API", f"Timeout for {card['name']} — skipping")
        return None
    except requests.exceptions.ConnectionError as e:
        log("API", f"Connection error for {card['name']}: {str(e)[:80]}")
        return None
    except Exception as e:
        log("API", f"Error for {card['name']}: {str(e)[:80]}")
        return None


# ═══ DEAL DETECTION ═══
def check_for_deals(card, price_data):
    """
    Check if the low price represents a deal (significantly below market).
    If low is X% below market → that's a snipe opportunity.
    """
    market = price_data["market_price"]
    low = price_data["low_price"]

    if market <= 0 or low <= 0:
        return None

    discount_pct = (market - low) / market

    if discount_pct >= THRESHOLD:
        # Calculate Whatnot arb profit
        sell_price = market  # sell at market on Whatnot
        whatnot_fee = sell_price * WHATNOT_FEE
        net_profit = round(sell_price - whatnot_fee - low, 2)
        discount_display = round(discount_pct * 100, 1)

        deal = {
            "card": card["name"],
            "set": card["set"],
            "rarity": card.get("rarity", ""),
            "market_price": market,
            "low_price": low,
            "discount_pct": discount_display,
            "net_profit": net_profit,
            "tcgplayer_url": price_data.get("tcgplayer_url", ""),
            "image": price_data.get("image", ""),
            "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return deal

    return None


# ═══ HUNT CYCLE ═══
def run_hunt():
    if state["running"]:
        log("SYS", "Already running — skip")
        return

    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cycle = state["scan_count"]

    log("SYS", f"═══ CYCLE #{cycle} — scanning {len(TARGETS)} cards ═══")

    new_deals = []
    new_prices = []
    cards_checked = 0
    errors = 0

    for i, card in enumerate(TARGETS):
        try:
            log("SCAN", f"[{i+1}/{len(TARGETS)}] {card['name']} [{card['rarity']}] — {card['set']}")

            price_data = get_tcg_price(card)

            if price_data is None:
                errors += 1
                log("SCAN", f"  → No price data (error)")
                # Small delay even on error to be nice to API
                time.sleep(1)
                continue

            cards_checked += 1
            state["total_cards_checked"] += 1

            log("PRICE", f"  → Market: ${price_data['market_price']} | Low: ${price_data['low_price']} | Mid: ${price_data['mid_price']}")

            # Store price snapshot
            new_prices.append({
                "card": card["name"],
                "set": card["set"],
                "rarity": card.get("rarity", ""),
                "market": price_data["market_price"],
                "low": price_data["low_price"],
                "tcgplayer_url": price_data.get("tcgplayer_url", ""),
            })

            # Check for deal
            deal = check_for_deals(card, price_data)
            if deal:
                new_deals.append(deal)
                log("DEAL", f"  🔥 DEAL! {deal['card']} — ${deal['low_price']} ({deal['discount_pct']}% below market ${deal['market_price']})")

                # Send Telegram alert
                alert_text = (
                    f"🔥 <b>DEAL FOUND</b>\n\n"
                    f"<b>{deal['card']}</b> [{deal['rarity']}]\n"
                    f"📦 {deal['set']}\n\n"
                    f"💰 TCGPlayer Low: <b>${deal['low_price']}</b>\n"
                    f"📈 Market Price: ${deal['market_price']}\n"
                    f"🏷️ {deal['discount_pct']}% below market\n\n"
                    f"💵 Whatnot Arb Profit: ~<b>${deal['net_profit']}</b>\n"
                    f"  (sell at ${deal['market_price']} - 15% fee - ${deal['low_price']} cost)\n\n"
                )
                if deal.get("tcgplayer_url"):
                    alert_text += f"<a href=\"{deal['tcgplayer_url']}\">⚡ BUY ON TCGPLAYER</a>"

                if send_telegram(alert_text):
                    state["alerts_sent"] += 1
            else:
                log("SCAN", f"  → No deal (low is not {int(THRESHOLD*100)}%+ below market)")

            # Rate limit: 1 request per 2 seconds (safe for no-key tier: 30/min)
            time.sleep(2)

        except Exception as e:
            errors += 1
            log("ERR", f"Error on {card['name']}: {str(e)[:100]}")
            state["errors"].append({"card": card["name"], "error": str(e)[:200], "time": datetime.now().strftime("%H:%M:%S")})
            if len(state["errors"]) > 50:
                state["errors"] = state["errors"][-50:]
            time.sleep(2)

    state["deals_found"] = new_deals
    state["all_prices"] = new_prices
    state["running"] = False

    log("SYS", f"═══ CYCLE #{cycle} COMPLETE — {cards_checked} checked, {errors} errors, {len(new_deals)} deals ═══")


# ═══ SCHEDULER ═══
def schedule_loop():
    # Small startup delay to let Flask start
    time.sleep(5)
    while True:
        try:
            run_hunt()
        except Exception as e:
            log("SYS", f"Schedule error: {str(e)[:100]}")
            state["running"] = False
        log("SYS", f"Next scan in {REFRESH_MINUTES} minutes...")
        time.sleep(REFRESH_MINUTES * 60)


# ═══ KEEP ALIVE (pings self to prevent Render sleep) ═══
def keep_alive():
    time.sleep(60)
    while True:
        try:
            requests.get("https://minty-cards-agent.onrender.com/ping", timeout=5)
        except:
            pass
        time.sleep(300)  # every 5 min


# ═══ ROUTES ═══
@app.route("/")
def index():
    return jsonify({
        "name": "Minty Cards Arbitrage Agent v3.0",
        "status": "running" if state["running"] else "idle",
        "endpoints": ["/status", "/prices", "/deals", "/log", "/hunt", "/test-telegram", "/ping"],
        "powered_by": "pokemontcg.io API → TCGPlayer market prices",
        "source": "No scraping. No eBay. No PokeTrace. Clean API only.",
    })

@app.route("/ping")
def ping():
    return "pong"

@app.route("/status")
def get_status():
    return jsonify({
        "running": state["running"],
        "last_scan": state["last_scan"],
        "scan_count": state["scan_count"],
        "total_cards_checked": state["total_cards_checked"],
        "current_deals": len(state["deals_found"]),
        "total_alerts_sent": state["alerts_sent"],
        "recent_errors": len(state["errors"]),
        "cards_tracked": len(TARGETS),
        "refresh_minutes": REFRESH_MINUTES,
        "threshold": f"{int(THRESHOLD*100)}% below market",
        "powered_by": "pokemontcg.io → TCGPlayer prices",
    })

@app.route("/prices")
def get_prices():
    return jsonify({
        "last_scan": state["last_scan"],
        "count": len(state["all_prices"]),
        "prices": state["all_prices"],
    })

@app.route("/deals")
def get_deals():
    return jsonify({
        "last_scan": state["last_scan"],
        "count": len(state["deals_found"]),
        "deals": state["deals_found"],
    })

@app.route("/log")
def get_log():
    return jsonify(state["log"][-100:])

@app.route("/errors")
def get_errors():
    return jsonify(state["errors"][-50:])

@app.route("/hunt")
def manual_hunt():
    if state["running"]:
        return jsonify({"status": "already running — check /log"})
    threading.Thread(target=run_hunt, daemon=True).start()
    return jsonify({"status": "hunt started — check /log in 60 seconds"})

@app.route("/test-telegram")
def test_telegram():
    ok = send_telegram(
        "🌿 <b>Minty Cards Agent v3.0</b>\n\n"
        "✅ Telegram connected!\n"
        f"📊 Tracking {len(TARGETS)} cards\n"
        f"⏱️ Scanning every {REFRESH_MINUTES} min\n"
        f"🎯 Alert threshold: {int(THRESHOLD*100)}% below market\n\n"
        "Powered by pokemontcg.io → TCGPlayer prices"
    )
    return jsonify({"status": "sent" if ok else "failed — check /log"})


# ═══ STARTUP ═══
log("SYS", "═══ Minty Cards Agent v3.0 starting ═══")
log("SYS", f"Tracking {len(TARGETS)} cards")
log("SYS", f"Threshold: {int(THRESHOLD*100)}% below TCGPlayer market")
log("SYS", f"Refresh: every {REFRESH_MINUTES} minutes")
log("SYS", f"Telegram: {'configured' if TELEGRAM_TOKEN else 'NOT SET — add TELEGRAM_TOKEN env var'}")
log("SYS", f"API key: {'set (higher limits)' if POKEMONTCG_KEY else 'not set (using free tier — 30 req/min)'}")
log("SYS", "Data source: pokemontcg.io → real TCGPlayer market prices")
log("SYS", "No scraping. No eBay. No PokeTrace. Clean API calls only.")

# Start background threads
threading.Thread(target=schedule_loop, daemon=True).start()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
