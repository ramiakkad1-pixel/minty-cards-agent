import os
import time
import threading
import requests
import traceback
from flask import Flask, jsonify
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# MINTY CARDS ARBITRAGE AGENT v3.1
# ═══════════════════════════════════════════════════════════════
# - pokemontcg.io API → real TCGPlayer market prices
# - Alert-once: same card+price only alerts once
# - Re-alerts when price drops $2+ further
# - 75+ high-value cards across 12 sets
# - Batch rotation: 10 cards per cycle, 30s between batches
# - No scraping. No eBay. No PokeTrace. Clean API only.
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
POKEMONTCG_KEY   = os.environ.get("POKEMONTCG_KEY", "")
THRESHOLD        = float(os.environ.get("THRESHOLD", "0.20"))
REFRESH_MINUTES  = int(os.environ.get("REFRESH_MINUTES", "10"))
WHATNOT_FEE      = 0.15
REQUEST_TIMEOUT  = 15
BATCH_SIZE       = 10

# Alert-once tracking: key=card_id, value=last_alerted_low_price
alerted_cards = {}
PRICE_CHANGE_THRESHOLD = 2.00

# ══════════════════════════════════════════════════════════════
# TARGET CARDS — SAR, SIR, HR, IR, UR, Full Art, Shiny across 12 sets
# ══════════════════════════════════════════════════════════════
TARGETS = [
    # ═══ PRISMATIC EVOLUTIONS ═══
    {"name": "Umbreon ex",  "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Umbreon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Sylveon ex",  "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Sylveon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Glaceon ex",  "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Glaceon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Eevee ex",    "set": "Prismatic Evolutions", "rarity": "SIR", "q": 'name:"Eevee ex" set.name:"Prismatic Evolutions"'},
    {"name": "Espeon ex",   "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Espeon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Flareon ex",  "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Flareon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Vaporeon ex", "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Vaporeon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Jolteon ex",  "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Jolteon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Leafeon ex",  "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Leafeon ex" set.name:"Prismatic Evolutions"'},

    # ═══ PALDEAN FATES ═══
    {"name": "Charizard ex",  "set": "Paldean Fates", "rarity": "HR",  "q": 'name:"Charizard ex" set.name:"Paldean Fates" rarity:"Hyper Rare"'},
    {"name": "Mew ex",        "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Mew ex" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Gardevoir ex",  "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Gardevoir ex" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Charizard ex",  "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Charizard ex" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Iono",          "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Iono" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Penny",         "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Penny" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Nemona",        "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Nemona" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Arven",         "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Arven" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Koraidon ex",   "set": "Paldean Fates", "rarity": "HR",  "q": 'name:"Koraidon ex" set.name:"Paldean Fates" rarity:"Hyper Rare"'},
    {"name": "Miraidon ex",   "set": "Paldean Fates", "rarity": "HR",  "q": 'name:"Miraidon ex" set.name:"Paldean Fates" rarity:"Hyper Rare"'},
    {"name": "Alakazam ex",   "set": "Paldean Fates", "rarity": "SAR", "q": 'name:"Alakazam ex" set.name:"Paldean Fates"'},
    {"name": "Charmander",    "set": "Paldean Fates", "rarity": "Shiny","q": 'name:"Charmander" set.name:"Paldean Fates" rarity:"Shiny Rare"'},
    {"name": "Charmeleon",    "set": "Paldean Fates", "rarity": "Shiny","q": 'name:"Charmeleon" set.name:"Paldean Fates" rarity:"Shiny Rare"'},
    {"name": "Pikachu",       "set": "Paldean Fates", "rarity": "Shiny","q": 'name:"Pikachu" set.name:"Paldean Fates" rarity:"Shiny Rare"'},

    # ═══ DESTINED RIVALS ═══
    {"name": "Team Rocket's Mewtwo ex", "set": "Destined Rivals", "rarity": "HR",  "q": 'name:"Mewtwo" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Cynthia's Garchomp ex",   "set": "Destined Rivals", "rarity": "HR",  "q": 'name:"Garchomp" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Ethan's Ho-Oh ex",        "set": "Destined Rivals", "rarity": "HR",  "q": 'name:"Ho-Oh" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Team Rocket's Crobat ex",  "set": "Destined Rivals", "rarity": "HR",  "q": 'name:"Crobat" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Team Rocket's Mewtwo ex", "set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Mewtwo" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Cynthia's Garchomp ex",   "set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Garchomp" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Giovanni",  "set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Giovanni" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Ariana",    "set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Ariana" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Ethan's Adventure",       "set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Ethan" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Moltres ex","set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Moltres" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Nidoking ex","set":"Destined Rivals", "rarity": "SIR", "q": 'name:"Nidoking" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Arven's Mabosstiff ex",   "set": "Destined Rivals", "rarity": "SIR", "q": 'name:"Mabosstiff" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},

    # ═══ 151 ═══
    {"name": "Charizard ex",       "set": "151", "rarity": "SAR", "q": 'name:"Charizard ex" set.name:"151" rarity:"Special Art Rare"'},
    {"name": "Mewtwo ex",          "set": "151", "rarity": "SAR", "q": 'name:"Mewtwo ex" set.name:"151"'},
    {"name": "Mew ex",             "set": "151", "rarity": "SAR", "q": 'name:"Mew ex" set.name:"151"'},
    {"name": "Alakazam ex",        "set": "151", "rarity": "SAR", "q": 'name:"Alakazam ex" set.name:"151"'},
    {"name": "Gengar ex",          "set": "151", "rarity": "SAR", "q": 'name:"Gengar ex" set.name:"151"'},
    {"name": "Blastoise ex",       "set": "151", "rarity": "SAR", "q": 'name:"Blastoise ex" set.name:"151"'},
    {"name": "Venusaur ex",        "set": "151", "rarity": "SAR", "q": 'name:"Venusaur ex" set.name:"151"'},
    {"name": "Erika's Invitation", "set": "151", "rarity": "SAR", "q": 'name:"Erika" set.name:"151" rarity:"Special Art Rare"'},
    {"name": "Mewtwo ex",          "set": "151", "rarity": "SIR", "q": 'name:"Mewtwo ex" set.name:"151" rarity:"Special Illustration Rare"'},
    {"name": "Charizard ex",       "set": "151", "rarity": "SIR", "q": 'name:"Charizard ex" set.name:"151" rarity:"Special Illustration Rare"'},
    {"name": "Zapdos ex",          "set": "151", "rarity": "IR",  "q": 'name:"Zapdos ex" set.name:"151" rarity:"Illustration Rare"'},

    # ═══ SURGING SPARKS ═══
    {"name": "Pikachu ex",   "set": "Surging Sparks", "rarity": "SAR", "q": 'name:"Pikachu ex" set.name:"Surging Sparks"'},
    {"name": "Raichu ex",    "set": "Surging Sparks", "rarity": "SIR", "q": 'name:"Raichu ex" set.name:"Surging Sparks"'},
    {"name": "Arceus ex",    "set": "Surging Sparks", "rarity": "SIR", "q": 'name:"Arceus ex" set.name:"Surging Sparks"'},

    # ═══ STELLAR CROWN ═══
    {"name": "Terapagos ex", "set": "Stellar Crown", "rarity": "SIR", "q": 'name:"Terapagos ex" set.name:"Stellar Crown"'},
    {"name": "Rayquaza ex",  "set": "Stellar Crown", "rarity": "SAR", "q": 'name:"Rayquaza ex" set.name:"Stellar Crown"'},
    {"name": "Pecharunt ex", "set": "Stellar Crown", "rarity": "SAR", "q": 'name:"Pecharunt ex" set.name:"Stellar Crown"'},

    # ═══ TWILIGHT MASQUERADE ═══
    {"name": "Bloodmoon Ursaluna ex", "set": "Twilight Masquerade", "rarity": "SIR", "q": 'name:"Bloodmoon Ursaluna ex" set.name:"Twilight Masquerade"'},
    {"name": "Ogerpon ex",   "set": "Twilight Masquerade", "rarity": "SAR", "q": 'name:"Ogerpon ex" set.name:"Twilight Masquerade"'},

    # ═══ OBSIDIAN FLAMES ═══
    {"name": "Charizard ex", "set": "Obsidian Flames", "rarity": "SIR", "q": 'name:"Charizard ex" set.name:"Obsidian Flames" rarity:"Special Illustration Rare"'},
    {"name": "Charizard ex", "set": "Obsidian Flames", "rarity": "SAR", "q": 'name:"Charizard ex" set.name:"Obsidian Flames"'},

    # ═══ PARADOX RIFT ═══
    {"name": "Roaring Moon ex",  "set": "Paradox Rift", "rarity": "SIR", "q": 'name:"Roaring Moon ex" set.name:"Paradox Rift"'},
    {"name": "Iron Valiant ex",  "set": "Paradox Rift", "rarity": "SAR", "q": 'name:"Iron Valiant ex" set.name:"Paradox Rift"'},

    # ═══ TEMPORAL FORCES ═══
    {"name": "Walking Wake ex",  "set": "Temporal Forces", "rarity": "SIR", "q": 'name:"Walking Wake ex" set.name:"Temporal Forces"'},
    {"name": "Iron Leaves ex",   "set": "Temporal Forces", "rarity": "SAR", "q": 'name:"Iron Leaves ex" set.name:"Temporal Forces"'},

    # ═══ PALDEA EVOLVED ═══
    {"name": "Iono",         "set": "Paldea Evolved", "rarity": "SAR", "q": 'name:"Iono" set.name:"Paldea Evolved" rarity:"Special Art Rare"'},

    # ═══ CROWN ZENITH ═══
    {"name": "Giratina VSTAR","set": "Crown Zenith", "rarity": "SAR", "q": 'name:"Giratina VSTAR" set.name:"Crown Zenith"'},
]

# ── State ──
state = {
    "running": False,
    "last_scan": "never",
    "scan_count": 0,
    "total_cards_checked": 0,
    "batch_index": 0,
    "deals_found": [],
    "all_prices": [],
    "alerts_sent": 0,
    "alerts_skipped": 0,
    "errors": [],
    "log": [],
}

def log(tag, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "tag": tag, "msg": msg}
    state["log"].append(entry)
    if len(state["log"]) > 300:
        state["log"] = state["log"][-300:]
    print(f"[{ts}] [{tag}] {msg}")

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("TG", "Telegram not configured — skipping")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        if resp.status_code == 200:
            log("TG", "Alert sent!")
            return True
        log("TG", f"Failed: {resp.status_code}")
        return False
    except Exception as e:
        log("TG", f"Error: {str(e)}")
        return False

def get_tcg_price(card):
    try:
        headers = {}
        if POKEMONTCG_KEY:
            headers["X-Api-Key"] = POKEMONTCG_KEY
        resp = requests.get("https://api.pokemontcg.io/v2/cards",
                          headers=headers,
                          params={"q": card["q"], "pageSize": 5},
                          timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            log("API", "Rate limited — waiting 60s")
            time.sleep(60)
            return None
        if resp.status_code != 200:
            log("API", f"HTTP {resp.status_code} for {card['name']}")
            return None
        cards = resp.json().get("data", [])
        if not cards:
            log("API", f"No results for {card['name']} [{card['set']}]")
            return None
        best = None
        best_price = 0
        for c in cards:
            tcg = c.get("tcgplayer", {})
            prices = tcg.get("prices", {})
            for pt in ["holofoil", "reverseHolofoil", "normal", "1stEditionHolofoil", "unlimitedHolofoil"]:
                p = prices.get(pt, {})
                market = p.get("market", 0) or 0
                low = p.get("low", 0) or 0
                mid = p.get("mid", 0) or 0
                if market > best_price:
                    best_price = market
                    best = {
                        "market_price": round(market, 2),
                        "low_price": round(low, 2),
                        "mid_price": round(mid, 2),
                        "tcgplayer_url": tcg.get("url", ""),
                        "card_id": c.get("id", ""),
                        "set_name": c.get("set", {}).get("name", card["set"]),
                        "rarity": c.get("rarity", card.get("rarity", "")),
                        "image": c.get("images", {}).get("small", ""),
                    }
        return best if best and best["market_price"] > 0 else None
    except requests.exceptions.Timeout:
        log("API", f"Timeout: {card['name']}")
        return None
    except requests.exceptions.ConnectionError:
        log("API", f"Connection error: {card['name']}")
        return None
    except Exception as e:
        log("API", f"Error: {card['name']} — {str(e)[:80]}")
        return None

def should_alert(card, low_price):
    key = f"{card['name']}|{card['set']}|{card.get('rarity','')}"
    last = alerted_cards.get(key)
    if last is None:
        return True
    if low_price <= last - PRICE_CHANGE_THRESHOLD:
        return True
    return False

def mark_alerted(card, low_price):
    key = f"{card['name']}|{card['set']}|{card.get('rarity','')}"
    alerted_cards[key] = low_price

def run_hunt():
    if state["running"]:
        return
    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = state["batch_index"]
    end = min(start + BATCH_SIZE, len(TARGETS))
    batch = TARGETS[start:end]
    log("SYS", f"═══ CYCLE #{state['scan_count']} — cards {start+1}-{end}/{len(TARGETS)} ═══")
    new_deals = []
    new_prices = []
    for i, card in enumerate(batch):
        try:
            log("SCAN", f"[{start+i+1}/{len(TARGETS)}] {card['name']} [{card['rarity']}] — {card['set']}")
            pd = get_tcg_price(card)
            if not pd:
                time.sleep(1)
                continue
            state["total_cards_checked"] += 1
            log("PRICE", f"  → Mkt: ${pd['market_price']} | Low: ${pd['low_price']} | Mid: ${pd['mid_price']}")
            new_prices.append({"card": card["name"], "set": card["set"], "rarity": card.get("rarity",""),
                             "market": pd["market_price"], "low": pd["low_price"], "tcgplayer_url": pd.get("tcgplayer_url","")})
            market = pd["market_price"]
            low = pd["low_price"]
            if market > 0 and low > 0 and (market - low) / market >= THRESHOLD:
                disc = round((market - low) / market * 100, 1)
                profit = round(market - market * WHATNOT_FEE - low, 2)
                deal = {"card": card["name"], "set": card["set"], "rarity": card.get("rarity",""),
                       "market_price": market, "low_price": low, "discount_pct": disc,
                       "net_profit": profit, "tcgplayer_url": pd.get("tcgplayer_url",""),
                       "image": pd.get("image",""), "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                new_deals.append(deal)
                if should_alert(card, low):
                    log("DEAL", f"  🔥 ${low} is {disc}% off ${market} — ALERTING")
                    txt = (f"🔥 <b>DEAL FOUND</b>\n\n<b>{deal['card']}</b> [{deal['rarity']}]\n"
                          f"📦 {deal['set']}\n\n💰 Low: <b>${low}</b>\n📈 Market: ${market}\n"
                          f"🏷️ {disc}% below\n💵 Whatnot Profit: ~<b>${profit}</b>\n\n")
                    if deal.get("tcgplayer_url"):
                        txt += f'<a href="{deal["tcgplayer_url"]}">⚡ BUY ON TCGPLAYER</a>'
                    if send_telegram(txt):
                        state["alerts_sent"] += 1
                        mark_alerted(card, low)
                else:
                    state["alerts_skipped"] += 1
                    log("DEAL", f"  🔔 Already alerted at this price — skip")
            else:
                log("SCAN", f"  → No deal")
            time.sleep(2)
        except Exception as e:
            log("ERR", f"{card['name']}: {str(e)[:100]}")
            time.sleep(2)
    state["batch_index"] = end if end < len(TARGETS) else 0
    ex = {f"{p['card']}|{p['set']}|{p['rarity']}": p for p in state["all_prices"]}
    for p in new_prices:
        ex[f"{p['card']}|{p['set']}|{p['rarity']}"] = p
    state["all_prices"] = list(ex.values())
    ed = {f"{d['card']}|{d['set']}|{d['rarity']}": d for d in state["deals_found"]}
    for d in new_deals:
        ed[f"{d['card']}|{d['set']}|{d['rarity']}"] = d
    state["deals_found"] = list(ed.values())
    state["running"] = False
    log("SYS", f"═══ DONE — next batch at card {state['batch_index']+1}/{len(TARGETS)} ═══")

def schedule_loop():
    time.sleep(5)
    while True:
        try:
            run_hunt()
        except Exception as e:
            log("SYS", f"Error: {str(e)[:100]}")
            state["running"] = False
        wait = REFRESH_MINUTES * 60 if state["batch_index"] == 0 else 30
        if state["batch_index"] != 0:
            log("SYS", "More cards — next batch in 30s...")
        else:
            log("SYS", f"Full rotation done — next in {REFRESH_MINUTES} min...")
        time.sleep(wait)

def keep_alive():
    time.sleep(60)
    while True:
        try:
            requests.get("https://minty-cards-agent-1.onrender.com/ping", timeout=5)
        except:
            pass
        time.sleep(300)

@app.route("/")
def index():
    return jsonify({"name": "Minty Cards Agent v3.1", "cards": len(TARGETS),
                   "sets": len(set(t["set"] for t in TARGETS)),
                   "endpoints": ["/status","/prices","/deals","/log","/hunt","/test-telegram","/alerted","/reset-alerts"]})

@app.route("/ping")
def ping():
    return "pong"

@app.route("/status")
def get_status():
    return jsonify({"running": state["running"], "last_scan": state["last_scan"],
                   "scan_count": state["scan_count"], "total_checked": state["total_cards_checked"],
                   "batch": f"{state['batch_index']}/{len(TARGETS)}", "deals": len(state["deals_found"]),
                   "alerts_sent": state["alerts_sent"], "alerts_skipped": state["alerts_skipped"],
                   "cards_tracked": len(TARGETS), "refresh_min": REFRESH_MINUTES,
                   "threshold": f"{int(THRESHOLD*100)}%"})

@app.route("/prices")
def get_prices():
    return jsonify({"count": len(state["all_prices"]),
                   "prices": sorted(state["all_prices"], key=lambda x: x.get("market",0), reverse=True)})

@app.route("/deals")
def get_deals():
    return jsonify({"count": len(state["deals_found"]),
                   "deals": sorted(state["deals_found"], key=lambda x: x.get("net_profit",0), reverse=True)})

@app.route("/log")
def get_log():
    return jsonify(state["log"][-150:])

@app.route("/alerted")
def get_alerted():
    return jsonify({"tracked": len(alerted_cards), "cards": {k: f"${v}" for k,v in alerted_cards.items()}})

@app.route("/hunt")
def manual_hunt():
    if state["running"]:
        return jsonify({"status": "already running"})
    threading.Thread(target=run_hunt, daemon=True).start()
    return jsonify({"status": "started — check /log in 30s"})

@app.route("/test-telegram")
def test_tg():
    ok = send_telegram(f"🌿 <b>Minty Cards Agent v3.1</b>\n\n✅ Connected\n📊 {len(TARGETS)} cards / {len(set(t['set'] for t in TARGETS))} sets\n🔕 Smart alerts (once per deal)\n⏱️ Every {REFRESH_MINUTES} min")
    return jsonify({"status": "sent" if ok else "failed"})

@app.route("/reset-alerts")
def reset():
    alerted_cards.clear()
    return jsonify({"status": "cleared"})

log("SYS", f"═══ Minty Cards Agent v3.1 — {len(TARGETS)} cards / {len(set(t['set'] for t in TARGETS))} sets ═══")
log("SYS", f"Batch: {BATCH_SIZE} cards/cycle | Threshold: {int(THRESHOLD*100)}% | Refresh: {REFRESH_MINUTES}min")
log("SYS", f"Telegram: {'OK' if TELEGRAM_TOKEN else 'NOT SET'} | Smart alerts: on")
log("SYS", "pokemontcg.io → TCGPlayer prices. No scraping. No blocking.")

threading.Thread(target=schedule_loop, daemon=True).start()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
