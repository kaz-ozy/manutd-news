"""監督・選手の名簿 docs/people.json を、毎日読み直して更新する。

- 選手: マンU公式サイト(ManUtd.com)の「Men's Team」ページ
- 監督: Wikipedia の API(公開データ向けの窓口)
- 読み取りに失敗したり、ページの形が変わって人数が少なすぎたりしたら、何も変えずに終わる
"""

import html
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PEOPLE = Path(__file__).resolve().parent.parent / "docs" / "people.json"
SQUAD_URL = "https://www.manutd.com/en/teams/mens-team"
WIKI_URL = ("https://en.wikipedia.org/w/api.php?action=parse&page=Manchester_United_F.C."
            "&prop=wikitext&format=json&formatversion=2")
CLUB = "マンチェスター・U"
SECTIONS = {"Forwards", "Midfielders", "Defenders", "Goalkeepers", "On Loan"}
# 監督の日本語表記(ここにない人は英語のまま表示する)
MANAGER_JA = {"Mauricio Pochettino": "マウリシオ・ポチェッティーノ"}
JST = timezone(timedelta(hours=9))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (manutd-news-bot)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def parse_squad(page):
    """公式ページから [(名前, レンタル中か)] を取り出す"""
    body = page[page.find("<body"):]
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
    tokens = [html.unescape(t).strip() for t in re.sub(r"<[^>]+>", "\n", body).split("\n")]
    tokens = [t for t in tokens if t]
    try:
        start = tokens.index("All")
        end = tokens.index("Principal Partners")
    except ValueError:
        return []
    players, section, group = [], None, []

    def flush():
        if group:
            players.append((" ".join(group), section == "On Loan"))
            group.clear()

    for t in tokens[start + 1:end]:
        if t in SECTIONS:
            flush()
            section = t
        elif t.isdigit() or t == "On Loan":
            flush()  # 背番号や「On Loan」の札は、選手と選手の区切り
        elif section:
            group.append(t)
    flush()
    return players


def key_of(name):
    w = norm(name).split()
    return (w[0], w[-1]) if len(w) > 1 else (w[0], None)


def match(page_name, aliases):
    pf, pl = key_of(page_name)
    for a in aliases:
        if not re.match(r"^[A-Za-zÀ-ɏ .'-]+$", a) or " " not in a:
            continue  # 日本語や名字だけの別名は照合に使わない
        af, al = key_of(a)
        if af == pf and (pl is None or al == pl):
            return True
    return False


def main():
    data = json.loads(PEOPLE.read_text(encoding="utf-8"))
    today = datetime.now(JST).strftime("%Y-%m-%d")
    changed = False

    # --- 選手 ---
    try:
        squad = parse_squad(get(SQUAD_URL))
    except Exception as e:
        squad = []
        print(f"[失敗] 公式サイト: {e}", file=sys.stderr)
    if len(squad) >= 20:
        old = data.get("players", [])
        new = []
        for name, loan in squad:
            prev = next((p for p in old if match(name, p["names"])), None)
            aliases = prev["names"] if prev else [name]  # 名字だけの別名は誤反応(例:Mee→meeting)が怖いので、新しい選手はフルネームだけ
            club = (prev["club"] if prev and "レンタル" in prev["club"] else "レンタル中") if loan else CLUB
            new.append({"names": aliases, "club": club})
        gone = [p["names"][0] for p in old if not any(match(n, p["names"]) for n, _ in squad)]
        added = [n for n, _ in squad if not any(match(n, p["names"]) for p in old)]
        print(f"[OK]   選手 {len(squad)}人(追加:{added or 'なし'} / 外れた:{gone or 'なし'})")
        data["players"] = new
        data["players_note"] = f"選手の出典: ManUtd.com(マンU公式)。{today}に確認。レンタル中の選手の貸出先は手入力です。"
    else:
        print(f"[スキップ] 選手が{len(squad)}人しか読めなかったため、名簿は変えません", file=sys.stderr)

    # --- 監督 ---
    try:
        wiki = json.loads(get(WIKI_URL))["parse"]["wikitext"]
        m = re.search(r"\|\s*manager\s*=\s*\[\[([^\]|]+)", wiki)
        if m:
            en = m.group(1).strip()
            ja = MANAGER_JA.get(en)
            data["manager"] = {"name": f"{ja}({en})" if ja else en, "checked": today, "source": "Wikipedia"}
            print(f"[OK]   監督: {data['manager']['name']}")
    except Exception as e:
        print(f"[失敗] 監督: {e}", file=sys.stderr)

    PEOPLE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
