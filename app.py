import os
import json
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)
# ═══ CONFIG ═══
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8639012891:AAEsPGc6eISuFWVXpi7w3ORba75ha3R4woI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7922849859")
SINGLES_THRESHOLD = 0.20   # 20% below market
SEALED_THRESHOLD  = 0.30   # 30% below market
SEALED_MIN_PRICE  = 3.00   # filter $1 bait
REFRESH_MINUTES   = 30
WHATNOT_FEE       = 0.15
SEALED_FEE        = 0.12

# ═══ TARGET CARDS ═══
SINGLES_TARGETS = [
    {"name": "Umbreon ex", "set": "Prismatic Evolutions", "rarity": "SAR", "tcg_id": "prismatic-evolutions-umbreon-ex"},
    {"name": "Sylveon ex", "set": "Prismatic Evolutions", "rarity": "SAR", "tcg_id": "prismatic-evolutions-sylveon-ex"},
    {"name": "Eevee ex", "set": "Prismatic Evolutions", "rarity": "SIR", "tcg_id": "prismatic-evolutions-eevee-ex"},
    {"name": "Espeon ex", "set": "Prismatic Evolutions", "rarity": "IR", "tcg_id": "prismatic-evolutions-espeon-ex"},
    {"name": "Glaceon ex", "set": "Prismatic Evolutions", "rarity": "SAR", "tcg_id": "prismatic-evolutions-glaceon-ex"},
    {"name": "Charizard ex", "set": "Paldean Fates", "rarity": "SAR", "tcg_id": "paldean-fates-charizard-ex"},
    {"name": "Mewtwo ex", "set": "151", "rarity": "SIR", "tcg_id": "pokemon-151-mewtwo-ex"},
    {"name": "Mew ex", "set": "151", "rarity": "SAR", "tcg_id": "pokemon-151-mew-ex"},
    {"name": "Stellar Rayquaza ex", "set": "Stellar Crown", "rarity": "SAR", "tcg_id": "stellar-crown-rayquaza-ex"},
    {"name": "Dragapult ex", "set": "Destined Rivals", "rarity": "SAR", "tcg_id": "destined-rivals-dragapult-ex"},
    {"name": "Miraidon ex", "set": "Destined Rivals", "rarity": "SIR", "tcg_id": "destined-rivals-miraidon-ex"},
    {"name": "Pikachu ex", "set": "Surging Sparks", "rarity": "SAR", "tcg_id": "surging-sparks-pikachu-ex"},
    {"name": "Terapagos ex", "set": "Stellar Crown", "rarity": "SIR", "tcg_id": "stellar-crown-terapagos-ex"},
    {"name": "Meowscarada ex", "set": "Paldean Fates", "rarity": "SIR", "tcg_id": "paldean-fates-meowscarada-ex"},
]

SEALED_TARGETS = [
    {"name": "Prismatic Evolutions Booster Box", "type": "Booster Box", "set": "Prismatic Evolutions"},
    {"name": "Prismatic Evolutions ETB", "type": "ETB", "set": "Prismatic Evolutions"},
    {"name": "Paldean Fates ETB", "type": "ETB", "set": "Paldean Fates"},
    {"name": "Paldean Fates Booster Box", "type": "Booster Box", "set": "Paldean Fates"},
    {"name": "Destined Rivals Booster Box", "type": "Booster Box", "set": "Destined Rivals"},
    {"name": "Destined Rivals ETB", "type": "ETB", "set": "Destined Rivals"},
    {"name": "151 ETB", "type": "ETB", "set": "151"},
    {"name": "151 Booster Bundle", "type": "Booster Bundle", "set": "151"},
    {"name": "Surging Sparks Booster Box", "type": "Booster Box", "set": "Surging Sparks"},
    {"name": "Stellar Crown Booster Box", "type": "Booster Box", "set": "Stellar Crown"},
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
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# ═══ LOGGING ═══
def log(level, msg):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    state["log"].append(entry)
    if len(state["log"]) > 200:
        state["log"] = state["log"][-200:]
    print(f"[{entry['time']}] [{level}] {msg}")

# ═══ TELEGRAM ═══
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        if resp.status_code == 200:
            state["alerts_sent"] += 1
            log("ALERT", f"Telegram sent: {msg[:60]}...")
        else:
            log("ALERT", f"Telegram error: {resp.text[:100]}")
    except Exception as e:
        log("ALERT", f"Telegram failed: {str(e)}")

# ═══ PRICE FETCHERS ═══
def get_pricecharting_price(card_name, set_name):
    """Fetch price from PriceCharting"""
    try:
        query = f"{card_name} {set_name} pokemon"
        url = f"https://www.pricecharting.com/search-products?q={requests.utils.quote(query)}&type=prices"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to get the first result price
        price_els = soup.select(".price .js-price")
        if price_els:
            raw = price_els[0].get_text().replace("$", "").replace(",", "").strip()
            return float(raw)
    except Exception as e:
        log("SYS", f"PriceCharting error for {card_name}: {str(e)[:50]}")
    return None

def get_tcgplayer_price(card_name, set_name):
    """Fetch market price from TCGPlayer"""
    try:
        query = f"{card_name} {set_name}"
        url = f"https://www.tcgplayer.com/search/pokemon/product?q={requests.utils.quote(query)}&view=grid"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # TCGPlayer market price selectors
        price_els = soup.select(".search-result__market-price--value")
        if not price_els:
            price_els = soup.select(".inventory__price-with-shipping")
        if price_els:
            raw = price_els[0].get_text().replace("$", "").replace(",", "").strip()
            return float(raw)
    except Exception as e:
        log("SYS", f"TCGPlayer error for {card_name}: {str(e)[:50]}")
    return None

def get_ebay_sold_price(card_name, set_name):
    """Fetch recent sold price from eBay"""
    try:
        query = f"{card_name} {set_name} pokemon NM"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_Sold=1&LH_Complete=1&_sop=13"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        prices = []
        for el in soup.select(".s-item__price"):
            raw = el.get_text().replace("$", "").replace(",", "").strip()
            try:
                # Handle price ranges like "10.00 to 20.00"
                if " to " in raw:
                    parts = raw.split(" to ")
                    prices.append((float(parts[0]) + float(parts[1])) / 2)
                else:
                    prices.append(float(raw))
            except:
                pass

        if prices:
            # Return median of first 10 sold prices
            prices = sorted(prices[:10])
            mid = len(prices) // 2
            return prices[mid]
    except Exception as e:
        log("SYS", f"eBay error for {card_name}: {str(e)[:50]}")
    return None

def get_market_avg(card_name, set_name):
    """Get average of all 3 sources"""
    prices = []
    log("SCAN", f'Checking TCGPlayer for "{card_name}"...')
    tcg = get_tcgplayer_price(card_name, set_name)
    if tcg and tcg > 0.50:
        prices.append(tcg)
        log("FIND", f'TCGPlayer: "{card_name}" = ${tcg:.2f}')

    time.sleep(1)
    log("SCAN", f'Checking PriceCharting for "{card_name}"...')
    pc = get_pricecharting_price(card_name, set_name)
    if pc and pc > 0.50:
        prices.append(pc)
        log("FIND", f'PriceCharting: "{card_name}" = ${pc:.2f}')

    time.sleep(1)
    log("SCAN", f'Checking eBay sold for "{card_name}"...')
    eb = get_ebay_sold_price(card_name, set_name)
    if eb and eb > 0.50:
        prices.append(eb)
        log("FIND", f'eBay sold: "{card_name}" = ${eb:.2f}')

    if not prices:
        return None

    avg = sum(prices) / len(prices)
    log("FIND", f'Market avg for "{card_name}": ${avg:.2f} ({len(prices)} sources)')
    return round(avg, 2)

def get_cheapest_listing(card_name, set_name):
    """Find cheapest current active listing on eBay"""
    try:
        query = f"{card_name} {set_name} pokemon NM"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_BIN=1&_sop=15"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        prices = []
        links = []
        items = soup.select(".s-item")
        for item in items[:20]:
            price_el = item.select_one(".s-item__price")
            link_el = item.select_one(".s-item__link")
            if price_el and link_el:
                raw = price_el.get_text().replace("$", "").replace(",", "").strip()
                try:
                    if " to " not in raw:
                        p = float(raw)
                        if p > 0.99:  # filter $0.99 junk
                            prices.append(p)
                            links.append(link_el.get("href", ""))
                except:
                    pass

        if prices:
            min_idx = prices.index(min(prices))
            return min(prices), links[min_idx]
    except Exception as e:
        log("SYS", f"eBay listing error: {str(e)[:50]}")
    return None, None

def get_sealed_market_price(product_name):
    """Get sealed product market price from eBay sold"""
    try:
        query = f"{product_name} pokemon sealed"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_Sold=1&LH_Complete=1&_sop=13"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        prices = []
        for el in soup.select(".s-item__price"):
            raw = el.get_text().replace("$", "").replace(",", "").strip()
            try:
                if " to " not in raw:
                    p = float(raw)
                    if p > 2:
                        prices.append(p)
            except:
                pass
        if prices:
            prices = sorted(prices[:15])
            mid = len(prices) // 2
            return prices[mid]
    except Exception as e:
        log("SYS", f"Sealed market price error: {str(e)[:50]}")
    return None

def get_cheapest_sealed(product_name):
    """Find cheapest sealed listing"""
    try:
        query = f"{product_name} pokemon sealed"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_BIN=1&_sop=15"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select(".s-item")
        for item in items[:20]:
            price_el = item.select_one(".s-item__price")
            link_el = item.select_one(".s-item__link")
            if price_el and link_el:
                raw = price_el.get_text().replace("$", "").replace(",", "").strip()
                try:
                    if " to " not in raw:
                        p = float(raw)
                        if p >= SEALED_MIN_PRICE:
                            return p, link_el.get("href", "")
                except:
                    pass
    except Exception as e:
        log("SYS", f"Cheapest sealed error: {str(e)[:50]}")
    return None, None

# ═══ HUNT ENGINES ═══
def hunt_singles():
    log("SYS", f"Singles hunt started — {len(SINGLES_TARGETS)} target cards")
    new_deals = []

    for card in SINGLES_TARGETS:
        if not state["running"]:
            break

        log("SCAN", f'Hunting "{card["name"]}" [{card["rarity"]}] — {card["set"]}')
        state["total_scanned"] += 1

        market = get_market_avg(card["name"], card["set"])
        if not market:
            log("SYS", f'No price data found for "{card["name"]}" — skipping')
            time.sleep(2)
            continue

        cheapest, link = get_cheapest_listing(card["name"], card["set"])
        if not cheapest:
            log("SYS", f'No active listings for "{card["name"]}"')
            time.sleep(2)
            continue

        discount = (market - cheapest) / market
        if discount >= SINGLES_THRESHOLD:
            pct = round(discount * 100)
            # Estimate Whatnot sell price (slightly above market)
            whatnot_sell = round(market * 1.05, 2)
            net_profit = round(whatnot_sell * (1 - WHATNOT_FEE) - cheapest, 2)

            deal = {
                "id": f"{card['name']}-{int(time.time())}",
                "name": card["name"],
                "set": card["set"],
                "rarity": card["rarity"],
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
            new_deals.append(deal)
            log("DEAL", f'🎯 {card["name"]} @ ${cheapest} — {pct}% below market ${market} · Arb profit ~${net_profit}')

            msg = (
                f"🌿 <b>MINTY CARDS DEAL</b>\n\n"
                f"<b>{card['name']}</b> [{card['rarity']}]\n"
                f"{card['set']}\n\n"
                f"💰 Buy: <b>${cheapest}</b> on eBay\n"
                f"📈 Market avg: ${market}\n"
                f"🏪 Whatnot sell: ~${whatnot_sell}\n"
                f"✅ Net profit: ~<b>${net_profit}</b>\n"
                f"🔥 {pct}% below market\n\n"
                f"<a href='{link}'>⚡ BUY NOW ON EBAY</a>"
            )
            send_telegram(msg)
        else:
            pct = round(discount * 100)
            log("FIND", f'"{card["name"]}" cheapest ${cheapest} vs market ${market} — only {pct}% below, skipping')

        time.sleep(3)  # be respectful to servers

    state["deals_found"] = new_deals
    log("SYS", f"Singles hunt complete — {len(new_deals)} deals found")

def hunt_sealed():
    log("SYS", f"Sealed hunt started — {len(SEALED_TARGETS)} products")
    new_deals = []

    for product in SEALED_TARGETS:
        if not state["running"]:
            break

        log("SCAN", f'Hunting sealed: "{product["name"]}"')
        state["total_scanned"] += 1

        market = get_sealed_market_price(product["name"])
        if not market:
            log("SYS", f'No market price for "{product["name"]}" — skipping')
            time.sleep(2)
            continue

        cheapest, link = get_cheapest_sealed(product["name"])
        if not cheapest:
            log("SYS", f'No listings found for "{product["name"]}"')
            time.sleep(2)
            continue

        # Filter bait listings
        if cheapest < SEALED_MIN_PRICE:
            log("ALERT", f'⚠️ Bait listing filtered: "{product["name"]}" @ ${cheapest} — too low, likely scam')
            time.sleep(2)
            continue

        discount = (market - cheapest) / market
        if discount >= SEALED_THRESHOLD:
            pct = round(discount * 100)
            net_profit = round(market * (1 - SEALED_FEE) - cheapest, 2)

            deal = {
                "id": f"seal-{product['name']}-{int(time.time())}",
                "name": product["name"],
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
            log("DEAL", f'📦 {product["name"]} @ ${cheapest} — {pct}% below market ${market} · Resell profit ~${net_profit}')

            msg = (
                f"📦 <b>MINTY SEALED DEAL</b>\n\n"
                f"<b>{product['name']}</b>\n"
                f"{product['set']} · {product['type']}\n\n"
                f"💰 Buy: <b>${cheapest}</b> on eBay\n"
                f"📈 Market avg: ${market}\n"
                f"🏪 Resell est: ~${market}\n"
                f"✅ Net profit: ~<b>${net_profit}</b>\n"
                f"🔥 {pct}% below market\n\n"
                f"<a href='{link}'>⚡ BUY NOW ON EBAY</a>"
            )
            send_telegram(msg)
        else:
            log("FIND", f'"{product["name"]}" @ ${cheapest} vs market ${market} — not enough discount')

        time.sleep(3)

    state["sealed_deals"] = new_deals
    log("SYS", f"Sealed hunt complete — {len(new_deals)} deals found")

def run_full_hunt():
    if state["running"]:
        log("SYS", "Hunt already in progress — skipping")
        return

    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("SYS", f"=== HUNT CYCLE #{state['scan_count']} STARTED ===")

    try:
        hunt_singles()
        time.sleep(5)
        hunt_sealed()
    except Exception as e:
        log("SYS", f"Hunt error: {str(e)}")
    finally:
        state["running"] = False
        log("SYS", f"=== HUNT CYCLE #{state['scan_count']} COMPLETE — next in {REFRESH_MINUTES} min ===")

def schedule_loop():
    """Run hunt every 30 minutes"""
    while True:
        run_full_hunt()
        time.sleep(REFRESH_MINUTES * 60)

# ═══ API ROUTES ═══
@app.route("/")
def index():
    return "Minty Cards Agent is running. Go to /status for details."

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
    })

@app.route("/deals")
def deals():
    return jsonify({
        "singles": state["deals_found"],
        "sealed": state["sealed_deals"],
    })

@app.route("/log")
def get_log():
    return jsonify(state["log"][-100:])

@app.route("/hunt")
def manual_hunt():
    if state["running"]:
        return jsonify({"status": "already running"})
    t = threading.Thread(target=run_full_hunt, daemon=True)
    t.start()
    return jsonify({"status": "hunt started"})

@app.route("/test-telegram")
def test_telegram():
    send_telegram("🌿 <b>Minty Cards Agent</b> — test message. Your deal alerts are live and working!")
    return jsonify({"status": "sent"})

# ═══ START ═══
if __name__ == "__main__":
    log("SYS", "Minty Cards Arbitrage Agent starting up...")
    log("SYS", f"Telegram: {TELEGRAM_CHAT_ID} | Refresh: {REFRESH_MINUTES}min | Singles: {SINGLES_THRESHOLD*100}% | Sealed: {SEALED_THRESHOLD*100}%")

    # Start hunt loop in background
    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
