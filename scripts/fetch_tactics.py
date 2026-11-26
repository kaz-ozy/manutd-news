"""チームごとの「戦術コラム」記事(タイトルとリンクだけ)を集めて docs/tactics.json に保存する。

- 集め方は移籍ニュースと同じ(GoogleニュースのRSS)
- 記事の本文は取らない・要約しない
- チームを増やすときは、下の TEAMS に1行足すだけ
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from fetch_news import google_news, read_feed  # 同じフォルダの fetch_news.py の部品を使う

# チームID: (表示名, 日本語の検索語, 英語の検索語, タイトルに入っているべきチームの目印)
TEAMS = {
    "manutd": ("マンチェスター・U", "マンチェスター・ユナイテッド 戦術", "Manchester United tactics",
               ["man utd", "man united", "manchester united", "red devils", "pochettino", "old trafford",
                "マンu", "マンチェスター・u", "マンチェスター・ユナイテッド", "ポチェッティーノ", "ユナイテッド"]),
}

JA_KEYWORDS = ["戦術", "フォーメーション", "システム", "配置", "プレス", "ビルドアップ", "采配", "布陣", "戦い方", "分析"]
EN_KEYWORDS = ["tactic", "formation", "system", "pressing", "press", "build-up", "buildup", "shape",
               "analysis", "tactical", "back three", "back four", "low block", "high line", "possession"]

MAX_PER_TEAM = 100
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "tactics.json"


def is_tactics(title):
    t = title.lower()
    if any(k in title for k in JA_KEYWORDS):
        return True
    if re.search(r"\b\d-\d-\d(-\d)?\b", t):  # 4-3-3 のような並び方
        return True
    return any(re.search(r"\b" + re.escape(k), t) for k in EN_KEYWORDS)


def main():
    old = {}
    if OUTPUT.exists():
        try:
            old = json.loads(OUTPUT.read_text(encoding="utf-8")).get("teams", {})
        except json.JSONDecodeError:
            pass

    teams = {}
    for tid, (name, q_ja, q_en, marks) in TEAMS.items():
        got = []
        for lang, q in (("ja", q_ja), ("en", q_en)):
            try:
                items = read_feed("Google News", google_news(q, lang))
                print(f"[OK]   {name}({lang}): {len(items)}件取得")
                got += items
            except Exception as e:
                print(f"[失敗] {name}({lang}): {e}", file=sys.stderr)
        merged = {}
        for a in old.get(tid, {}).get("articles", []) + got:
            if is_tactics(a["title"]) and any(m in a["title"].lower() for m in marks):
                merged[a["url"]] = a
        arts = sorted(merged.values(), key=lambda a: a["date"], reverse=True)[:MAX_PER_TEAM]
        print(f"       戦術に関する記事: {len(arts)}件")
        teams[tid] = {"name": name, "articles": arts}

    OUTPUT.write_text(
        json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "teams": teams}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"保存しました: {OUTPUT}")


if __name__ == "__main__":
    main()
