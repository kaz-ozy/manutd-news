"""マンチェスター・ユナイテッドの移籍ニュースを集めて docs/news.json に保存する。

- RSS(更新情報の自動配信)から記事のタイトル・リンク・日付だけを取る
- 記事の本文は取らない(著作権のため)
- Pythonに最初から入っている機能だけを使う(追加インストール不要)
"""

import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

# ニュースの集め先: (表示する名前, RSSのURL)
def google_news(query, lang):
    q = urllib.parse.quote(query)
    if lang == "ja":
        return f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
    return f"https://news.google.com/rss/search?q={q}&hl=en-GB&gl=GB&ceid=GB:en"


FEEDS = [
    ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/teams/manchester-united/rss.xml"),
    ("The Guardian", "https://www.theguardian.com/football/manchester-united/rss"),
    ("Google News", google_news("マンチェスター・ユナイテッド 移籍", "ja")),
    ("Google News", google_news("Manchester United transfer", "en")),
]

# 移籍に関係する記事かどうかを見分けるキーワード
JA_KEYWORDS = ["移籍", "契約", "交渉", "獲得", "補強", "加入", "退団", "放出", "レンタル", "期限付き", "オファー", "完全移籍"]
EN_KEYWORDS = [
    "transfer", "signing", "sign", "signs", "signed", "deal", "bid", "loan",
    "contract", "fee", "target", "talks", "negotiat", "swap", "release clause",
    "agree", "medical", "offer", "linked", "move",
]

MAX_ARTICLES = 200  # 保存する記事の最大数
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "news.json"


def is_transfer_news(title):
    t = title.lower()
    if any(k in title for k in JA_KEYWORDS):
        return True
    # 英語は単語の頭が一致するものだけ(例: "assign" の "sign" には反応させない)
    return any(re.search(r"\b" + re.escape(k), t) for k in EN_KEYWORDS)


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (manutd-news-bot)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def read_feed(default_source, url):
    root = ET.fromstring(fetch(url))
    articles = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        date = parse_date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date"))
        source = default_source
        if default_source == "Google News":
            src = item.find("source")
            if src is not None and (src.text or "").strip():
                source = src.text.strip()
                # Googleニュースのタイトル末尾「 - 媒体名」を取り除く
                suffix = " - " + source
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
        if title and link and date:
            articles.append({"title": title, "url": link, "source": source, "date": date.isoformat()})
    return articles


def fetch_rates():
    """その日の為替レート(1ポンド・1ユーロ・1ドルが何円か)を無料サービスから取る"""
    rates = {}
    day = None
    for cur in ("GBP", "EUR", "USD"):
        data = json.loads(fetch(f"https://api.frankfurter.dev/v1/latest?base={cur}&symbols=JPY"))
        rates[cur] = data["rates"]["JPY"]
        day = data["date"]
    return {"date": day, "JPY_per": rates}


SYMBOLS = {"£": "GBP", "€": "EUR", "$": "USD"}
UNITS = {"m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def to_yen_text(n):
    """円の金額を「約156億円」「約5000万円」のように読みやすくする"""
    if n >= 1e8:
        v = n / 1e8
        return f"約{v:.0f}億円" if v >= 10 else f"約{v:.1f}億円".replace(".0億", "億")
    return f"約{round(n / 1e4):,}万円"


def find_price_yen(title, rates):
    """タイトル中の金額(£75m、€50m、5億ポンド など)を最初の1つだけ円に換算する。なければ None"""
    if not rates:
        return None
    m = re.search(r"([£€$])\s?(\d+(?:\.\d+)?)\s?(bn|billion|million|m)\b", title, re.I)
    if m:
        cur = SYMBOLS[m.group(1)]
        amount = float(m.group(2)) * UNITS[m.group(3).lower()]
        return to_yen_text(amount * rates["JPY_per"][cur])
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)(億|万)(ポンド|ユーロ|ドル)", title)
    if m:
        cur = {"ポンド": "GBP", "ユーロ": "EUR", "ドル": "USD"}[m.group(3)]
        amount = float(m.group(1).replace(",", "")) * (1e8 if m.group(2) == "億" else 1e4)
        return to_yen_text(amount * rates["JPY_per"][cur])
    return None  # 日本語の「100億円」はもともと円なので換算不要


def main():
    try:
        rates = fetch_rates()
        print(f"[OK]   為替レート: 1ポンド={rates['JPY_per']['GBP']}円 ({rates['date']})")
    except Exception as e:
        rates = None
        print(f"[失敗] 為替レート: {e}", file=sys.stderr)
    collected = []
    for name, url in FEEDS:
        try:
            items = read_feed(name, url)
            print(f"[OK]   {name}: {len(items)}件取得")
            collected += items
        except Exception as e:  # 1つ失敗しても他は続ける
            print(f"[失敗] {name}: {e}", file=sys.stderr)

    # 昨日までに保存した記事も引き継ぐ
    old = []
    if OUTPUT.exists():
        try:
            old = json.loads(OUTPUT.read_text(encoding="utf-8")).get("articles", [])
        except json.JSONDecodeError:
            pass

    merged = {}
    for a in old + collected:
        if is_transfer_news(a["title"]):
            merged[a["url"]] = a  # 同じURLは1件にまとめる
    print(f"移籍に関係する記事: {len(merged)}件(取得{len(collected)}件のうち)")

    articles = sorted(merged.values(), key=lambda a: a["date"], reverse=True)[:MAX_ARTICLES]
    # 金額は毎回、その日のレートで計算し直す(古い換算を残さない)
    for a in articles:
        a["price_jpy"] = find_price_yen(a["title"], rates)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"updated": datetime.now(timezone.utc).isoformat(), "rates": rates, "articles": articles},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"保存しました: {OUTPUT}")


if __name__ == "__main__":
    main()
