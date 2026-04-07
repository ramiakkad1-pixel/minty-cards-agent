import os
import time
import threading
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ═══ CONFIG ═══
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "8639012891:AAEsPGc6eISuFWVXpi7w3ORba75ha3R4woI")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7922849859")
SINGLES_THRESHOLD = 0.20
SEALED_THRESHOLD  = 0.30
SEALED_MIN_PRICE  = 3.00
REFRESH_MINUTES   = 30
WHATNOT_FEE       = 0.15
SEALED_FEE        = 0.12

# ═══ TARGET CARDS ═══
SINGLES_TARGETS = [
    {"name": "Umbreon ex",         "set": "Prismatic Evolutions", "rarity": "SAR"},
    {"name": "Sylveon ex",         "set": "Prismatic Evolutions", "rarity": "SAR"},
    {"name": "Eevee ex",           "set": "Prismatic Evolutions", "rarity": "SIR"},
    {"name": "Espeon ex",          "set": "Prismatic Evolutions", "rarity": "IR"},
    {"name": "Glaceon ex",         "set": "Prismatic Evolutions", "rarity": "SAR"},
    {"name": "Charizard ex",       "set": "Paldean Fates",        "rarity": "SAR"},
    {"name": "Mewtwo ex",          "set": "151",                  "rarity": "SIR"},
    {"name": "Mew ex",             "set": "151",                  "rarity": "SAR"},
    {"name": "Stellar Rayquaza ex","set": "Stellar Crown",        "rarity": "SAR"},
    {"name": "Dragapult ex",       "set": "Destined Rivals",      "rarity": "SAR"},
    {"name": "Miraidon ex",        "set": "Destined Rivals",      "rarity": "SIR"},
    {"name": "Pikachu ex",         "set": "Surging Sparks",       "rarity": "SAR"},
    {"name": "Terapagos ex",       "set": "Stellar Crown",        "rarity": "SIR"},
    {"name": "Meowscarada ex",     "set": "Paldean Fates",        "rarity": "SIR"},
]

# ═══ SEALED TARGETS (top 6 most liquid) ═══
SEALED_TARGETS = [
    {"name": "Prismatic Evolutions Booster Box", "type": "Booster Box", "set": "Prismatic Evolutions"},
    {"name": "Prismatic Evolutions ETB",         "type": "ETB",         "set": "Prismatic Evolutions"},
    {"name": "Paldean Fates Booster Box",        "type": "Booster Box", "set": "Paldean Fates"},
    {"name": "Destined Rivals Booster Box",      "type": "Booster Box", "set": "Destined Rivals"},
    {"name": "151 ETB",                          "type": "ETB",         "set": "151"},
    {"name": "Stellar Crown Booster Box",        "type": "Booster Box", "set": "Stellar Crown"},
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
    if len(state["log"]) > 300:
        state["log"] = state["log"][-300:]
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

# ═══ KEEP-ALIVE (stops Render free tier from sleeping) ═══
def keep_alive():
    while True:
        time.sleep(600)  # ping every 10 min
        try:
            own_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
            requests.get(f"{own_url}/status", timeout=5)
            log("SYS", "Keep-alive ping sent")
        except:
            pass

# ═══ PRICE FETCHERS ═══
def get_pricecharting_price(card_name, set_name):
    try:
        query = f"{card_name} {set_name} pokemon"
        url = f"https://www.pricecharting.com/search-products?q={requests.utils.quote(query)}&type=prices"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        price_els = soup.select(".price .js-price")
        if price_els:
            raw = price_els[0].get_text().replace("$", "").replace(",", "").strip()
            return float(raw)
    except Exception as e:
        log("SYS", f"PriceCharting error for {card_name}: {str(e)[:50]}")
    return None

def get_tcgplayer_price(card_name, set_name):
    try:
        query = f"{card_name} {set_name}"
        url = f"https://www.tcgplayer.com/search/pokemon/product?q={requests.utils.quote(query)}&view=grid"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
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
    try:
        query = f"{card_name} {set_name} pokemon NM"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_Sold=1&LH_Complete=1&_sop=13"
        resp = requests.get(url, headers=HEADERS, timeout=10)
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
            except:
                pass
        if prices:
            prices = sorted(prices[:10])
            return prices[len(prices) // 2]
    except Exception as e:
        log("SYS", f"eBay sold error for {card_name}: {str(e)[:50]}")
    return None

def get_market_avg(card_name, set_name):
    """Fetch all 3 sources IN PARALLEL — 3x faster"""
    log("SCAN", f'Pricing "{card_name}" across 3 sources simultaneously...')
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_tcg = ex.submit(get_tcgplayer_price, card_name, set_name)
        f_pc  = ex.submit(get_pricecharting_price, card_name, set_name)
        f_eb  = ex.submit(get_ebay_sold_price, card_name, set_name)
        tcg = f_tcg.result(timeout=8)
        pc  = f_pc.result(timeout=8)
        eb  = f_eb.result(timeout=8)


    prices = []
    if tcg and tcg > 0.50: prices.append(tcg); log("FIND", f'TCGPlayer: ${tcg:.2f}')
    if pc  and pc  > 0.50: prices.append(pc);  log("FIND", f'PriceCharting: ${pc:.2f}')
    if eb  and eb  > 0.50: prices.append(eb);  log("FIND", f'eBay sold: ${eb:.2f}')

    if not prices:
        return None
    avg = round(sum(prices) / len(prices), 2)
    log("FIND", f'Market avg "{card_name}": ${avg} ({len(prices)} sources)')
    return avg

def get_cheapest_listing(card_name, set_name):
    try:
        query = f"{card_name} {set_name} pokemon NM"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_BIN=1&_sop=15"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        prices, links = [], []
        for item in soup.select(".s-item")[:20]:
            price_el = item.select_one(".s-item__price")
            link_el  = item.select_one(".s-item__link")
            if price_el and link_el:
                raw = price_el.get_text().replace("$", "").replace(",", "").strip()
                try:
                    if " to " not in raw:
                        p = float(raw)
                        if p > 0.99:
                            prices.append(p)
                            links.append(link_el.get("href", ""))
                except:
                    pass
        if prices:
            idx = prices.index(min(prices))
            return min(prices), links[idx]
    except Exception as e:
        log("SYS", f"eBay listing error: {str(e)[:50]}")
    return None, None

def get_sealed_market_price(product_name):
    try:
        query = f"{product_name} pokemon sealed"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_Sold=1&LH_Complete=1&_sop=13"
        resp = requests.get(url, headers=HEADERS, timeout=10)
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
            return prices[len(prices) // 2]
    except Exception as e:
        log("SYS", f"Sealed market error: {str(e)[:50]}")
    return None

def get_cheapest_sealed(product_name):
    try:
        query = f"{product_name} pokemon sealed"
        url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&LH_BIN=1&_sop=15"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".s-item")[:20]:
            price_el = item.select_one(".s-item__price")
            link_el  = item.select_one(".s-item__link")
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
    log("SYS", f"Singles hunt — {len(SINGLES_TARGETS)} cards · parallel pricing · 1s delays")
    new_deals = []
    for card in SINGLES_TARGETS:
        if not state["running"]:
            break
        state["total_scanned"] += 1
        market = get_market_avg(card["name"], card["set"])
        if not market:
            log("SYS", f'No price data for "{card["name"]}" — skipping')
            time.sleep(0.5)
            continue
        cheapest, link = get_cheapest_listing(card["name"], card["set"])
        if not cheapest:
            log("SYS", f'No listings for "{card["name"]}"')
            time.sleep(0.5)
            continue
        discount = (market - cheapest) / market
        if discount >= SINGLES_THRESHOLD:
            pct          = round(discount * 100)
            whatnot_sell = round(market * 1.05, 2)
            net_profit   = round(whatnot_sell * (1 - WHATNOT_FEE) - cheapest, 2)
            deal = {
                "id": f"{card['name']}-{int(time.time())}",
                "name": card["name"], "set": card["set"], "rarity": card["rarity"],
                "platform": "eBay", "buyPrice": cheapest, "market": market,
                "whatnotSell": whatnot_sell, "netProfit": net_profit,
                "pct": pct, "link": link, "condition": "NM/LP",
                "time": datetime.now().strftime("%H:%M"),
            }
            new_deals.append(deal)
            log("DEAL", f'🎯 {card["name"]} @ ${cheapest} — {pct}% below ${market} · profit ~${net_profit}')
            send_telegram(
                f"🌿 <b>MINTY CARDS DEAL</b>\n\n"
                f"<b>{card['name']}</b> [{card['rarity']}]\n{card['set']}\n\n"
                f"💰 Buy: <b>${cheapest}</b> on eBay\n"
                f"📈 Market avg: ${market}\n"
                f"🏪 Whatnot sell: ~${whatnot_sell}\n"
                f"✅ Net profit: ~<b>${net_profit}</b>\n"
                f"🔥 {pct}% below market\n\n"
                f"<a href='{link}'>⚡ BUY NOW ON EBAY</a>"
            )
        else:
            log("FIND", f'"{card["name"]}" ${cheapest} vs ${market} — {round(discount*100)}% below, skip')
        time.sleep(1)

    state["deals_found"] = new_deals
    log("SYS", f"Singles complete — {len(new_deals)} deals")

def hunt_sealed():
    log("SYS", f"Sealed hunt — {len(SEALED_TARGETS)} products · fast mode")
    new_deals = []
    for product in SEALED_TARGETS:
        if not state["running"]:
            break
        log("SCAN", f'Hunting sealed: "{product["name"]}"')
        state["total_scanned"] += 1
        market = get_sealed_market_price(product["name"])
        if not market:
            log("SYS", f'No market price for "{product["name"]}" — skip')
            time.sleep(0.5)
            continue
        cheapest, link = get_cheapest_sealed(product["name"])
        if not cheapest:
            log("SYS", f'No listings for "{product["name"]}"')
            time.sleep(0.5)
            continue
        if cheapest < SEALED_MIN_PRICE:
            log("ALERT", f'⚠️ Bait filtered: "{product["name"]}" @ ${cheapest}')
            continue
        discount = (market - cheapest) / market
        if discount >= SEALED_THRESHOLD:
            pct        = round(discount * 100)
            net_profit = round(market * (1 - SEALED_FEE) - cheapest, 2)
            deal = {
                "id": f"seal-{product['name']}-{int(time.time())}",
                "name": product["name"], "type": product["type"], "set": product["set"],
                "platform": "eBay", "buyPrice": cheapest, "market": market,
                "netProfit": net_profit, "pct": pct, "link": link,
                "time": datetime.now().strftime("%H:%M"),
            }
            new_deals.append(deal)
            log("DEAL", f'📦 {product["name"]} @ ${cheapest} — {pct}% below ${market} · profit ~${net_profit}')
            send_telegram(
                f"📦 <b>MINTY SEALED DEAL</b>\n\n"
                f"<b>{product['name']}</b>\n{product['set']} · {product['type']}\n\n"
                f"💰 Buy: <b>${cheapest}</b> on eBay\n"
                f"📈 Market avg: ${market}\n"
                f"✅ Net profit: ~<b>${net_profit}</b>\n"
                f"🔥 {pct}% below market\n\n"
                f"<a href='{link}'>⚡ BUY NOW ON EBAY</a>"
            )
        else:
            log("FIND", f'"{product["name"]}" ${cheapest} vs ${market} — not enough')
        time.sleep(1)

    state["sealed_deals"] = new_deals
    log("SYS", f"Sealed complete — {len(new_deals)} deals")

def run_full_hunt():
    if state["running"]:
        log("SYS", "Already running — skip")
        return
    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("SYS", f"=== HUNT CYCLE #{state['scan_count']} STARTED ===")
    try:
        hunt_singles()
        time.sleep(2)
        hunt_sealed()
    except Exception as e:
        log("SYS", f"Hunt error: {str(e)}")
    finally:
        state["running"] = False
        log("SYS", f"=== CYCLE #{state['scan_count']} COMPLETE — next in {REFRESH_MINUTES} min ===")

def schedule_loop():
    while True:
        run_full_hunt()
        time.sleep(REFRESH_MINUTES * 60)

# ═══ ROUTES ═══
@app.route("/")
def index():
    return "Minty Cards Agent running. /status /deals /log /hunt"

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
    send_telegram("🌿 <b>Minty Cards Agent</b> — test message. Alerts are live!")
    return jsonify({"status": "sent"})

# ═══ START ═══
log("SYS", "Minty Cards Agent starting — fast mode + keep-alive enabled")
log("SYS", f"{len(SINGLES_TARGETS)} singles · {len(SEALED_TARGETS)} sealed · parallel pricing · 1s delays")
threading.Thread(target=schedule_loop, daemon=True).start()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
