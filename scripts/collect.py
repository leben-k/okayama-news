#!/usr/bin/env python3
"""岡山県に関する「事件・事故・火災・災害・催し(予定)」の見出しを集めて
data.json に保存し、index.html などを更新する。標準ライブラリのみ使用(pip不要)。

取得元(すべて無料):
  1. Google ニュース RSS(検索クエリごと)  … 見出し+リンクのみ使う
  2. 気象庁 防災情報 XML(岡山地方気象台の警報・土砂災害警戒情報など)
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

JST = timezone(timedelta(hours=9))
OUT = Path(__file__).resolve().parent.parent / "data.json"
KEEP_DAYS = 7           # これより古い取得分は消す
UA = "Mozilla/5.0 (compatible; okayama-news-digest/1.0)"

# 取得時刻(日本時間)。GitHub Actions の cron(.github/workflows/collect.yml)と合わせる。
# ページの「次回更新」表示にも使われる。
SLOTS = ["05:07", "11:37", "16:07", "19:07", "22:07"]

# ---- 検索クエリ(クエリ, 何日前まで) ----
NEWS_QUERIES = [
    ("岡山 事件", "2d"), ("岡山 逮捕", "2d"), ("岡山 事故", "2d"),
    ("岡山 火災", "2d"), ("岡山 災害", "2d"), ("岡山 大雨", "2d"),
    ("岡山 地震", "2d"), ("倉敷 事件 事故", "2d"), ("津山 事件 事故", "2d"),
    # 催し(事前予定)
    ("岡山 イベント 開催", "7d"), ("岡山 祭り", "7d"), ("岡山 花火大会", "7d"),
    ("岡山 フェスタ", "7d"), ("岡山 マラソン 開催", "7d"), ("岡山 コンサート 公演", "7d"),
]

JMA_FEED = "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"
JMA_PAGE = "https://www.jma.go.jp/bosai/warning/#area_type=offices&area_code=330000"
JMA_TITLES = ["気象特別警報・警報・注意報", "気象警報・注意報(H27)", "土砂災害警戒情報",
              "指定河川洪水予報", "記録的短時間大雨情報", "竜巻注意情報"]
JMA_WARNING_TITLES = ["気象特別警報・警報・注意報", "気象警報・注意報(H27)"]  # 中身に「警報」があるものだけ載せる


def _nfkc(t):
    return unicodedata.normalize("NFKC", t)

# ---- 地域(表示名: 見出しに含まれる語) ----
AREAS = {
    "岡山市": ["岡山市", "岡山駅", "岡山城", "後楽園", "表町", "奉還町", "問屋町", "西大寺"], "倉敷市": ["倉敷"], "津山市": ["津山"], "玉野市": ["玉野"],
    "笠岡市": ["笠岡"], "井原市": ["井原"], "総社市": ["総社"], "高梁市": ["高梁"],
    "新見市": ["新見市"], "備前市": ["備前市", "備前焼"], "瀬戸内市": ["瀬戸内市", "牛窓", "邑久"], "赤磐市": ["赤磐"],
    "真庭市": ["真庭"], "美作市": ["美作"], "浅口市": ["浅口"], "和気町": ["和気町"],
    "早島町": ["早島"], "里庄町": ["里庄"], "矢掛町": ["矢掛"], "新庄村": ["新庄村"],
    "鏡野町": ["鏡野"], "勝央町": ["勝央"], "奈義町": ["奈義"], "西粟倉村": ["西粟倉"],
    "久米南町": ["久米南"], "美咲町": ["美咲町"], "吉備中央町": ["吉備中央"],
}
# 見出しに地名が無くても岡山の記事とみなす配信元(必要に応じて編集)
LOCAL_SOURCES = ["山陽新聞", "山陽放送", "RSK", "岡山放送", "OHK", "テレビせとうち",
                 "瀬戸内海放送", "KSB", "津山朝日新聞"]

# ---- 種類の判定(上にあるものを優先) ----
KW = [
    ("火災", ["火災", "出火", "火事", "全焼", "半焼", "焼け跡", "山火事", "放火", "ぼや", "焼損"]),
    ("災害", ["地震", "震度", "台風", "大雨", "豪雨", "洪水", "土砂", "浸水", "冠水", "避難指示",
              "高潮", "津波", "竜巻", "落雷", "暴風", "大雪", "断水", "停電", "警報", "氾濫",
              "土石流", "特別警報"]),
    ("事件", ["逮捕", "容疑", "送検", "起訴", "詐欺", "窃盗", "強盗", "傷害", "殺人", "暴行",
              "行方不明", "遺体", "不審者", "立てこもり", "盗まれ", "盗んだ", "盗難", "押収",
              "指名手配", "わいせつ", "脅迫", "恐喝", "判決", "公判", "懲役", "被告"]),
    ("事故", ["事故", "衝突", "追突", "横転", "転落", "ひき逃げ", "はねられ", "はねた", "接触",
              "脱線", "溺れ", "水難", "遭難", "重傷", "巻き込まれ", "死亡", "搬送"]),
]
EVENT_KW = ["開催", "イベント", "まつり", "祭り", "花火大会", "フェス", "展示", "展覧会", "企画展",
            "特別展", "写真展", "作品展", "公演", "コンサート", "ライブ", "開幕", "フェア", "マルシェ",
            "催し", "ワークショップ", "上映", "発表会", "セミナー", "試食会", "芸術祭", "音楽祭", "映画祭",
            "収穫祭", "秋祭", "夏祭", "冬祭", "春祭", "大祭", "例祭", "献穀祭"]
# 日付がない催しでも、これから行われる予定だと分かる言葉(あると7日間、ないと1日間だけ載せる)
EVENT_FUTURE = ["開催へ", "開催予定", "開催します", "開催されます", "開催されるみたい", "開催決定", "開催に挑む",
                "上映へ", "上演へ", "発売開始", "受付", "募集", "初開催", "を開催！", "を開催!", "開催！", "開催!"]
EVENT_EXCLUDE = ["開催された", "開かれた", "行われた", "閉幕", "盛況", "にぎわ", "賑わ",
                 "優勝", "結果", "最優秀", "準決勝", "決勝", "表彰台", "受賞",
                 "名が参加", "人が参加", "名参加", "人参加", "密着", "凱旋", "実績", "寄付", "終了しました",
                 "開催しました", "行われました", "開かれました", "中止", "取り止め"]

# 岡山県以外の地名(見出しに岡山の地名がないときだけ、除外に使う)
OTHER_PLACES = [
    "香川", "高松", "まんのう", "丸亀", "坂出", "広島", "福山", "愛媛", "松山", "兵庫", "神戸", "姫路",
    "大阪", "京都", "東京", "神奈川", "横浜", "千葉", "埼玉", "北海道", "青森", "岩手", "宮城", "秋田",
    "山形", "福島", "茨城", "栃木", "群馬", "新潟", "富山", "石川", "福井", "山梨", "長野", "岐阜",
    "静岡", "愛知", "名古屋", "三重", "滋賀", "奈良", "和歌山", "鳥取", "島根", "山口", "徳島", "高知",
    "福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄",
]
OKAYAMA_WORDS = ["岡山"] + [w for words in AREAS.values() for w in words]


def classify(title):
    for cat, words in KW:
        if any(w in title for w in words):
            return cat
    if any(w in title for w in EVENT_KW) and not any(w in title for w in EVENT_EXCLUDE):
        return "催し"
    return None


def find_area(title):
    for name, words in AREAS.items():
        if any(w in title for w in words):
            return name
    return "県内・その他"


def clean_title(raw):
    """配信元の飾り(「 | 岡山・香川のニュース | …」「(KSB瀬戸内海放送)」「【画像】」など)を取り除く。"""
    t = re.sub(r"\s*\|\s.*$", "", raw)
    t = re.sub(r"\s*[（(]\d{4}年\d{1,2}月\d{1,2}日掲載[）)]\s*$", "", t)
    t = re.sub(r"\s*[（(][^（）()]*(放送|新聞|オンライン|NEWS|ニュース|テレビ)[^（）()]*[）)]\s*$", "", t)
    t = t.replace("【画像】", "")
    return t.strip()


def is_okayama(raw, title, source):
    # 配信元の飾りに入っている「岡山」は数えず、清書した見出しで判断する
    if any(w in title for w in OKAYAMA_WORDS):
        return True
    # 全国の「震度○ ○○」一覧は、岡山の地名がなければ岡山の記事ではない
    if "地震詳細" in raw or re.match(r"^震度\d", title):
        return False
    # 他県の地名があれば除外(RSKなどは香川のニュースも流すため)
    if any(p in title for p in OTHER_PLACES):
        return False
    return any(w in source or w in raw for w in LOCAL_SOURCES)


_WD = "月火水木金土日"


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def event_window(title, pub):
    """見出しから催しの日付(始まり, 終わり)を読み取る。読み取れなければ None。
    対応: 10月23日から25日 / 10月17日・18日 / 12月3日(木) / 【10/18(日)】 / 10日 / ３、４日 / 11月から"""
    t = unicodedata.normalize("NFKC", title)
    pd = pub.date()

    def resolve(m, d, y=None, wd=None):
        if y:
            return _mk(y, m, d)
        if wd is not None:       # 曜日が書いてあれば、曜日が合う年を選ぶ
            for yy in (pd.year, pd.year + 1):
                c = _mk(yy, m, d)
                if c and c.weekday() == wd and c >= pd - timedelta(days=180):
                    return c
        base = _mk(pd.year, m, d)
        if base and base < pd - timedelta(days=180):   # 半年以上前なら来年の話とみなす
            return _mk(pd.year + 1, m, d) or base
        return base

    dates = []

    def add_with_continuation(d0, rest):
        dates.append(d0)
        while True:   # 「・18日」「から25日」「〜25日」のつづき
            cm = re.match(r"(?:[・、,]|から|〜|～|~|-)(\d{1,2})(?![\d月/])日?", rest)
            if not cm:
                break
            dd = _mk(d0.year, d0.month, int(cm.group(1)))
            if dd:
                dates.append(dd)
            rest = rest[cm.end():]

    for m in re.finditer(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})(?:日|(?=[・、,]\d{1,2}日))(?:[(][月火水木金土日][)])?", t):
        wd = re.search(r"[(]([月火水木金土日])[)]", m.group(0))
        d0 = resolve(int(m.group(2)), int(m.group(3)), int(m.group(1)) if m.group(1) else None,
                     _WD.index(wd.group(1)) if wd else None)
        if d0:
            add_with_continuation(d0, t[m.end():])
    for m in re.finditer(r"(?<=[【〔\[])(\d{1,2})/(\d{1,2})(?:[(]([月火水木金土日])[)])?", t):   # 【10/18(日)】
        d0 = resolve(int(m.group(1)), int(m.group(2)), None, _WD.index(m.group(3)) if m.group(3) else None)
        if d0:
            add_with_continuation(d0, t[m.end():])
    if not dates:   # 「11月から」「12月上旬」
        for m in re.finditer(r"(\d{1,2})月(?:から|上旬|中旬|下旬)", t):
            mo = int(m.group(1))
            if 1 <= mo <= 12 and mo >= pd.month:
                first = _mk(pd.year, mo, 1)
                last = _mk(pd.year + (mo == 12), mo % 12 + 1, 1)
                if first and last:
                    dates += [first, last - timedelta(days=1)]
    if not dates:   # 「10日」「９日に」「３、４日」(月がないときは掲載月の日とみなす。掲載日より前の日は過去)
        for m in re.finditer(r"(?<![\d月/])(\d{1,2}(?:[・、,]\d{1,2})*)日(?![間前後以目あ])", t):
            for n in re.split(r"[・、,]", m.group(1)):
                dd = _mk(pd.year, pd.month, int(n))
                if dd:
                    dates.append(dd)
    if not dates:
        return None
    return min(dates), max(dates)


def norm_key(title):
    t = re.sub(r"【[^】]*】", "", title)
    t = re.sub(r"[\s\u3000、。・「」『』()()\-—–:：!！?？]", "", t)
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:12]


def fetch(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def make_item(raw, url, source, published, now):
    """条件に合えば記事の辞書を返す。合わなければ None。raw は配信元の飾りつきの見出し。"""
    title = clean_title(raw)
    if not title or not is_okayama(raw, title, source):
        return None
    cat = classify(title)
    if not cat:
        return None
    ed = end = ""
    if cat == "催し":
        win = event_window(title, published.astimezone(JST))
        if win:
            if win[1] < now.date():          # 終わった催しは載せない
                return None
            shown = win[0] if win[0] >= now.date() else win[1]
            ed, end = shown.isoformat(), win[1].isoformat()
        else:                                 # 日付がないものは、掲載から日がたったら外す
            age = now - published
            future = any(w in title for w in EVENT_FUTURE)
            if age > timedelta(days=7 if future else 1):
                return None
    return {
        "id": norm_key(title), "title": title, "raw": raw if raw != title else "",
        "url": url, "source": source,
        "cat": cat, "area": find_area(title),
        "published": published.astimezone(JST).strftime("%Y-%m-%dT%H:%M"),
        "event_date": ed, "event_end": end,
    }


def parse_google(data, now):
    root = ET.fromstring(data)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = (it.findtext("source") or "").strip()
        pub = it.findtext("pubDate")
        if not title or not link or not pub:
            continue
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        elif " - " in title:
            head, tail = title.rsplit(" - ", 1)
            title, src = head, src or tail
        try:
            published = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        item = make_item(title.strip(), link, src or "Googleニュース", published, now)
        if item:
            out.append(item)
    return out


def parse_jma(data, now):
    ns = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(data)
    out = []
    for e in root.findall(ns + "entry"):
        author = e.findtext(f"{ns}author/{ns}name") or ""
        if "岡山地方気象台" not in author:
            continue
        title = _nfkc((e.findtext(ns + "title") or "").strip())
        if title not in JMA_TITLES:
            continue
        content = " ".join((e.findtext(ns + "content") or "").split())
        body = re.sub(r"【[^】]*】", "", content)  # 見出しの【…気象警報・注意報】は除いて判定
        if title in JMA_WARNING_TITLES and "警報" not in body:
            continue  # 注意報だけのものは載せない
        try:
            pub = datetime.fromisoformat((e.findtext(ns + "updated") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - pub.astimezone(JST) > timedelta(days=2):
            continue
        text = "【岡山地方気象台】" + (content or title)
        if len(text) > 100:
            text = text[:99] + "…"
        out.append({
            "id": norm_key(text), "title": text, "url": JMA_PAGE, "source": "気象庁",
            "cat": "災害", "area": "県内・その他",
            "published": pub.astimezone(JST).strftime("%Y-%m-%dT%H:%M"), "event_date": "",
        })
    return out


# ---------------------------------------------------------------------------
# 表示用: 検索エンジンが読めるように、一覧を index.html にも直接書き込む
# (ブラウザでは JavaScript が同じ内容を描き直す)
# ---------------------------------------------------------------------------
CAT_ICON = {"事件": "i-siren", "事故": "i-car", "火災": "i-fire", "災害": "i-storm", "催し": "i-fireworks"}
WEEKDAY = "日月火水木金土"


def slot_of(hour):
    if 4 <= hour < 10:
        return "morning", "i-sunrise"
    if 10 <= hour < 17:
        return "day", "i-sun"
    if 17 <= hour < 21:
        return "eve", "i-sunset"
    return "night", "i-moon"


def _ic(icon_id):
    return f'<svg class="ic" aria-hidden="true"><use href="icons.svg#{icon_id}"/></svg>'


def render_static(items, updated):
    e = html.escape
    if not items:
        return ('<div class="msg">' + _ic("i-empty")
                + "まだ記事がありません。<br>最初の取得が終わると、ここに表示されます。</div>")
    groups = {}
    for it in items:
        groups.setdefault(it["fetched"], []).append(it)
    out = []
    for k, g in groups.items():
        dt = datetime.strptime(k, "%Y-%m-%dT%H:%M")
        cls, icon = slot_of(dt.hour)
        wd = WEEKDAY[(dt.weekday() + 1) % 7]
        new = '<span class="new">新着</span>' if k == updated else ""
        out.append(f'<section class="batch {cls}"><h2>{_ic(icon)}{dt.month}月{dt.day}日({wd}) '
                   f'{dt.hour}:{dt.minute:02d} 取得分{new}</h2>')
        for r in g:
            p = datetime.strptime(r["published"], "%Y-%m-%dT%H:%M")
            when = ""
            if r.get("event_date"):
                ed = datetime.strptime(r["event_date"], "%Y-%m-%d")
                when = f'<span class="pill when">{_ic("i-cal")}開催日 {ed.month}/{ed.day}</span>'
            url = r["url"] if r["url"].startswith(("http://", "https://")) else "#"
            out.append(
                f'<a class="item" href="{e(url, quote=True)}" target="_blank" rel="noopener noreferrer" data-cat="{e(r["cat"])}">'
                f'<span class="badge">{_ic(CAT_ICON.get(r["cat"], "i-news"))}</span>'
                f'<span class="body"><span class="meta"><span class="pill cat-pill">{e(r["cat"])}</span>'
                f'<span class="pill area">{_ic("i-pin")}{e(r["area"])}</span>{when}'
                f'<span>{p.month}/{p.day} {p.hour}:{p.minute:02d}</span>'
                f'<span class="src">{_ic("i-news")}{e(r["source"])}</span></span>'
                f'<span class="title">{e(r["title"])}</span></span></a>')
        out.append("</section>")
    return "".join(out)


def site_base():
    """公開URL(末尾 / つき)。環境変数 SITE_URL があればそれを使い、
    なければ GitHub Actions の GITHUB_REPOSITORY から GitHub Pages のURLを作る。"""
    url = os.environ.get("SITE_URL", "").strip()
    if not url:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo:
            owner, name = repo.split("/", 1)
            host = f"{owner.lower()}.github.io"
            url = f"https://{host}/" + ("" if name.lower() == host else name + "/")
    if url and not url.endswith("/"):
        url += "/"
    return url


def update_pages(items, updated, today):
    docs = OUT.parent
    base = site_base()
    index = docs / "index.html"
    if index.exists():
        t = index.read_text(encoding="utf-8")
        t = re.sub(r"<!--LIST-START-->.*?<!--LIST-END-->",
                   lambda m: "<!--LIST-START-->" + render_static(items, updated) + "<!--LIST-END-->",
                   t, flags=re.S)
        if base:
            seo = (f'<link rel="canonical" href="{base}"><meta property="og:url" content="{base}">')
            t = re.sub(r"<!--SEO-START-->.*?<!--SEO-END-->",
                       lambda m: "<!--SEO-START-->" + seo + "<!--SEO-END-->", t, flags=re.S)
        index.write_text(t, encoding="utf-8")
    if base:
        urls = [base] + [base + n for n in ("about.html",) if (docs / n).exists()]
        sm = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for u in urls:
            sm.append(f"  <url><loc>{html.escape(u)}</loc><lastmod>{today.isoformat()}</lastmod></url>")
        sm.append("</urlset>")
        (docs / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
        (docs / "robots.txt").write_text(
            f"User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n", encoding="utf-8")


def slot_is_due(now, updated):
    """予定の取得時刻(SLOTS)を過ぎていて、まだその分を取得していなければ True。
    GitHub の自動実行が遅れたり飛ばされたりしても、次に動いたときに取りこぼしを取り戻すための判定。"""
    last_due = None
    for offset in (0, -1):
        day = now.date() + timedelta(days=offset)
        for slot in SLOTS:
            t = datetime(day.year, day.month, day.day, int(slot[:2]), int(slot[3:]), tzinfo=JST)
            if t <= now and (last_due is None or t > last_due):
                last_due = t
    if last_due is None or not updated:
        return True
    try:
        done = datetime.strptime(updated, "%Y-%m-%dT%H:%M").replace(tzinfo=JST)
    except ValueError:
        return True
    return done < last_due


def main():
    now = datetime.now(JST)
    run = now.strftime("%Y-%m-%dT%H:%M")
    if os.environ.get("EVENT_NAME") == "schedule":   # 定期の確認のとき: 取得の時刻でなければ何もしない
        updated = ""
        try:
            updated = json.loads(OUT.read_text(encoding="utf-8")).get("updated", "")
        except (OSError, ValueError):
            pass
        if not slot_is_due(now, updated):
            print("NOT_DUE: 予定の取得時刻ではないか、取得ずみです")
            return
    found, ok = [], 0

    for q, when in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote(f"{q} when:{when}") + "&hl=ja&gl=JP&ceid=JP:ja")
        try:
            found += parse_google(fetch(url), now)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {q}: {e}", file=sys.stderr)
        time.sleep(1)

    try:
        found += parse_jma(fetch(JMA_FEED), now)
        ok += 1
    except Exception as e:  # noqa: BLE001
        print(f"[skip] 気象庁: {e}", file=sys.stderr)

    if ok == 0:
        print("取得元がすべて失敗しました", file=sys.stderr)
        sys.exit(1)

    old = {"items": []}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    items, seen = [], set()
    stored = sorted(old.get("items", []), key=lambda i: (i.get("fetched", ""), i.get("published", "")), reverse=True)
    for it in stored:   # 保存済みの記事にも最新のルールを当てはめ直す
        if it.get("source") != "気象庁":
            try:
                pub = datetime.strptime(it["published"], "%Y-%m-%dT%H:%M").replace(tzinfo=JST)
                fetched = it["fetched"]
            except (KeyError, ValueError):
                continue
            fixed = make_item(it.get("raw") or it["title"], it["url"], it["source"], pub, now)
            if not fixed:
                continue
            fixed["fetched"] = fetched
            it = fixed
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        items.append(it)
    added = 0
    for it in found:
        if it["id"] in seen:
            continue
        it["fetched"] = run
        items.append(it)
        seen.add(it["id"])
        added += 1

    limit = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M")
    items = [i for i in items if i["fetched"] >= limit]
    items.sort(key=lambda i: (i["fetched"], i["published"]), reverse=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated": run, "slots": SLOTS, "items": items},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    update_pages(items, run, now.date())
    print(f"取得元 {ok} 件成功 / 新規 {added} 件 / 保存 {len(items)} 件")


if __name__ == "__main__":
    main()
