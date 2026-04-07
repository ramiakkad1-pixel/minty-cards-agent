import os
import time
import threading
import requests
import base64
import urllib.parse
from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ═══ CREDENTIALS ═══
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN",   "8639012891:AAEsPGc6eISuFWVXpi7w3ORba75ha3R4woI")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7922849859")
POKETRACE_KEY     = os.environ.get("POKETRACE_KEY",    "pc_4e02cbc645d9eba1f64a9ab79d4bdb6fd53c63e01414fdfa")
EBAY_APP_ID       = os.environ.get("EBAY_APP_ID",      "RamiAkka-MyAPIKey-PRD-b64ce8038-2ac35fa0")
EBAY_CERT_ID      = os.environ.get("EBAY_CERT_ID",     "PRD-64ce8038323f-12d0-44ed-a58d-5ee5")

# ═══ CONFIG ═══
SINGLES_THRESHOLD = 0.20
SEALED_THRESHOLD  = 0.30
SEALED_MIN_PRICE  = 3.00
REFRESH_MINUTES   = 5
WHATNOT_FEE       = 0.15
SEALED_FEE        = 0.12
BATCH_SIZE        = 10

# ═══ TARGET CARDS ═══
SINGLES_TARGETS = [
    {"name": "Umbreon ex",           "set": "Prismatic Evolutions", "rarity": "SAR", "search": "Umbreon ex Prismatic Evolutions"},
    {"name": "Sylveon ex",           "set": "Prismatic Evolutions", "rarity": "SAR", "search": "Sylveon ex Prismatic Evolutions"},
    {"name": "Eevee ex",             "set": "Prismatic Evolutions", "rarity": "SIR", "search": "Eevee ex Prismatic Evolutions"},
    {"name": "Glaceon ex",           "set": "Prismatic Evolutions", "rarity": "SAR", "search": "Glaceon ex Prismatic Evolutions"},
    {"name": "Espeon ex",            "set": "Prismatic Evolutions", "rarity": "IR",  "search": "Espeon ex Prismatic Evolutions"},
    {"name": "Flareon ex",           "set": "Prismatic Evolutions", "rarity": "IR",  "search": "Flareon ex Prismatic Evolutions"},
    {"name": "Vaporeon ex",          "set": "Prismatic Evolutions", "rarity": "IR",  "search": "Vaporeon ex Prismatic Evolutions"},
    {"name": "Jolteon ex",           "set": "Prismatic Evolutions", "rarity": "IR",  "search": "Jolteon ex Prismatic Evolutions"},
    {"name": "Leafeon ex",           "set": "Prismatic Evolutions", "rarity": "IR",  "search": "Leafeon ex Prismatic Evolutions"},
    {"name": "Charizard ex",         "set": "Paldean Fates",        "rarity": "SAR", "search": "Charizard ex Paldean Fates"},
    {"name": "Meowscarada ex",       "set": "Paldean Fates",        "rarity": "SIR", "search": "Meowscarada ex Paldean Fates"},
    {"name": "Teal Mask Ogerpon ex", "set": "Paldean Fates",        "rarity": "SAR", "search": "Ogerpon ex Paldean Fates"},
    {"name": "Iron Valiant ex",      "set": "Paldean Fates",        "rarity": "SAR", "search": "Iron Valiant ex Paldean Fates"},
    {"name": "Dragapult ex",         "set": "Destined Rivals",      "rarity": "SAR", "search": "Dragapult ex Destined Rivals"},
    {"name": "Miraidon ex",          "set": "Destined Rivals",      "rarity": "SIR", "search": "Miraidon ex Destined Rivals"},
    {"name": "Koraidon ex",          "set": "Destined Rivals",      "rarity": "SAR", "search": "Koraidon ex Destined Rivals"},
    {"name": "Mewtwo ex",            "set": "151",                  "rarity": "SIR", "search": "Mewtwo ex 151 pokemon"},
    {"name": "Mew ex",               "set": "151",                  "rarity": "SAR", "search": "Mew ex 151 pokemon"},
    {"name": "Gengar ex",            "set": "151",                  "rarity": "SAR", "search": "Gengar ex 151 pokemon"},
    {"name": "Blastoise ex",         "set": "151",                  "rarity": "SAR", "search": "Blastoise ex 151 pokemon"},
    {"name": "Venusaur ex",          "set": "151",                  "rarity": "Rainbow", "search": "Venusaur ex 151 rainbow"},
    {"name": "Charizard ex",         "set": "151",                  "rarity": "SAR", "search": "Charizard ex 151 pokemon"},
    {"name": "Pikachu ex",           "set": "Surging Sparks",       "rarity": "SAR", "search": "Pikachu ex Surging Sparks"},
    {"name": "Raichu ex",            "set": "Surging Sparks",       "rarity": "SIR", "search": "Raichu ex Surging Sparks"},
    {"name": "Zapdos ex",            "set": "Surging Sparks",       "rarity": "Rainbow", "search": "Zapdos ex Surging Sparks"},
    {"name": "Stellar Rayquaza ex",  "set": "Stellar Crown",        "rarity": "SAR", "search": "Rayquaza ex Stellar Crown"},
    {"name": "Terapagos ex",         "set": "Stellar Crown",        "rarity": "SIR", "search": "Terapagos ex Stellar Crown"},
    {"name": "Pecharunt ex",         "set": "Stellar Crown",        "rarity": "SAR", "search": "Pecharunt ex Stellar Crown"},
    {"name": "Ogerpon ex",           "set": "Twilight Masquerade",  "rarity": "SAR", "search": "Ogerpon ex Twilight Masquerade"},
    {"name": "Bloodmoon Ursaluna ex","set": "Twilight Masquerade",  "rarity": "SAR", "search": "Ursaluna ex Twilight Masquerade"},
    {"name": "Roaring Moon ex",      "set": "Paradox Rift",         "rarity": "SAR", "search": "Roaring Moon ex Paradox Rift"},
    {"name": "Iron Valiant ex",      "set": "Paradox Rift",         "rarity": "SAR", "search": "Iron Valiant ex Paradox Rift"},
    {"name": "Charizard ex",         "set": "Obsidian Flames",      "rarity": "SAR", "search": "Charizard ex Obsidian Flames"},
    {"name": "Tyranitar ex",         "set": "Obsidian Flames",      "rarity": "SAR", "search": "Tyranitar ex Obsidian Flames"},
    {"name": "Walking Wake ex",      "set": "Temporal Forces",      "rarity": "SAR", "search": "Walking Wake ex Temporal Forces"},
    {"name": "Iron Leaves ex",       "set": "Temporal Forces",      "rarity": "SAR", "search": "Iron Leaves ex Temporal Forces"},
]

SEALED_TARGETS = [
    {"name": "Prismatic Evolutions Booster Box", "type": "Booster Box", "set": "Prismatic Evolutions"},
    {"name": "Prismatic Evolutions ETB",         "type": "ETB",         "set": "Prismatic Evolutions"},
    {"name": "Paldean Fates Booster Box",        "type": "Booster Box", "set": "Paldean Fates"},
    {"name": "Paldean Fates ETB",                "type": "ETB",         "set": "Paldean Fates"},
    {"name": "Destined Rivals Booster Box",      "type": "Booster Box", "set": "Destined Rivals"},
    {"name": "Destined Rivals ETB",              "type": "ETB",         "set": "Destined Rivals"},
    {"name": "151 ETB",                          "type": "ETB",         "set": "151"},
    {"name": "Stellar Crown Booster Box",        "type": "Booster Box", "set": "Stellar Crown"},
    {"name": "Surging Sparks Booster Box",       "type": "Booster Box", "set": "Surging Sparks"},
    {"name": "Obsidian Flames Booster Box",      "type": "Booster Box", "set": "Obsidian Flames"},
]

# ═══ STATE ═══
state = {
    "last_scan": None,
    "deals_found": [],
    "sealed_deals": [],
    "scan_count": 0,
    "total_scanned": 0,
    "alerts_sent": 0,
    "log": [],
    "running": False,
    "batch_index": 0,
}

ebay_token_cache = {"token": None, "expires": 0}
sealed_price_cache = {}

# ═══ LOGGING ═══
def log(level, msg):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    state["log"].append(entry)
    if len(state["log"]) > 500:
        state["log"] = state["log"][-500:]
    print("[" + entry["time"] + "] [" + level + "] " + msg)

# ═══ TELEGRAM ═══
def send_telegram(msg):
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        if resp.status_code == 200:
            state["alerts_sent"] += 1
            log("ALERT", "Telegram sent OK")
        else:
            log("ALERT", "Telegram error: " + resp.text[:80])
    except Exception as e:
        log("ALERT", "Telegram failed: " + str(e)[:50])

# ═══ KEEP ALIVE ═══
def keep_alive():
    while True:
        time.sleep(240)
        try:
            own_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
            requests.get(own_url + "/status", timeout=5)
            log("SYS", "Keep-alive ping OK")
        except Exception:
            pass

# ═══ EBAY OAUTH TOKEN ═══
def get_ebay_token():
    now = time.time()
    if ebay_token_cache["token"] and ebay_token_cache["expires"] > now + 60:
        return ebay_token_cache["token"]

    try:
        credentials = EBAY_APP_ID + ":" + EBAY_CERT_ID
        encoded = base64.b64encode(credentials.encode()).decode()
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": "Basic " + encoded,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope",
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            ebay_token_cache["token"] = data["access_token"]
            ebay_token_cache["expires"] = now + data.get("expires_in", 7200)
            log("SYS", "eBay token refreshed OK")
            return ebay_token_cache["token"]
        else:
            log("SYS", "eBay token error: " + resp.text[:100])
    except Exception as e:
        log("SYS", "eBay token failed: " + str(e)[:50])
    return None

# ═══ EBAY BROWSE API — find cheapest listing ═══
def ebay_find_cheapest(search_query, min_price=0.99):
    token = get_ebay_token()
    if not token:
        return None, None
    try:
        url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
        params = {
            "q": search_query + " pokemon NM",
            "sort": "price",
            "limit": "10",
            "filter": "buyingOptions:{FIXED_PRICE},conditions:{NEW|LIKE_NEW}",
        }
        headers = {
            "Authorization": "Bearer " + token,
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            log("SYS", "eBay Browse error " + str(resp.status_code) + ": " + resp.text[:80])
            return None, None

        data = resp.json()
        items = data.get("itemSummaries", [])

        for item in items:
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            link  = item.get("itemWebUrl", "")
            if price > min_price:
                return price, link

    except Exception as e:
        log("SYS", "eBay Browse failed: " + str(e)[:50])
    return None, None

# ═══ POKETRACE — get market price ═══
def get_card_market_price(search_term):
    try:
        url = "https://api.poketrace.com/v1/cards"
        params = {"search": search_term, "market": "US", "limit": 3}
        headers = {"X-API-Key": POKETRACE_KEY, "Accept": "application/json"}
        resp = requests.get(url, headers=headers, params=params, timeout=10)

        if resp.status_code == 429:
            log("SYS", "PokeTrace rate limit — waiting 60s")
            time.sleep(60)
            return None

        if resp.status_code != 200:
            log("SYS", "PokeTrace error " + str(resp.status_code))
            return None

        cards = resp.json().get("data", [])
        if not cards:
            return None

        prices = cards[0].get("prices", {})
        ebay_avg = prices.get("ebay", {}).get("NEAR_MINT", {}).get("avg", 0)
        tcg_avg  = prices.get("tcgplayer", {}).get("NEAR_MINT", {}).get("avg", 0)

        if ebay_avg > 0 and tcg_avg > 0:
            return round((ebay_avg + tcg_avg) / 2, 2)
        elif ebay_avg > 0:
            return round(ebay_avg, 2)
        elif tcg_avg > 0:
            return round(tcg_avg, 2)
        return None

    except Exception as e:
        log("SYS", "PokeTrace error: " + str(e)[:50])
    return None

# ═══ SINGLES HUNT ═══
def hunt_singles_batch():
    idx   = state["batch_index"]
    batch = SINGLES_TARGETS[idx: idx + BATCH_SIZE]
    state["batch_index"] = 0 if idx + BATCH_SIZE >= len(SINGLES_TARGETS) else idx + BATCH_SIZE

    log("SYS", "Singles batch " + str(idx) + "-" + str(idx + len(batch)) + " of " + str(len(SINGLES_TARGETS)))

    for card in batch:
        if not state["running"]:
            break

        name     = card["name"]
        set_name = card["set"]
        rarity   = card["rarity"]
        search   = card["search"]
        state["total_scanned"] += 1

        log("SCAN", name + " [" + rarity + "] — " + set_name)

        # Step 1: Get market price from PokeTrace
        market = get_card_market_price(search)
        if not market or market < 10:
            log("SYS", "Skip " + name + " — no price or under $10")
            time.sleep(0.5)
            continue

        log("FIND", name + " market: $" + str(market))

        # Step 2: Find cheapest live eBay listing via official API
        cheapest, link = ebay_find_cheapest(search)
        if not cheapest:
            log("SYS", "No eBay listings found for " + name)
            time.sleep(0.5)
            continue

        # Step 3: Check if it's a deal
        discount = (market - cheapest) / market
        if discount >= SINGLES_THRESHOLD:
            pct          = round(discount * 100)
            whatnot_sell = round(market * 1.05, 2)
            net_profit   = round(whatnot_sell * (1 - WHATNOT_FEE) - cheapest, 2)

            deal = {
                "id": name.replace(" ", "-") + "-" + set_name.replace(" ", "-"),
                "name": name,
                "set": set_name,
                "rarity": rarity,
                "platform": "eBay",
                "buyPrice": cheapest,
                "market": market,
                "whatnotSell": whatnot_sell,
                "netProfit": net_profit,
                "pct": pct,
                "link": link,
                "condition": "NM/LP",
                "time": datetime.now().strftime("%H:%M"),
            }

            existing = [d for d in state["deals_found"] if d["id"] != deal["id"]]
            existing.append(deal)
            existing.sort(key=lambda x: x["netProfit"], reverse=True)
            state["deals_found"] = existing[:50]

            log("DEAL", "DEAL: " + name + " @ $" + str(cheapest) + " — " + str(pct) + "% below $" + str(market) + " — profit ~$" + str(net_profit))

            send_telegram(
                "🌿 <b>MINTY CARDS DEAL</b>\n\n"
                "<b>" + name + "</b> [" + rarity + "]\n"
                + set_name + "\n\n"
                "💰 Buy: <b>$" + str(cheapest) + "</b> on eBay\n"
                "📈 Market avg: $" + str(market) + "\n"
                "🏪 Whatnot sell: ~$" + str(whatnot_sell) + "\n"
                "✅ Net profit: ~<b>$" + str(net_profit) + "</b>\n"
                "🔥 " + str(pct) + "% below market\n\n"
                "<a href='" + link + "'>⚡ BUY NOW ON EBAY</a>"
            )
        else:
            log("FIND", name + " cheapest $" + str(cheapest) + " vs market $" + str(market) + " — " + str(round(discount * 100)) + "% below, skip")

        time.sleep(1)

    log("SYS", "Batch complete — " + str(len(state["deals_found"])) + " active deals")

# ═══ SEALED HUNT ═══
def hunt_sealed():
    log("SYS", "Sealed hunt — " + str(len(SEALED_TARGETS)) + " products")
    new_deals = []

    for product in SEALED_TARGETS:
        if not state["running"]:
            break

        name = product["name"]
        log("SCAN", "Sealed: " + name)
        state["total_scanned"] += 1

        if name in sealed_price_cache:
            market = sealed_price_cache[name]
        else:
            market = get_card_market_price(name)
            if market and market > 5:
                sealed_price_cache[name] = market

        if not market or market < 5:
            log("SYS", "No price for " + name)
            time.sleep(0.5)
            continue

        log("FIND", name + " market: $" + str(market))

        cheapest, link = ebay_find_cheapest(name + " sealed", min_price=SEALED_MIN_PRICE)
        if not cheapest or cheapest < SEALED_MIN_PRICE:
            if cheapest:
                log("ALERT", "Bait filtered: " + name + " @ $" + str(cheapest))
            else:
                log("SYS", "No listings for " + name)
            time.sleep(0.5)
            continue

        discount = (market - cheapest) / market
        if discount >= SEALED_THRESHOLD:
            pct        = round(discount * 100)
            net_profit = round(market * (1 - SEALED_FEE) - cheapest, 2)

            deal = {
                "id": "seal-" + name.replace(" ", "-"),
                "name": name,
                "type": product["type"],
                "set": product["set"],
                "platform": "eBay",
                "buyPrice": cheapest,
                "market": market,
                "netProfit": net_profit,
                "pct": pct,
                "link": link,
                "time": datetime.now().strftime("%H:%M"),
            }
            new_deals.append(deal)
            log("DEAL", "SEALED: " + name + " @ $" + str(cheapest) + " — " + str(pct) + "% below $" + str(market))

            send_telegram(
                "📦 <b>MINTY SEALED DEAL</b>\n\n"
                "<b>" + name + "</b>\n"
                + product["set"] + " · " + product["type"] + "\n\n"
                "💰 Buy: <b>$" + str(cheapest) + "</b> on eBay\n"
                "📈 Market avg: $" + str(market) + "\n"
                "✅ Net profit: ~<b>$" + str(net_profit) + "</b>\n"
                "🔥 " + str(pct) + "% below market\n\n"
                "<a href='" + link + "'>⚡ BUY NOW ON EBAY</a>"
            )
        else:
            log("FIND", name + " $" + str(cheapest) + " vs $" + str(market) + " — not enough discount")

        time.sleep(1)

    state["sealed_deals"] = new_deals
    log("SYS", "Sealed complete — " + str(len(new_deals)) + " deals")

# ═══ HUNT LOOP ═══
def run_full_hunt():
    if state["running"]:
        log("SYS", "Already running — skip")
        return
    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("SYS", "=== CYCLE #" + str(state["scan_count"]) + " — PokeTrace + eBay API ===")
    try:
        hunt_singles_batch()
        if state["scan_count"] % 6 == 0:
            hunt_sealed()
    except Exception as e:
        log("SYS", "Hunt error: " + str(e))
    finally:
        state["running"] = False
        log("SYS", "=== CYCLE #" + str(state["scan_count"]) + " COMPLETE ===")

def schedule_loop():
    while True:
        run_full_hunt()
        time.sleep(REFRESH_MINUTES * 60)

# ═══ ROUTES ═══
@app.route("/")
def index():
    return "Minty Cards Agent — PokeTrace + eBay API. /status /deals /log /hunt"

@app.route("/status")
def status():
    return jsonify({
        "running": state["running"],
        "last_scan": state["last_scan"],
        "scan_count": state["scan_count"],
        "total_scanned": state["total_scanned"],
        "singles_deals": len(state["deals_found"]),
        "sealed_deals": len(state["sealed_deals"]),
        "alerts_sent": state["alerts_sent"],
        "card_coverage": str(state["batch_index"]) + "/" + str(len(SINGLES_TARGETS)),
        "refresh_minutes": REFRESH_MINUTES,
        "powered_by": "PokeTrace + eBay Official API",
    })

@app.route("/deals")
def deals():
    return jsonify({"singles": state["deals_found"], "sealed": state["sealed_deals"]})

@app.route("/log")
def get_log():
    return jsonify(state["log"][-100:])

@app.route("/hunt")
def manual_hunt():
    if state["running"]:
        return jsonify({"status": "already running"})
    threading.Thread(target=run_full_hunt, daemon=True).start()
    return jsonify({"status": "hunt started"})

@app.route("/test-telegram")
def test_telegram():
    send_telegram("🌿 <b>Minty Cards Agent</b> — PokeTrace + eBay API live. No more blocking!")
    return jsonify({"status": "sent"})

# ═══ START ═══
log("SYS", "Minty Cards Agent — PokeTrace + official eBay API")
log("SYS", str(len(SINGLES_TARGETS)) + " cards · " + str(BATCH_SIZE) + " per cycle · 5 min · " + str(len(SEALED_TARGETS)) + " sealed every 30 min")
threading.Thread(target=schedule_loop, daemon=True).start()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
