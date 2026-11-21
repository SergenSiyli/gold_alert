"""
Altın (XAU/USD, ons) fiyat bildirimi -> Telegram.
Her çalıştığında güncel fiyatı ve bir önceki kontrole göre değişimi gönderir.
Sadece Python standart kütüphanesi kullanır, kurulum gerekmez.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

API_URL = "https://api.gold-api.com/price/XAU"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


GOLDPRICE_ORG_URL = "https://data-asg.goldprice.org/dbXRates/USD"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://goldprice.org/",
    "Origin": "https://goldprice.org",
}


def price_from_goldprice_org():
    req = urllib.request.Request(GOLDPRICE_ORG_URL, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    item = data["items"][0]
    return float(item["xauPrice"]), data.get("date", ""), "goldprice.org"


def price_from_gold_api():
    req = urllib.request.Request(API_URL, headers={"User-Agent": "gold-alert-bot"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    return float(data["price"]), data.get("updatedAt", ""), "gold-api.com"


def get_price():
    # Önce goldprice.org; engellenirse (403 vb.) gold-api.com yedeği
    try:
        return price_from_goldprice_org()
    except Exception as e:
        print("goldprice.org alınamadı, yedeğe geçiliyor:", e, file=sys.stderr)
        return price_from_gold_api()


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


def main():
    price, updated, source = get_price()
    last = load_state().get("last_price")

    if last is None:
        line = "İlk kontrol"
    else:
        diff = price - last
        pct = diff / last * 100
        if diff > 0:
            line = f"📈 Arttı: +${diff:,.2f} (+%{pct:.2f})"
        elif diff < 0:
            line = f"📉 Düştü: -${abs(diff):,.2f} (-%{abs(pct):.2f})"
        else:
            line = "➖ Değişmedi"

    send_telegram(
        f"🟡 Altın (ons): ${price:,.2f}\n"
        f"{line}  (önceki kontrole göre)\n"
        f"Kaynak: {source}"
    )
    save_state({"last_price": price})
    print(price, line)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("hata:", e, file=sys.stderr)
        sys.exit(1)
