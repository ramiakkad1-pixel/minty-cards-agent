import os
import time
import threading
import requests
import json
import base64
from flask import Flask, jsonify
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# MINTY CARDS ARBITRAGE AGENT v3.3
# ═══════════════════════════════════════════════════════════════
# v3.3 FIXES:
# 1. eBay searches include rarity (SAR/SIR/HR etc) — no more wrong cards
# 2. Price sanity: eBay price must be >50% of market (catches wrong listings)
# 3. Minimum $5 profit to alert (no $0.77 junk)
# 4. Dedup by card_id (no duplicate alerts for same physical card)
# 5. Silent first scan — populates prices without spamming Telegram
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__)

TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
POKEMONTCG_KEY     = os.environ.get("POKEMONTCG_KEY", "")
EBAY_CLIENT_ID     = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
THRESHOLD          = float(os.environ.get("THRESHOLD", "0.20"))
REFRESH_MINUTES    = int(os.environ.get("REFRESH_MINUTES", "10"))
MIN_MARKET_PRICE   = 10.00   # ignore cards under $10 market
MIN_PROFIT         = 5.00    # don't alert for less than $5 profit
EBAY_SANITY_FLOOR  = 0.50    # eBay price must be >50% of market (otherwise wrong card)
WHATNOT_FEE        = 0.15
REQUEST_TIMEOUT    = 15
BATCH_SIZE         = 10
PRICE_DROP_TO_REALERT = 2.00

# ── Rarity keywords for eBay search ──
RARITY_EBAY_KEYWORDS = {
    "SAR": "special art rare",
    "SIR": "special illustration rare",
    "HR":  "hyper rare gold",
    "IR":  "illustration rare",
    "UR":  "ultra rare full art",
    "Shiny": "shiny rare",
}

# ── Alert history (persisted to disk) ──
ALERT_FILE = "/tmp/minty_alerted.json"

def load_alerted():
    try:
        with open(ALERT_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_alerted(data):
    try:
        with open(ALERT_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass

alerted_cards = load_alerted()

# ── Track if first full rotation is done (silent scan) ──
first_rotation_done = False

# ── Dedup: track card_ids already seen this rotation ──
seen_card_ids = set()

# ── eBay OAuth ──
ebay_token_cache = {"token": None, "expires": 0}

def get_ebay_token():
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None
    now = time.time()
    if ebay_token_cache["token"] and ebay_token_cache["expires"] > now:
        return ebay_token_cache["token"]
    try:
        creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
        resp = requests.post("https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            ebay_token_cache["token"] = data["access_token"]
            ebay_token_cache["expires"] = now + data.get("expires_in", 7200) - 300
            log("EBAY", "OAuth token acquired")
            return data["access_token"]
        log("EBAY", f"OAuth failed: {resp.status_code}")
        return None
    except Exception as e:
        log("EBAY", f"OAuth error: {str(e)[:80]}")
        return None

def search_ebay(card_name, set_name, rarity, market_price):
    """Search eBay with rarity-specific keywords and sanity checks."""
    token = get_ebay_token()
    if not token:
        return None
    try:
        # Build rarity-aware search query
        rarity_kw = RARITY_EBAY_KEYWORDS.get(rarity, rarity)
        query = f"{card_name} {rarity_kw} {set_name} pokemon"

        resp = requests.get("https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params={"q": query, "limit": 10, "filter": "buyingOptions:{FIXED_PRICE},conditions:{NEW}",
                    "sort": "price"},
            timeout=REQUEST_TIMEOUT)

        if resp.status_code != 200:
            if resp.status_code == 429:
                log("EBAY", "Rate limited — waiting 10s")
                time.sleep(10)
            else:
                log("EBAY", f"Search error {resp.status_code}")
            return None

        items = resp.json().get("itemSummaries", [])
        if not items:
            return None

        # Find the cheapest item that passes sanity checks
        for item in items:
            price = float(item.get("price", {}).get("value", 0))
            if price <= 0:
                continue

            # SANITY CHECK 1: Price must be >50% of market
            # If eBay shows $14 for a $1400 card, it's the wrong card
            if price < market_price * EBAY_SANITY_FLOOR:
                continue

            # SANITY CHECK 2: Price must be >= $10
            if price < MIN_MARKET_PRICE:
                continue

            link = item.get("itemWebUrl", "")
            title = item.get("title", "")
            return {"price": round(price, 2), "url": link, "title": title}

        return None
    except Exception as e:
        log("EBAY", f"Error: {str(e)[:80]}")
        return None


# ══════════════════════════════════════════════════════════════
# 62 TARGET CARDS across 12 sets
# ══════════════════════════════════════════════════════════════
TARGETS = [
    # PRISMATIC EVOLUTIONS
    {"name": "Umbreon ex",  "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Umbreon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Sylveon ex",  "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Sylveon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Glaceon ex",  "set": "Prismatic Evolutions", "rarity": "SAR", "q": 'name:"Glaceon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Eevee ex",    "set": "Prismatic Evolutions", "rarity": "SIR", "q": 'name:"Eevee ex" set.name:"Prismatic Evolutions"'},
    {"name": "Espeon ex",   "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Espeon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Flareon ex",  "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Flareon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Vaporeon ex", "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Vaporeon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Jolteon ex",  "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Jolteon ex" set.name:"Prismatic Evolutions"'},
    {"name": "Leafeon ex",  "set": "Prismatic Evolutions", "rarity": "IR",  "q": 'name:"Leafeon ex" set.name:"Prismatic Evolutions"'},
    # PALDEAN FATES
    {"name": "Charizard ex","set": "Paldean Fates", "rarity": "HR",  "q": 'name:"Charizard ex" set.name:"Paldean Fates" rarity:"Hyper Rare"'},
    {"name": "Mew ex",      "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Mew ex" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Gardevoir ex","set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Gardevoir ex" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Charizard ex","set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Charizard ex" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Iono",        "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Iono" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Penny",       "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Penny" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Nemona",      "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Nemona" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Arven",       "set": "Paldean Fates", "rarity": "SIR", "q": 'name:"Arven" set.name:"Paldean Fates" rarity:"Special Illustration Rare"'},
    {"name": "Koraidon ex", "set": "Paldean Fates", "rarity": "HR",  "q": 'name:"Koraidon ex" set.name:"Paldean Fates" rarity:"Hyper Rare"'},
    {"name": "Miraidon ex", "set": "Paldean Fates", "rarity": "HR",  "q": 'name:"Miraidon ex" set.name:"Paldean Fates" rarity:"Hyper Rare"'},
    {"name": "Alakazam ex", "set": "Paldean Fates", "rarity": "SAR", "q": 'name:"Alakazam ex" set.name:"Paldean Fates"'},
    {"name": "Charmander",  "set": "Paldean Fates", "rarity": "Shiny","q": 'name:"Charmander" set.name:"Paldean Fates" rarity:"Shiny Rare"'},
    {"name": "Charmeleon",  "set": "Paldean Fates", "rarity": "Shiny","q": 'name:"Charmeleon" set.name:"Paldean Fates" rarity:"Shiny Rare"'},
    {"name": "Pikachu",     "set": "Paldean Fates", "rarity": "Shiny","q": 'name:"Pikachu" set.name:"Paldean Fates" rarity:"Shiny Rare"'},
    # DESTINED RIVALS
    {"name": "Team Rocket's Mewtwo ex","set": "Destined Rivals","rarity": "HR", "q": 'name:"Mewtwo" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Cynthia's Garchomp ex",  "set": "Destined Rivals","rarity": "HR", "q": 'name:"Garchomp" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Ethan's Ho-Oh ex",       "set": "Destined Rivals","rarity": "HR", "q": 'name:"Ho-Oh" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Team Rocket's Crobat ex","set": "Destined Rivals","rarity": "HR", "q": 'name:"Crobat" set.name:"Destined Rivals" rarity:"Hyper Rare"'},
    {"name": "Team Rocket's Mewtwo ex","set": "Destined Rivals","rarity": "SIR","q": 'name:"Mewtwo" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Cynthia's Garchomp ex",  "set": "Destined Rivals","rarity": "SIR","q": 'name:"Garchomp" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Giovanni", "set": "Destined Rivals","rarity": "SIR","q": 'name:"Giovanni" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Ariana",   "set": "Destined Rivals","rarity": "SIR","q": 'name:"Ariana" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Ethan's Adventure",      "set": "Destined Rivals","rarity": "SIR","q": 'name:"Ethan" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Moltres ex","set":"Destined Rivals","rarity": "SIR","q": 'name:"Moltres" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Team Rocket's Nidoking ex","set":"Destined Rivals","rarity":"SIR","q": 'name:"Nidoking" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    {"name": "Arven's Mabosstiff ex",  "set": "Destined Rivals","rarity": "SIR","q": 'name:"Mabosstiff" set.name:"Destined Rivals" rarity:"Special Illustration Rare"'},
    # 151
    {"name": "Charizard ex",      "set": "151","rarity": "SAR","q": 'name:"Charizard ex" set.name:"151" rarity:"Special Art Rare"'},
    {"name": "Mewtwo ex",         "set": "151","rarity": "SAR","q": 'name:"Mewtwo ex" set.name:"151"'},
    {"name": "Mew ex",            "set": "151","rarity": "SAR","q": 'name:"Mew ex" set.name:"151"'},
    {"name": "Alakazam ex",       "set": "151","rarity": "SAR","q": 'name:"Alakazam ex" set.name:"151"'},
    {"name": "Gengar ex",         "set": "151","rarity": "SAR","q": 'name:"Gengar ex" set.name:"151"'},
    {"name": "Blastoise ex",      "set": "151","rarity": "SAR","q": 'name:"Blastoise ex" set.name:"151"'},
    {"name": "Venusaur ex",       "set": "151","rarity": "SAR","q": 'name:"Venusaur ex" set.name:"151"'},
    {"name": "Erika's Invitation","set": "151","rarity": "SAR","q": 'name:"Erika" set.name:"151" rarity:"Special Art Rare"'},
    {"name": "Mewtwo ex",         "set": "151","rarity": "SIR","q": 'name:"Mewtwo ex" set.name:"151" rarity:"Special Illustration Rare"'},
    {"name": "Charizard ex",      "set": "151","rarity": "SIR","q": 'name:"Charizard ex" set.name:"151" rarity:"Special Illustration Rare"'},
    {"name": "Zapdos ex",         "set": "151","rarity": "IR", "q": 'name:"Zapdos ex" set.name:"151" rarity:"Illustration Rare"'},
    # SURGING SPARKS
    {"name": "Pikachu ex",  "set": "Surging Sparks","rarity": "SAR","q": 'name:"Pikachu ex" set.name:"Surging Sparks"'},
    {"name": "Raichu ex",   "set": "Surging Sparks","rarity": "SIR","q": 'name:"Raichu ex" set.name:"Surging Sparks"'},
    {"name": "Arceus ex",   "set": "Surging Sparks","rarity": "SIR","q": 'name:"Arceus ex" set.name:"Surging Sparks"'},
    # STELLAR CROWN
    {"name": "Terapagos ex","set": "Stellar Crown","rarity": "SIR","q": 'name:"Terapagos ex" set.name:"Stellar Crown"'},
    {"name": "Rayquaza ex", "set": "Stellar Crown","rarity": "SAR","q": 'name:"Rayquaza ex" set.name:"Stellar Crown"'},
    {"name": "Pecharunt ex","set": "Stellar Crown","rarity": "SAR","q": 'name:"Pecharunt ex" set.name:"Stellar Crown"'},
    # TWILIGHT MASQUERADE
    {"name": "Bloodmoon Ursaluna ex","set": "Twilight Masquerade","rarity": "SIR","q": 'name:"Bloodmoon Ursaluna ex" set.name:"Twilight Masquerade"'},
    {"name": "Ogerpon ex",  "set": "Twilight Masquerade","rarity": "SAR","q": 'name:"Ogerpon ex" set.name:"Twilight Masquerade"'},
    # OBSIDIAN FLAMES
    {"name": "Charizard ex","set": "Obsidian Flames","rarity": "SIR","q": 'name:"Charizard ex" set.name:"Obsidian Flames" rarity:"Special Illustration Rare"'},
    # PARADOX RIFT
    {"name": "Roaring Moon ex","set": "Paradox Rift","rarity": "SIR","q": 'name:"Roaring Moon ex" set.name:"Paradox Rift"'},
    {"name": "Iron Valiant ex","set": "Paradox Rift","rarity": "SAR","q": 'name:"Iron Valiant ex" set.name:"Paradox Rift"'},
    # TEMPORAL FORCES
    {"name": "Walking Wake ex","set": "Temporal Forces","rarity": "SIR","q": 'name:"Walking Wake ex" set.name:"Temporal Forces"'},
    {"name": "Iron Leaves ex", "set": "Temporal Forces","rarity": "SAR","q": 'name:"Iron Leaves ex" set.name:"Temporal Forces"'},
    # PALDEA EVOLVED
    {"name": "Iono",        "set": "Paldea Evolved","rarity": "SAR","q": 'name:"Iono" set.name:"Paldea Evolved" rarity:"Special Art Rare"'},
    # CROWN ZENITH
    {"name": "Giratina VSTAR","set": "Crown Zenith","rarity": "SAR","q": 'name:"Giratina VSTAR" set.name:"Crown Zenith"'},
]

# ── State ──
state = {"running": False, "last_scan": "never", "scan_count": 0, "total_cards_checked": 0,
         "batch_index": 0, "deals_found": [], "all_prices": [], "alerts_sent": 0,
         "alerts_skipped": 0, "ebay_deals": 0, "ebay_skipped_wrong_card": 0,
         "errors": [], "log": []}

def log(tag, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    state["log"].append({"time": ts, "tag": tag, "msg": msg})
    if len(state["log"]) > 300:
        state["log"] = state["log"][-300:]
    print(f"[{ts}] [{tag}] {msg}")

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=10)
        return resp.status_code == 200
    except:
        return False

def should_alert(key, price):
    last = alerted_cards.get(key)
    if last is None:
        return True
    if price <= last - PRICE_DROP_TO_REALERT:
        return True
    return False

def mark_alerted(key, price):
    alerted_cards[key] = price
    save_alerted(alerted_cards)

def get_tcg_price(card):
    try:
        headers = {}
        if POKEMONTCG_KEY:
            headers["X-Api-Key"] = POKEMONTCG_KEY
        resp = requests.get("https://api.pokemontcg.io/v2/cards", headers=headers,
                          params={"q": card["q"], "pageSize": 5}, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            log("API", "Rate limited — 60s")
            time.sleep(60)
            return None
        if resp.status_code != 200:
            return None
        cards = resp.json().get("data", [])
        if not cards:
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
                    best = {"market_price": round(market, 2), "low_price": round(low, 2),
                           "mid_price": round(mid, 2), "tcgplayer_url": tcg.get("url", ""),
                           "card_id": c.get("id", ""), "rarity": c.get("rarity", ""),
                           "image": c.get("images", {}).get("small", "")}
        return best if best and best["market_price"] > 0 else None
    except:
        return None

def process_card(card, silent_mode):
    """Process a single card. If silent_mode=True, log prices but don't send alerts."""
    global first_rotation_done

    log("SCAN", f"{card['name']} [{card['rarity']}] — {card['set']}")

    pd = get_tcg_price(card)
    if not pd:
        time.sleep(1)
        return

    state["total_cards_checked"] += 1
    market = pd["market_price"]
    low = pd["low_price"]
    card_id = pd.get("card_id", "")

    log("PRICE", f"  Mkt: ${market} | Low: ${low} | Mid: ${pd['mid_price']}")

    # Skip cards under minimum market price
    if market < MIN_MARKET_PRICE:
        log("SCAN", f"  Skip (${market} < ${MIN_MARKET_PRICE} min)")
        time.sleep(2)
        return

    # Dedup: if we already processed this exact card_id this rotation, skip
    if card_id and card_id in seen_card_ids:
        log("SCAN", f"  Skip (card_id {card_id} already scanned)")
        time.sleep(2)
        return
    if card_id:
        seen_card_ids.add(card_id)

    # Store price
    pk = f"{card['name']}|{card['set']}|{card.get('rarity','')}"
    existing = {f"{p['card']}|{p['set']}|{p['rarity']}": p for p in state["all_prices"]}
    existing[pk] = {"card": card["name"], "set": card["set"], "rarity": card.get("rarity",""),
                  "market": market, "low": low, "tcgplayer_url": pd.get("tcgplayer_url","")}
    state["all_prices"] = list(existing.values())

    # ── TCGPlayer deal check ──
    if market > 0 and low > 0 and (market - low) / market >= THRESHOLD:
        profit = round(market - market * WHATNOT_FEE - low, 2)
        disc = round((market - low) / market * 100, 1)

        if profit >= MIN_PROFIT:
            tcg_key = f"TCG|{pk}"
            ed = {f"{d['card']}|{d['set']}|{d['rarity']}|{d.get('source','')}": d for d in state["deals_found"]}
            ed[f"{pk}|TCGPlayer"] = {"card": card["name"], "set": card["set"], "rarity": card.get("rarity",""),
                 "market_price": market, "low_price": low, "discount_pct": disc,
                 "net_profit": profit, "source": "TCGPlayer",
                 "url": pd.get("tcgplayer_url",""), "found_at": datetime.now().strftime("%H:%M:%S")}
            state["deals_found"] = list(ed.values())

            if not silent_mode and should_alert(tcg_key, low):
                log("DEAL", f"  🔥 TCG: ${low} ({disc}% off) profit ${profit} — ALERTING")
                txt = (f"🔥 <b>DEAL — TCGPlayer</b>\n\n<b>{card['name']}</b> [{card.get('rarity','')}]\n"
                      f"📦 {card['set']}\n\n💰 Low: <b>${low}</b>\n📈 Market: ${market}\n"
                      f"🏷️ {disc}% below\n💵 Profit: ~<b>${profit}</b>\n\n")
                if pd.get("tcgplayer_url"):
                    txt += f'<a href="{pd["tcgplayer_url"]}">⚡ BUY ON TCGPLAYER</a>'
                if send_telegram(txt):
                    state["alerts_sent"] += 1
                mark_alerted(tcg_key, low)
            elif silent_mode:
                # During silent scan, still mark as alerted to prevent burst later
                mark_alerted(tcg_key, low)
                log("SCAN", f"  🔇 Deal found (silent mode — marking without alert)")
            else:
                state["alerts_skipped"] += 1
                log("SCAN", f"  🔔 Already alerted — skip")
        else:
            log("SCAN", f"  Skip TCG (profit ${profit} < ${MIN_PROFIT} min)")
    else:
        log("SCAN", f"  No TCG deal")

    # ── eBay deal check ──
    if EBAY_CLIENT_ID:
        ebay = search_ebay(card["name"], card["set"], card.get("rarity", ""), market)
        if ebay and ebay["price"] > 0 and market > 0:
            ebay_disc = (market - ebay["price"]) / market
            ebay_profit = round(market - market * WHATNOT_FEE - ebay["price"], 2)

            if ebay_disc >= THRESHOLD and ebay_profit >= MIN_PROFIT:
                disc_pct = round(ebay_disc * 100, 1)
                ebay_key = f"EBAY|{pk}"

                ed = {f"{d['card']}|{d['set']}|{d['rarity']}|{d.get('source','')}": d for d in state["deals_found"]}
                ed[f"{pk}|eBay"] = {"card": card["name"], "set": card["set"], "rarity": card.get("rarity",""),
                     "market_price": market, "low_price": ebay["price"], "discount_pct": disc_pct,
                     "net_profit": ebay_profit, "source": "eBay",
                     "url": ebay["url"], "found_at": datetime.now().strftime("%H:%M:%S")}
                state["deals_found"] = list(ed.values())

                if not silent_mode and should_alert(ebay_key, ebay["price"]):
                    log("DEAL", f"  🛒 eBay: ${ebay['price']} ({disc_pct}% off) profit ${ebay_profit}")
                    txt = (f"🛒 <b>DEAL — eBay</b>\n\n<b>{card['name']}</b> [{card.get('rarity','')}]\n"
                          f"📦 {card['set']}\n\n💰 eBay BIN: <b>${ebay['price']}</b>\n"
                          f"📈 Market: ${market}\n🏷️ {disc_pct}% below\n"
                          f"💵 Profit: ~<b>${ebay_profit}</b>\n\n"
                          f'<a href="{ebay["url"]}">⚡ BUY ON EBAY</a>')
                    if send_telegram(txt):
                        state["alerts_sent"] += 1
                        state["ebay_deals"] += 1
                    mark_alerted(ebay_key, ebay["price"])
                elif silent_mode:
                    mark_alerted(ebay_key, ebay["price"])
                else:
                    state["alerts_skipped"] += 1
            else:
                log("SCAN", f"  eBay skip (profit ${ebay_profit} < ${MIN_PROFIT})")
        time.sleep(1)

    time.sleep(2)

def run_hunt():
    global first_rotation_done, seen_card_ids

    if state["running"]:
        return
    state["running"] = True
    state["scan_count"] += 1
    state["last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = state["batch_index"]
    end = min(start + BATCH_SIZE, len(TARGETS))
    batch = TARGETS[start:end]

    silent = not first_rotation_done
    mode_label = "SILENT" if silent else "LIVE"
    log("SYS", f"═══ CYCLE #{state['scan_count']} [{mode_label}] — cards {start+1}-{end}/{len(TARGETS)} ═══")

    for i, card in enumerate(batch):
        try:
            process_card(card, silent_mode=silent)
        except Exception as e:
            log("ERR", f"{card['name']}: {str(e)[:100]}")
            time.sleep(2)

    # Update batch index
    next_idx = end if end < len(TARGETS) else 0
    state["batch_index"] = next_idx

    # If we just completed a full rotation
    if next_idx == 0:
        if not first_rotation_done:
            first_rotation_done = True
            log("SYS", f"✅ Silent scan complete — {len(alerted_cards)} deals pre-marked. Alerts now LIVE.")
            send_telegram(f"🌿 <b>Minty Cards Agent v3.3</b>\n\n✅ Initial scan complete\n📊 {len(TARGETS)} cards / {len(set(t['set'] for t in TARGETS))} sets\n💰 {len(state['all_prices'])} prices loaded\n🔕 {len(alerted_cards)} deals pre-marked\n\nAlerts now LIVE — only NEW deals will notify.")
        seen_card_ids.clear()

    state["running"] = False
    log("SYS", f"═══ DONE — next at card {state['batch_index']+1}/{len(TARGETS)} ═══")

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
            log("SYS", "More cards — 30s...")
        else:
            log("SYS", f"Waiting {REFRESH_MINUTES} min...")
        time.sleep(wait)

def keep_alive():
    time.sleep(60)
    while True:
        try:
            requests.get("https://minty-cards-agent-1.onrender.com/ping", timeout=5)
        except:
            pass
        time.sleep(300)

# ── Routes ──
@app.route("/")
def index():
    return jsonify({"name": "Minty Cards Agent v3.3", "cards": len(TARGETS),
                   "sets": len(set(t["set"] for t in TARGETS)),
                   "ebay": "connected" if EBAY_CLIENT_ID else "not configured",
                   "fixes": ["rarity-aware eBay search", "price sanity >50%", "min $5 profit",
                            "card_id dedup", "silent first scan"]})

@app.route("/ping")
def ping():
    return "pong"

@app.route("/status")
def get_status():
    return jsonify({"running": state["running"], "last_scan": state["last_scan"],
                   "scan_count": state["scan_count"], "total_checked": state["total_cards_checked"],
                   "batch": f"{state['batch_index']}/{len(TARGETS)}",
                   "mode": "LIVE" if first_rotation_done else "SILENT (first scan)",
                   "deals": len(state["deals_found"]),
                   "alerts_sent": state["alerts_sent"], "alerts_skipped": state["alerts_skipped"],
                   "ebay_deals": state["ebay_deals"],
                   "ebay_wrong_card_filtered": state["ebay_skipped_wrong_card"],
                   "ebay": "connected" if EBAY_CLIENT_ID else "not configured",
                   "cards_tracked": len(TARGETS), "threshold": f"{int(THRESHOLD*100)}%",
                   "min_profit": f"${MIN_PROFIT}"})

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
    return jsonify({"status": "started"})

@app.route("/test-telegram")
def test_tg():
    ok = send_telegram(f"🌿 <b>Minty Cards Agent v3.3</b>\n\n📊 {len(TARGETS)} cards / {len(set(t['set'] for t in TARGETS))} sets\n{'✅ eBay connected' if EBAY_CLIENT_ID else '❌ eBay not set'}\n🔕 Silent first scan\n💰 Min profit: ${MIN_PROFIT}\n🛡️ eBay sanity: >50% of market")
    return jsonify({"status": "sent" if ok else "failed"})

@app.route("/reset-alerts")
def reset():
    alerted_cards.clear()
    save_alerted(alerted_cards)
    return jsonify({"status": "cleared"})

# ── Startup ──
log("SYS", f"═══ Minty Cards Agent v3.3 — {len(TARGETS)} cards / {len(set(t['set'] for t in TARGETS))} sets ═══")
log("SYS", f"Threshold: {int(THRESHOLD*100)}% | Min profit: ${MIN_PROFIT} | Min market: ${MIN_MARKET_PRICE}")
log("SYS", f"eBay: {'connected' if EBAY_CLIENT_ID else 'NOT SET'} | eBay sanity: price must be >{int(EBAY_SANITY_FLOOR*100)}% of market")
log("SYS", f"Telegram: {'OK' if TELEGRAM_TOKEN else 'NOT SET'}")
log("SYS", f"Alert history: {len(alerted_cards)} pre-loaded from disk")
log("SYS", "🔇 First full rotation will be SILENT (no alerts) to pre-mark existing deals")
log("SYS", "After first rotation: only NEW deals or $2+ price drops will alert")

threading.Thread(target=schedule_loop, daemon=True).start()
threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
