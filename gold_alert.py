"""
Altın (XAU/USD, ons) bildirimi -> Telegram.

GitHub Actions bu script'i her 10 dakikada çalıştırır. Script kendisi karar verir:
- Saatlik özet: hafta içi, Türkiye saatiyle 09:00-23:00 arası, her saatin
  ilk çalışmasında gönderilir.
- Sert hareket alarmı: fiyat SON GÖNDERİLEN MESAJDAKİ fiyata göre ALERT_PCT
  (varsayılan %1) veya daha fazla oynarsa, saat/gün fark etmeksizin hemen gönderilir.
- "Gün başı": piyasa gün dönümünden (Türkiye saatiyle 01:00) sonraki ilk fiyat.

Sadece Python standart kütüphanesi kullanır, kurulum gerekmez.
Kaynak: önce goldprice.org; engellenirse gold-api.com yedeği.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
GRAM_PER_OUNCE = 31.1034768
TR_TZ = timezone(timedelta(hours=3))  # Türkiye yaz/kış saati uygulamıyor
SUMMARY_START, SUMMARY_END = 9, 23   # özet saatleri (dahil)
AYLAR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
         "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ALERT_PCT = float(os.environ.get("ALERT_PCT") or "1")

GOLDPRICE_ORG_URL = "https://data-asg.goldprice.org/dbXRates/USD,TRY"
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://goldprice.org/",
    "Origin": "https://goldprice.org",
}


# ---------- veri ----------

def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def from_goldprice_org():
    data = get_json(GOLDPRICE_ORG_URL, BROWSER_HEADERS)
    items = {i["curr"]: i for i in data["items"]}
    price = float(items["USD"]["xauPrice"])
    return price, float(items["TRY"]["xauPrice"]) / price, "goldprice.org"


def from_gold_api():
    h = {"User-Agent": "gold-alert-bot"}
    price = float(get_json(GOLD_API_URL, h)["price"])
    usdtry = float(get_json(GOLD_API_URL + "/TRY", h)["exchangeRate"])
    return price, usdtry, "gold-api.com"


def get_data():
    try:
        return from_goldprice_org()
    except Exception as e:
        print("goldprice.org alınamadı, yedeğe geçiliyor:", e, file=sys.stderr)
        return from_gold_api()


# ---------- yardımcılar ----------

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
    return "0" if s in ("-0", "") else s


def signed(x, decimals):
    s = num(x, decimals)
    return s if s.startswith("-") or s == "0" else "+" + s


def build_body(now, price, usdtry, open_price, open_gram):
    gram = price * usdtry / GRAM_PER_OUNCE
    change = price - open_price
    pct = change / open_price * 100 if open_price else 0.0
    arrow = "📈" if change >= 0 else "📉"
    when = f"{now.day} {AYLAR[now.month - 1]} {now:%H:%M}"
    return (
        f"ONS GOLD (XAU/USD) · 🕐 {when}\n"
        f"💰 Fiyat: {num(price, 4)} $\n"
        f"📊 Gün başı: {num(open_price, 4)} $\n"
        f"{arrow} Günlük Değişim: {signed(change, 2)} $ ({pct:+.2f}%)\n"
        f"💵 USD/TRY: {num(usdtry, 6)}\n"
        f"🇹🇷 Gram Altın: {gram:.0f} ₺ ({signed(gram - open_gram, 0)} ₺)"
    )


# ---------- ana akış ----------

def main(now=None):
    now = now or datetime.now(TR_TZ)
    price, usdtry, source = get_data()
    gram = price * usdtry / GRAM_PER_OUNCE
    state = load_state()

    # Gün başı: piyasanın gün dönümünden (TR 01:00 = New York 17:00) sonra
    # görülen ilk fiyat
    today = (now - timedelta(hours=1)).strftime("%Y-%m-%d")
    if state.get("day") != today:
        state.update(day=today, open_price=price, open_gram=gram)

    body = build_body(now, price, usdtry, state["open_price"], state["open_gram"])
    hour_key = now.strftime("%Y-%m-%d %H")
    in_window = now.weekday() < 5 and SUMMARY_START <= now.hour <= SUMMARY_END
    last_sent = state.get("last_sent_price")

    text = None
    if in_window and state.get("last_summary_hour") != hour_key:
        text = body
        state["last_summary_hour"] = hour_key
    elif last_sent:
        move = (price - last_sent) / last_sent * 100
        if abs(move) >= ALERT_PCT:
            icon = "📉" if move < 0 else "📈"
            text = (f"🚨 SERT HAREKET\n"
                    f"{icon} Son mesajdan beri: {signed(price - last_sent, 2)} $ "
                    f"({move:+.2f}%)\n\n" + body)

    if text:
        send_telegram(text)
        state["last_sent_price"] = price
        print("gönderildi:", source, text.replace("\n", " | "))
    else:
        if last_sent is None:
            state["last_sent_price"] = price  # alarm için başlangıç noktası
        print("mesaj yok:", source, price)

    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("hata:", e, file=sys.stderr)
        sys.exit(1)
