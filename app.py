import os
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8639012891:AAEsPGc6eISuFWVXpi7w3ORba75ha3R4woI")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7922849859")
SINGLES_THRESHOLD = 0.20
SEALED_THRESHOLD  = 0.30
SEALED_MIN_PRICE  = 3.00
REFRESH_MINUTES   = 5
WHATNOT_FEE       = 0.15
SEALED_FEE        = 0.12

# All SAR/SIR/IR/Rainbow cards with estimated market $10+
# Rotates through in batches of 10 per cycle so each cycle stays under 5 min
SINGLES_TARGETS = [
    # Prismatic Evolutions
    {"name": "Umbreon ex",          "set": "Prismatic Evolutions", "rarity": "SAR"},
    {"name": "Sylveon ex",          "set": "Prismatic Evolutions", "rarity": "SAR"},
    {"name": "Eevee ex",            "set": "Prismatic Evolutions", "rarity": "SIR"},
    {"name": "Glaceon ex",          "set": "Prismatic Evolutions", "rarity": "SAR"},
    {"name": "Espeon ex",           "set": "Prismatic Evolutions", "rarity": "IR"},
    {"name": "Flareon ex",          "set": "Prismatic Evolutions", "rarity": "IR"},
    {"name": "Vaporeon ex",         "set": "Prismatic Evolutions", "rarity": "IR"},
    {"name": "Jolteon ex",          "set": "Prismatic Evolutions", "rarity": "IR"},
    {"name": "Leafeon ex",          "set": "Prismatic Evolutions", "rarity": "IR"},
    {"name": "Umbreon ex",          "set": "Prismatic Evolutions", "rarity": "SIR"},
    # Paldean Fates
    {"name": "Charizard ex",        "set": "Paldean Fates",        "rarity": "SAR"},
    {"name": "Meowscarada ex",      "set": "Paldean Fates",        "rarity": "SIR"},
    {"name": "Teal Mask Ogerpon ex","set": "Paldean Fates",        "rarity": "SAR"},
    {"name": "Iron Valiant ex",     "set": "Paldean Fates",        "rarity": "SAR"},
    {"name": "Skeledirge ex",       "set": "Paldean Fates",        "rarity": "SAR"},
    {"name": "Quaquaval ex",        "set": "Paldean Fates",        "rarity": "SAR"},
    # Destined Rivals
    {"name": "Dragapult ex",        "set": "Destined Rivals",      "rarity": "SAR"},
    {"name": "Miraidon ex",         "set": "Destined Rivals",      "rarity": "SIR"},
    {"name": "Koraidon ex",         "set": "Destined Rivals",      "rarity": "SAR"},
    {"name": "Flutter Mane ex",     "set": "Destined Rivals",      "rarity": "Rainbow"},
    {"name": "Tera Staraptor ex",   "set": "Destined Rivals",      "rarity": "IR"},
    {"name": "Lono",                "set": "Destined Rivals",      "rarity": "SAR"},
    # 151
    {"name": "Mewtwo ex",           "set": "151",                  "rarity": "SIR"},
    {"name": "Mew ex",              "set": "151",                  "rarity": "SAR"},
    {"name": "Gengar ex",           "set": "151",                  "rarity": "SAR"},
    {"name": "Blastoise ex",        "set": "151",                  "rarity": "SAR"},
    {"name": "Venusaur ex",         "set": "151",                  "rarity": "Rainbow"},
    {"name": "Charizard ex",        "set": "151",                  "rarity": "SAR"},
    {"name": "Alakazam ex",         "set": "151",                  "rarity": "SAR"},
    # Surging Sparks
    {"name": "Pikachu ex",          "set": "Surging Sparks",       "rarity": "SAR"},
    {"name": "Raichu ex",           "set": "Surging Sparks",       "rarity": "SIR"},
    {"name": "Zapdos ex",           "set": "Surging Sparks",       "rarity": "Rainbow"},
    {"name": "Tera Staraptor ex",   "set": "Surging Sparks",       "rarity": "SAR"},
    {"name": "Iron Hands ex",       "set": "Surging Sparks",       "rarity": "SAR"},
    # Stellar Crown
    {"name": "Stellar Rayquaza ex", "set": "Stellar Crown",        "rarity": "SAR"},
    {"name": "Terapagos ex",        "set": "Stellar Crown",        "rarity": "SIR"},
    {"name": "Pecharunt ex",        "set": "Stellar Crown",        "rarity": "SAR"},
    {"name": "Archaludon ex",       "set": "Stellar Crown",        "rarity": "Rainbow"},
    # Twilight Masquerade
    {"name": "Ogerpon ex",          "set": "Twilight Masquerade",  "rarity": "SAR"},
    {"name": "Munkidori ex",        "set": "Twilight Masquerade",  "rarity": "SAR"},
    {"name": "Bloodmoon Ursaluna ex","set": "Twilight Masquerade", "rarity": "SAR"},
    # Paradox Rift
    {"name": "Roaring Moon ex",     "set": "Paradox Rift",         "rarity": "SAR"},
    {"name": "Iron Valiant ex",     "set": "Paradox Rift",         "rarity": "SAR"},
    {"name": "Garchomp ex",         "set": "Paradox Rift",         "rarity": "SAR"},
    # Obsidian Flames
    {"name": "Charizard ex",        "set": "Obsidian Flames",      "rarity": "SAR"},
    {"name": "Tyranitar ex",        "set": "Obsidian Flames",      "rarity": "SAR"},
    {"name": "Dragonite ex",        "set": "Obsidian Flames",      "rarity": "SAR"},
    # Temporal Forces
    {"name": "Walking Wake ex",     "set": "Temporal Forces",      "rarity": "SAR"},
    {"name": "Iron Leaves ex",      "set": "Temporal Forces",      "rarity": "SAR"},
]

SEALED_TARGETS = [
    {"name": "Prismatic Evolutions Booster Box", "type": "Booster Box", "set": "Prismatic Evolutions"},
    {"name": "Prismatic Evolutions ETB",         "type": "ETB",         "set": "Prismatic Evolutions"},
    {"name": "Paldean Fates Booster Box",        "type": "Booster Box", "set": "Paldean Fates"},
    {"name": "Paldean Fates ETB",                "type": "ETB",         "set": "Paldean Fates"},
    {"name": "Destined Rivals Booster Box",      "type": "Booster Box", "set": "Destined Rivals"},
    {"name": "Destined Rivals ETB",              "type": "ETB",         "set": "Destined Rivals"},
    {"name": "151 ETB",                          "type": "ETB",         "set": "151"},
    {"name": "151 Booster Bundle",               "type": "Booster Bundle","set": "151"},
    {"name": "Stellar Crown Booster Box",        "type": "Booster Box", "set": "Stellar Crown"},
    {"name": "Surging Sparks Booster Box",       "type": "Booster Box", "set": "Surging Sparks"},
    {"name": "Obsidian Flames Booster Box",      "type": "Booster Box", "set": "Obsidian Flames"},
    {"name": "Paradox Rift Booster Box",         "type": "Booster Box", "set": "Paradox Rift"},
]

BATCH_SIZE = 10  # cards per 5-min cycle

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def log(level, msg):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    state["log"].append(entry)
    if len(state["log"]) > 500:
        state["log"] = state["log"][-500:]
    print("[" + entry["time"] + "] [" + level + "] " + msg)

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

def keep_alive():
    while True:
        time.sleep(240)
        try:
            own_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
            requests.get(own_url + "/status", timeout=5)
            log("SYS", "Keep-alive ping OK")
        except Exception:
            pass

def ebay_sold_median(query):
    try:
        url = "https://www.ebay.com/sch/i.html?_nkw=" + requests.utils.quote(query) + "&LH_Sold=1&LH_Complete=1&_sop=13"
        resp = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        prices = []
        for el in soup.select(".s-item__price"):
            raw = el.get_text().replace("$", "").replace(",", "").strip()
            try:
                if " to " in raw:
                    parts = raw.split(" to ")
                    prices.append((float(parts[0]) + float(parts[1])) / 2)
                else:
                    prices.append(float(raw))
            except Exception:
                pass
        if prices:
            prices = sorted(prices[:12])
            return prices[len(prices) // 2]
    except Exception as e:
        log("SYS", "eBay sold error: " + str(e)[:50])
    return None

def ebay_cheapest_bin(query, min_price=0.99):
    try:
        url = "https://www.ebay.com/sch/i.html?_nkw=" + requests.utils.quote(query) + "&LH_BIN=1&_sop=15"
        resp = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".s-item")[:25]:
            price_el = item.select_one(".s-item__price")
            link_el  = item.select_one(".s-item__link")
            if price_el and link_el:
                raw = price_el.get_text().replace("$", "").replace(",", "").strip()
                try:
                    if " to " not in raw:
                        p = float(raw)
                        if p > min_price:
                            return p, link_el.get("href", "")
                except Exception:
                    pass
    except Exception as e:
        log("SYS", "eBay BIN error: " + str(e)[:50])
    return None, None

def hunt_singles_batch():
    idx = state["batch_index"]
    batch = SINGLES_TARGETS[idx: idx + BATCH_SIZE]
    next_idx = idx + BATCH_SIZE
    if next_idx >= len(SINGLES_TARGETS):
        next_idx = 0
    state["batch_index"] = next_idx

    total = len(SINGLES_TARGETS)
    log("SYS", "Singles batch " + str(idx) + "-" + str(idx + len(batch)) + " of " + str(total) + " cards")

    for card in batch:
        if not state["running"]:
            break

        name = card["name"]
        set_name = card["set"]
        state["total_scanned"] += 1

        log("SCAN", name + " [" + card["rarity"] + "] — " + set_name)
        market = ebay_sold_median(name + " " + set_name + " pokemon NM")

        if not market or market < 10:
            log("SYS", "Skip " + name + " — no data or under $10")
            time.sleep(1)
            continue

        log("FIND", name + " market: $" + str(round(market, 2)))
        cheapest, link = ebay_cheapest_bin(name + " " + set_name + " pokemon NM")

        if not cheapest:
            log("SYS", "No BIN listings for " + name)
            time.sleep(1)
            continue

        discount = (market - cheapest) / market

        if discount >= SINGLES_THRESHOLD:
            pct          = round(discount * 100)
            whatnot_sell = round(market * 1.05, 2)
            net_profit   = round(whatnot_sell * (1 - WHATNOT_FEE) - cheapest, 2)

            deal = {
                "id": name + "-" + str(int(time.time())),
                "name": name,
                "set": set_name,
                "rarity": card["rarity"],
                "platform": "eBay",
                "buyPrice": cheapest,
                "market": round(market, 2),
                "whatnotSell": whatnot_sell,
                "netProfit": net_profit,
                "pct": pct,
                "link": link,
                "condition": "NM/LP",
                "time": datetime.now().strftime("%H:%M"),
            }

            existing = [d for d in state["deals_found"] if d["name"] != name or d["set"] != set_name]
            existing.append(deal)
            state["deals_found"] = existing

            log("DEAL", "DEAL: " + name + " @ $" + str(cheapest) + " — " + str(pct) + "% below $" + str(round(market, 2)) + " — profit ~$" + str(net_profit))

            send_telegram(
                "🌿 <b>MINTY CARDS DEAL</b>\n\n"
                "<b>" + name + "</b> [" + card["rarity"] + "]\n"
                + set_name + "\n\n"
                "💰 Buy: <b>$" + str(cheapest) + "</b> on eBay\n"
                "📈 eBay market: $" + str(round(market, 2)) + "\n"
                "🏪 Whatnot sell: ~$" + str(whatnot_sell) + "\n"
                "✅ Net profit: ~<b>$" + str(net_profit) + "</b>\n"
                "🔥 " + str(pct) + "% below market\n\n"
                "<a href='" + link + "'>⚡ BUY NOW ON EBAY</a>"
            )
        else:
            log("FIND", name + " $" + str(cheapest) + " vs $" + str(round(market, 2)) + " — " + str(round(discount * 100)) + "% below, skip")

        time.sleep(2)

def hunt_sealed_batch():
    log("SYS", "Sealed batch — " + str(len(SEALED_TARGETS)) + " products")
    new_deals = []

    for product in SEALED_TARGETS:
        if not state["running"]:
            break

        name = product["name"]
        log("SCAN", "Sealed: " + name)
        state["total_scanned"] += 1

        market = ebay_sold_median(name + " pokemon sealed")
        if not market or market < 10:
            log("SYS", "Skip " + name + " — no data")
            time.sleep(1)
            continue

        log("FIND", name + " market: $" + str(round(market, 2)))
        cheapest, link = ebay_cheapest_bin(name + " pokemon sealed", min_price=SEALED_MIN_PRICE)

        if not cheapest or cheapest < SEALED_MIN_PRICE:
            if cheapest:
                log("ALERT", "Bait filtered: " + name + " @ $" + str(cheapest))
            time.sleep(1)
            continue

        discount = (market - cheapest) / market

        if discount >= SEALED_THRESHOLD:
            pct        = round(discount * 100)
            net_profit = round(market * (1 - SEALED_FEE) - cheapest, 2)

            deal = {
                "id": "seal-" + name + "-" + str(int(time.time())),
                "name": name,
                "type": product["type"],
                "set": product["set"],
                "platform": "eBay",
                "buyPrice": cheapest,
                "market": round(market, 2),
                "netProfit": net_profit,
                "pct": pct,
                "link": link,
                "time": datetime.now().strftime("%H:%M"),
            }
            new_deals.append(deal)
            log("DEAL", "SEALED: " + name + " @ $" + str(cheapest) + " — " + str(pct) + "% below $" + str(round(market, 2)))

            send_telegram(
                "📦 <b>MINTY SEALED DEAL</b>\n\n"
                "<b>" + name + "</b>\n"
                + product["set"] + " · " + product["type"] + "\n\n"
                "💰 Buy: <b>$" + str(cheapest) + "</b> on eBay\n"
                "📈 eBay market: $" + str(round(market, 2)) + "\n"
                "✅ Net profit: ~<b>$" + str(net_profit) + "</b>\n"
                "🔥 " + str(pct) + "% below market\n\n"
                "<a href='" + link + "'>⚡ BUY NOW ON EBAY</a>"
            )
        else:
            log("FIND", name + " $" + str(cheapest) + " vs $" + str(round(market, 2)) + " — skip")

        time.sleep(2)

    state["sealed_deals"] = new_deals

def run_full_hunt():
    if state["running"]:
        log("SYS", "Already running — skip")
        return
    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("SYS", "=== CYCLE #" + str(state["scan_count"]) + " — batch " + str(state["batch_index"]) + "/" + str(len(SINGLES_TARGETS)) + " ===")
    try:
        hunt_singles_batch()
        # Run sealed every 6th cycle (every 30 min)
        if state["scan_count"] % 6 == 0:
            hunt_sealed_batch()
    except Exception as e:
        log("SYS", "Hunt error: " + str(e))
    finally:
        state["running"] = False
        log("SYS", "=== CYCLE #" + str(state["scan_count"]) + " COMPLETE ===")

def schedule_loop():
    while True:
        run_full_hunt()
        time.sleep(REFRESH_MINUTES * 60)

@app.route("/")
def index():
    return "Minty Cards Agent — /status /deals /log /hunt"

@app.route("/status")
def status():
    total = len(SINGLES_TARGETS)
    scanned_so_far = state["batch_index"]
    return jsonify({
        "running": state["running"],
        "last_scan": state["last_scan"],
        "scan_count": state["scan_count"],
        "total_scanned": state["total_scanned"],
        "singles_deals": len(state["deals_found"]),
        "sealed_deals": len(state["sealed_deals"]),
        "alerts_sent": state["alerts_sent"],
        "card_coverage": str(scanned_so_far) + "/" + str(total),
        "refresh_minutes": REFRESH_MINUTES,
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
    send_telegram("🌿 <b>Minty Cards Agent</b> — test OK. 50 cards hunting every 5 min!")
    return jsonify({"status": "sent"})

log("SYS", "Minty Cards Agent starting — eBay only, batch mode, 5 min cycles")
log("SYS", str(len(SINGLES_TARGETS)) + " cards total — " + str(BATCH_SIZE) + " per cycle — " + str(len(SEALED_TARGETS)) + " sealed every 30 min")
threading.Thread(target=schedule_loop, daemon=True).start()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
