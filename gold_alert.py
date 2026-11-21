"""
Altın (XAU/USD, ons) fiyat bildirimi -> Telegram.
Her çalıştığında ons fiyatı, önceki kapanış, günlük değişim, USD/TRY ve
gram altın (TL) bilgisini gönderir.
Sadece Python standart kütüphanesi kullanır, kurulum gerekmez.

Kaynak: önce goldprice.org; engellenirse gold-api.com yedeği.
Yedekte "önceki kapanış" bilgisi olmadığından, bir önceki günün son
fiyatı state.json'da tutulup kapanış olarak kullanılır.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
GRAM_PER_OUNCE = 31.1034768

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GOLDPRICE_ORG_URL = "https://data-asg.goldprice.org/dbXRates/USD,TRY"
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://goldprice.org/",
    "Origin": "https://goldprice.org",
}


def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def from_goldprice_org():
    data = get_json(GOLDPRICE_ORG_URL, BROWSER_HEADERS)
    items = {i["curr"]: i for i in data["items"]}
    usd, tr = items["USD"], items["TRY"]
    price = float(usd["xauPrice"])
    return {
        "price": price,
        "close": float(usd["xauClose"]),
        "usdtry": float(tr["xauPrice"]) / price,
        "source": "goldprice.org",
    }


def from_gold_api():
    h = {"User-Agent": "gold-alert-bot"}
    usd = get_json(GOLD_API_URL, h)
    tr = get_json(GOLD_API_URL + "/TRY", h)
    return {
        "price": float(usd["price"]),
        "close": None,  # bu kaynakta yok, state'ten doldurulacak
        "usdtry": float(tr["exchangeRate"]),
        "source": "gold-api.com",
    }


def get_data():
    try:
        return from_goldprice_org()
    except Exception as e:
        print("goldprice.org alınamadı, yedeğe geçiliyor:", e, file=sys.stderr)
        return from_gold_api()


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    urllib.request.urlopen(url, data=body, timeout=20).read()


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def num(x, decimals):
    """4744.37250 -> '4744.3725', -180.50 -> '-180.5'"""
    s = f"{x:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def main():
    d = get_data()
    price = d["price"]
    state = load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Yedek kaynak için kendi "önceki kapanış" kaydımız
    if state.get("day") != today:
        if state.get("last_price") is not None:
            state["prev_close"] = state["last_price"]
        state["day"] = today
    close = d["close"] or state.get("prev_close") or price

    change = price - close
    pct = change / close * 100 if close else 0.0
    gram_try = price * d["usdtry"] / GRAM_PER_OUNCE
    arrow = "📈" if change >= 0 else "📉"

    text = (
        "ONS GOLD (XAU/USD)\n"
        f"💰 Fiyat: {num(price, 4)} $\n"
        f"📊 Önceki Kapanış: {num(close, 4)} $\n"
        f"{arrow} Günlük Değişim: {num(change, 4)} $\n"
        f"({pct:+.2f}%)\n"
        f"💵 USD/TRY: {num(d['usdtry'], 6)}\n"
        f"🇹🇷 Gram Altın: {gram_try:.0f} ₺"
    )
    send_telegram(text)

    state["last_price"] = price
    save_state(state)
    print(d["source"], text.replace("\n", " | "))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("hata:", e, file=sys.stderr)
        sys.exit(1)
