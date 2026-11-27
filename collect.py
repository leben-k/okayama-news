#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
岡山関係情報（事件・事故・災害・催し）
  - 岡山県・岡山市の公式RSS、Googleニュース(RSS)、Bingニュース(RSS)、気象庁(岡山地方気象台)から見出しを集める
  - data.json に履歴を保存する
  - site/ フォルダに公開用ページ(index.html など)を作る
外部ライブラリは使いません(Python標準のみ)。
"""
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# ====================== 調整できるところ ======================
BASE_URL = "https://leben-k.github.io/okayama-news/"
SITE_TITLE = "岡山の事件・事故・災害・催し"
OPERATOR = "地域情報室"
UPDATE_TIMES_TEXT = "随時"  # 表示用の文言(時刻はcollect.ymlのcronで決まります)

DATA_FILE = "data.json"
SITE_DIR = "site"
KEEP_DAYS = 7          # 事件・事故・火災・災害を残す日数
KEEP_DAYS_EVENT = 7    # 催しを残す日数
MAX_ITEMS = 800

# 検索ワード(Googleニュース)。ORで複数語をまとめられます。
NEWS_QUERIES = [
    "岡山 事件 逮捕",
    "岡山 事故",
    "岡山 火災 火事",
    "岡山 災害 大雨 地震 台風",
    "岡山 イベント 開催",
    "岡山 祭り 花火",
    "岡山 フェスタ マルシェ",
]
CITY_QUERIES = [
    "岡山市", "倉敷市", "津山市", "玉野市", "笠岡市", "井原市", "総社市", "高梁市",
    "新見市", "備前市", "瀬戸内市", "赤磐市", "真庭市", "美作市", "浅口市",
]  # それぞれ「○○ 事件 OR 事故 OR 火災 OR 催し」で検索します

# ---- Googleニュース以外の取得元 ------------------------------
USE_GOOGLE = True          # Googleニュース(RSS)を使う
USE_BING = True           # Bingニュース(Googleとは別の検索エンジンのニュース)も使う
USE_OUTLET_QUERIES = True  # 新聞社・放送局のサイトごとに、Googleニュースで探し直す
USE_YAHOO_SEARCH = False   # Yahoo!ニュース検索(RSSで返ってこないときは、自動で見送ります)
# 新聞社・放送局のサイト。(サイトのアドレス, 検索に足す言葉)。「site:」で、そのサイトの記事だけを探します。
OUTLET_SITES = [
    ("sanyonews.jp", ""),               # 山陽新聞
    ("news.web.nhk", "岡山"),            # NHK(全国版なので「岡山」を足す)
    ("news.ksb.co.jp", ""),             # KSB瀬戸内海放送
    ("rsk.co.jp", ""),                  # RSK山陽放送
    ("ohk.co.jp", ""),                  # OHK岡山放送
    ("yomiuri.co.jp/local/okayama", ""),  # 読売新聞(岡山)
    ("mainichi.jp/okayama", ""),        # 毎日新聞(岡山)
    ("asahi.com/area/okayama", ""),     # 朝日新聞(岡山)
]
# 自分で足したいRSS(市役所・警察などの公式RSS)。 ("表示する名前", "RSSのアドレス") の形で書きます。
# 見出しに岡山の地名があり、事件・事故などの言葉が入っているものだけが採用されます。
# ("表示する名前", "RSSのアドレス", "市町村名(わからなければ県内・その他)") の形で書きます。
# 公式RSSは、岡山の情報であることがはっきりしているので、見出しに地名がなくても採用します。
EXTRA_FEEDS = [
    ("岡山県(緊急情報)", "https://www.pref.okayama.jp/rss/10/list3.xml", "県内・その他"),
    ("岡山県(新着情報)", "https://www.pref.okayama.jp/rss/10/list1.xml", "県内・その他"),
    ("岡山県(報道発表)", "https://www.pref.okayama.jp/rss/10/site-3.xml", "県内・その他"),
    ("岡山市(緊急情報)", "https://www.city.okayama.jp/rss/rss_emergency.xml", "岡山市"),
    ("岡山市(観光・イベント)", "https://www.city.okayama.jp/rss/rss_topics_kankou.xml", "岡山市"),
    ("岡山市(くらしの情報)", "https://www.city.okayama.jp/rss/rss_topics_kurashi.xml", "岡山市"),
]
# ==============================================================

JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; okayama-news-collector; +" + BASE_URL + ")"

# 市町村(表示名 -> 文中で探す言葉)
MUNICIPALITIES = [
    ("岡山市", ["岡山市"]),
    ("倉敷市", ["倉敷"]),
    ("津山市", ["津山"]),
    ("玉野市", ["玉野"]),
    ("笠岡市", ["笠岡"]),
    ("井原市", ["井原"]),
    ("総社市", ["総社"]),
    ("高梁市", ["高梁"]),
    ("新見市", ["新見"]),
    ("備前市", ["備前市"]),
    ("瀬戸内市", ["瀬戸内市"]),
    ("赤磐市", ["赤磐"]),
    ("真庭市", ["真庭"]),
    ("美作市", ["美作"]),
    ("浅口市", ["浅口"]),
    ("和気町", ["和気町"]),
    ("早島町", ["早島"]),
    ("里庄町", ["里庄"]),
    ("矢掛町", ["矢掛"]),
    ("新庄村", ["新庄村"]),
    ("鏡野町", ["鏡野"]),
    ("勝央町", ["勝央"]),
    ("奈義町", ["奈義"]),
    ("西粟倉村", ["西粟倉"]),
    ("久米南町", ["久米南"]),
    ("美咲町", ["美咲町"]),
    ("吉備中央町", ["吉備中央"]),
]
REGION_OTHER = "県内・その他"

# 市町村名以外で「岡山県内」とわかる言葉(地区名・警察署・海上保安部・名所・行事など)。
# 見出しにこれらが入っていれば、「岡山」の文字がなくても岡山の記事として扱います。
# 山陽新聞などの配信元だけで岡山とみなすことはしません(全国ニュースが混ざるため)。
OKAYAMA_PLACE_WORDS = [
    "岡山", "おかやま", "備前", "備中", "美作", "吉備", "牛窓", "邑久", "長船", "日生", "西大寺",
    "児島", "水島", "玉島", "庭瀬", "足守", "牛窓", "湯郷", "蒜山", "後楽園", "吉備津", "鷲羽山",
    "大谷焼", "つやま", "会陽", "ファジアーノ", "シーガルズ", "楽天生命パーク", "玉島",
    "倉敷", "津山", "玉野", "笠岡", "井原", "総社", "高梁", "新見", "赤磐", "真庭", "浅口", "和気", "早島",
    "里庄", "矢掛", "新庄村", "鏡野", "勝央", "奈義", "西粟倉", "久米南", "美咲",
    "県民局",
]

CATS = ["事件", "事故", "火災", "災害", "催し"]
CAT_ICON = {"事件": "i-siren", "事故": "i-car", "火災": "i-fire", "災害": "i-storm", "催し": "i-fireworks"}

RE_FIRE = re.compile(r"火災|火事|全焼|半焼|延焼|焼死|山火事|炎上")
RE_DISASTER = re.compile(
    r"地震|震度|大雨|豪雨|台風|警報|注意報|土砂|洪水|浸水|氾濫|避難|高潮|竜巻|落雷|停電|断水|"
    r"運転見合わせ|噴火|津波|被災|防災|冠水|通行止め|熱中症"
)
RE_ACCIDENT = re.compile(r"事故|衝突|横転|転落|追突|はねられ|重体|遭難|溺れ|水難|墜落|巻き込まれ")
RE_CRIME = re.compile(
    r"逮捕|容疑|送検|詐欺|窃盗|盗ん|盗難|殺|強盗|暴行|傷害|行方不明|保護|脅迫|摘発|不審者|薬物|"
    r"あおり運転|飲酒運転|虐待|クマ|熊|出没|わいせつ|性的|立てこもり|発砲|刺さ|刺し|被害"
)
RE_EVENT = re.compile(
    r"開催|まつり|祭|イベント|フェス|フェア|展|公演|ライブ|花火|マラソン|大会|コンサート|マルシェ|"
    r"開幕|発売|ミュージカル|上演|講演|セミナー|体験|収穫"
)
# 岡山以外の地名(岡山の語が無い記事を除外するために使う)
RE_OTHER_AREA = re.compile(
    r"香川|高松|愛媛|松山|広島県|広島市|兵庫|神戸|鳥取|島根|山口県|徳島|高知|大阪|京都|東京|北海道|"
    r"福岡|熊本|宮崎|鹿児島|沖縄|能登|石川|三陸|岩手|宮古島|奄美|伊豆|台湾|韓国|中国|"
    r"愛知|名古屋|静岡|埼玉|千葉|神奈川|横浜|新潟|長野|群馬|栃木|茨城|宮城|仙台|福島|山形|秋田|青森|"
    r"富山|福井|滋賀|奈良|和歌山|三重県|岐阜|山梨県|佐賀|長崎|大分|尼崎|堺市|札幌|"
    r"エジプト|米国|アメリカ|ロシア|ウクライナ|欧州|ヨーロッパ|イスラエル|ガザ|イラン|インド|タイ[でのにを]|ベトナム|"
    r"フィリピン|インドネシア|トルコ|ブラジル|カナダ|豪州|オーストラリア|英国|イギリス|フランス|ドイツ|イタリア|"
    r"スペイン|アフリカ|中東|北朝鮮|ミャンマー|パキスタン|ネパール|メキシコ|アルゼンチン|ケニア|ナイジェリア"
)
# 配信元だけで岡山とみなす仕組みはやめました(山陽新聞などにも全国ニュースがあるため)。

# 収集する時刻(日本時間)。取りこぼしたら、次の30分ごとの確認で取り戻します
SLOTS = [(h, 0) for h in range(24)]  # 毎時0分(1時間ごと)

JMA_FEED = "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"
JMA_LINK = "https://www.jma.go.jp/bosai/warning/#area_type=offices&area_code=330000"
WEEK = ["月", "火", "水", "木", "金", "土", "日"]


# ------------------------------------------------------------
# 取得
# ------------------------------------------------------------
def fetch_bytes(url, tries=3):
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


def gnews_url(query):
    q = urllib.parse.urlencode(
        {"q": query + " when:7d", "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    )
    return "https://news.google.com/rss/search?" + q


def parse_gnews(data):
    """Googleニュースを読み、[{title, link, pub, source}] を返す"""
    out = []
    root = ET.fromstring(data)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub_s = it.findtext("pubDate") or ""
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None and src_el.text else ""
        if not title or not link or not pub_s:
            continue
        try:
            pub = parsedate_to_datetime(pub_s).astimezone(JST)
        except Exception:  # noqa: BLE001
            continue
        out.append({"title": title, "link": link, "pub": pub, "source": source})
    return out


def collect_gnews():
    queries = list(NEWS_QUERIES)
    for c in CITY_QUERIES:
        queries.append(c + " 事件 OR 事故 OR 火災 OR 催し")
    raws, ok, ng = [], 0, 0
    for q in queries:
        try:
            raws.extend(parse_gnews(fetch_bytes(gnews_url(q))))
            ok += 1
        except Exception as e:  # noqa: BLE001
            ng += 1
            print("  取得失敗:", q, "->", e)
        time.sleep(0.7)
    print("Googleニュース: 成功 %d / 失敗 %d / 見出し %d" % (ok, ng, len(raws)))
    return raws, ok


# ---- Googleニュース以外(Bing・Yahoo・公式RSSなど) ----
def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def unwrap_link(link):
    """Bingの中継アドレスから、元の記事のアドレスを取り出す"""
    if "bing.com/news/apiclick" in link:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        if q.get("url"):
            return q["url"][0]
    return link


def parse_feed(data, hint=""):
    """RSS 2.0 / Atom を読み、[{title, link, pub, source}] を返す(Googleニュース以外用)"""
    out = []
    root = ET.fromstring(data)
    if _local(root.tag) not in ("rss", "feed", "rdf"):   # RSSではない(ふつうのページなど)ときは失敗として扱う
        raise ValueError("RSS/Atomではありません(%s)" % _local(root.tag))
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f = {}
        for ch in el:
            k = _local(ch.tag)
            if k == "link":
                f.setdefault("link", (ch.get("href") or ch.text or "").strip())
            elif k in ("title", "pubdate", "published", "updated", "date", "source"):
                text = (ch.text or "").strip()
                if text:
                    f.setdefault(k, text)
        title = re.sub(r"<[^>]+>", "", html.unescape(f.get("title", ""))).strip()
        link = unwrap_link(f.get("link", ""))
        if not title or not link:
            continue
        pub = None
        for k in ("pubdate", "published", "updated", "date"):
            s = f.get(k)
            if not s:
                continue
            try:
                pub = parsedate_to_datetime(s) if k == "pubdate" else datetime.fromisoformat(s.replace("Z", "+00:00"))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=JST)
                pub = pub.astimezone(JST)
                break
            except Exception:  # noqa: BLE001
                pub = None
        if pub is None:
            continue
        out.append({"title": title, "link": link, "pub": pub, "source": f.get("source") or hint})
    return out


def collect_group(label, urls, parse, hint="", tries=2, give_up_after=3):
    """同じ種類の取得先をまとめて取得する。最初の数件がすべて失敗したら、その取得元は見送る。
    戻り値: (raws, 取得の結果)"""
    raws, ok, ng, streak, last_err = [], 0, 0, 0, ""
    for u in urls:
        try:
            raws.extend(parse(fetch_bytes(u, tries=tries), hint))
            ok += 1
            streak = 0
        except Exception as e:  # noqa: BLE001
            ng += 1
            streak += 1
            last_err = ("%s: %s" % (type(e).__name__, e))[:140]
            print("  取得失敗:", label, "->", last_err)
            if ok == 0 and streak >= give_up_after:
                print("  %s は続けて失敗したため、残りを見送ります。" % label)
                break
        time.sleep(0.7)
    print("%s: 成功 %d / 失敗 %d / 見出し %d" % (label, ok, ng, len(raws)))
    stat = {"ok": ok, "ng": ng, "raw": len(raws)}
    if last_err and ok == 0:
        stat["error"] = last_err
    return raws, stat


def collect_extra():
    """Googleニュース以外の取得元をまとめて集める。戻り値: (raws, {取得元の名前: 結果})"""
    raws, stats = [], {}

    def add(label, got, stat):
        for r in got:
            r["via"] = label
        raws.extend(got)
        stats[label] = stat

    if USE_OUTLET_QUERIES:
        urls = []
        for site, extra in OUTLET_SITES:
            for words in ("事件 OR 事故 OR 火災 OR 災害 OR 逮捕", "イベント OR 開催 OR 祭り OR 花火"):
                urls.append(gnews_url(("site:%s %s %s" % (site, extra, words)).replace("  ", " ")))
        got, st = collect_group("Googleニュース(媒体別)", urls, lambda d, h: parse_gnews(d), give_up_after=4)
        add("Googleニュース(媒体別)", got, st)

    if USE_BING:
        queries = list(NEWS_QUERIES) + [c + " 事件 OR 事故 OR 火災 OR 催し" for c in CITY_QUERIES]
        urls = ["https://www.bing.com/news/search?" + urllib.parse.urlencode(
            {"q": q, "format": "rss", "mkt": "ja-JP", "setlang": "ja-JP", "cc": "JP"}) for q in queries]
        got, st = collect_group("Bingニュース", urls, parse_feed)
        add("Bingニュース", got, st)

    if USE_YAHOO_SEARCH:
        urls = ["https://news.yahoo.co.jp/search?" + urllib.parse.urlencode(
            {"p": q, "ei": "UTF-8", "format": "rss"}) for q in NEWS_QUERIES]
        got, st = collect_group("Yahoo!ニュース検索", urls, parse_feed, give_up_after=2)
        add("Yahoo!ニュース検索", got, st)

    for label, url, region in EXTRA_FEEDS:
        got, st = collect_group(label, [url], parse_feed, hint=label, give_up_after=1)
        for r in got:
            r["official"] = True
            r["region"] = region
        add(label, got, st)
    return raws, stats


def collect_jma():
    """気象庁(岡山地方気象台)の防災情報"""
    items = []
    try:
        root = ET.fromstring(fetch_bytes(JMA_FEED))
    except Exception as e:  # noqa: BLE001
        print("気象庁 取得失敗:", e)
        return items, 0
    ns = {"a": "http://www.w3.org/2005/Atom"}
    pat = re.compile(r"警報|注意報|土砂災害|記録的短時間|洪水|竜巻|地震|台風|高潮|火山")
    for e in root.findall("a:entry", ns):
        author = e.findtext("a:author/a:name", "", ns) or ""
        if "岡山地方気象台" not in author:
            continue
        title = (e.findtext("a:title", "", ns) or "").strip()
        if not pat.search(title):
            continue
        content = (e.findtext("a:content", "", ns) or "").strip()
        updated = e.findtext("a:updated", "", ns) or ""
        try:
            pub = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(JST)
        except Exception:  # noqa: BLE001
            continue
        text = "【岡山地方気象台】" + title
        if content:
            text += "「" + content[:80] + "」"
        items.append(
            {
                "id": hashlib.sha1((e.findtext("a:id", "", ns) or text).encode("utf-8")).hexdigest()[:16],
                "title": text,
                "url": JMA_LINK,
                "source": "気象庁",
                "cat": "災害",
                "region": REGION_OTHER,
                "pub": pub.isoformat(),
                "event_date": "",
            }
        )
    items.sort(key=lambda x: x["pub"], reverse=True)
    print("気象庁: %d件" % len(items[:15]))
    return items[:15], 1


# ------------------------------------------------------------
# 判定
# ------------------------------------------------------------
def find_region(title):
    for name, keys in MUNICIPALITIES:
        for k in keys:
            if k in title:
                return name
    return REGION_OTHER


def find_cat(title):
    if RE_FIRE.search(title):
        return "火災"
    if RE_DISASTER.search(title):
        return "災害"
    if RE_ACCIDENT.search(title):
        return "事故"
    if RE_CRIME.search(title):
        return "事件"
    if RE_EVENT.search(title):
        return "催し"
    return ""


def find_event_date(title, pub):
    m = re.search(r"(\d{1,2})月(\d{1,2})日", title) or re.search(r"(\d{1,2})/(\d{1,2})\(", title)
    if not m:
        return ""
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        dt = datetime(pub.year, mo, d, tzinfo=JST)
    except ValueError:
        return ""
    if dt < pub - timedelta(days=60):
        try:
            dt = dt.replace(year=pub.year + 1)
        except ValueError:
            return ""
    return dt.strftime("%Y-%m-%d")


# 他県の地名が混ざる見出しでも、岡山の記事と判断できる言葉(市町村の正式名と、紛らわしくない地区名など)
_SHORT_ONLY = {k for _n, keys in MUNICIPALITIES for k in keys} - {n for n, _k in MUNICIPALITIES}
STRONG_PLACE_WORDS = [n for n, _k in MUNICIPALITIES] + [w for w in OKAYAMA_PLACE_WORDS if w not in _SHORT_ONLY]


# 香川県の地名(香川の記事を除くために使う)
RE_KAGAWA = re.compile(
    r"香川|高松|丸亀|坂出|善通寺|観音寺|さぬき市|東かがわ|三豊|小豆島|直島|琴平|綾川|宇多津|多度津|まんのう|土庄|三木町|屋島|栗林公園"
)
# 「岡山・香川」のように、2県をならべただけの言い方(これだけでは岡山の記事とみなさない)
RE_PAIR_LABEL = re.compile(r"岡山・香川|香川・岡山|岡山と香川|香川と岡山|岡山、香川|香川、岡山|岡山・香川")


# 岡山の地名とまちがえやすい言葉(「鹿児島」の中に「児島」が入っている、など)。判定の前に取りのぞく
RE_LOOKALIKE = re.compile(r"鹿児島|和気あいあい|和気藹々")


def has_okayama_area(title):
    """見出しだけを見て、岡山県内の地名・言葉が入っているかを返す。
    配信元(山陽新聞など)は判定に使わない。"""
    title = RE_LOOKALIKE.sub("", title)
    return any(w in title for w in OKAYAMA_PLACE_WORDS) or find_region(title) != REGION_OTHER


def is_okayama_news(title):
    """報道各社・検索結果の見出しが、岡山のものかどうか。
    ・岡山県内の地名がない見出しは、配信元がどこであっても採用しない
    ・他県・外国の地名があるのに、岡山の市町村名(「倉敷市」のように正式名)も「岡山」もない見出しは採用しない"""
    # 「岡山・香川」のように2県をならべた言い方は、地名とは数えない(KSB・OHKなど両県向けの放送局が付けるため)
    title = RE_PAIR_LABEL.sub("", title)
    if not has_okayama_area(title):
        return False
    # 香川県の地名がある見出しは、「岡山県」「岡山市」や、市町村の正式名(倉敷市など)がある場合だけ採用する
    if RE_KAGAWA.search(title):
        if not re.search("岡山県|岡山市|" + "|".join(n for n, _k in MUNICIPALITIES), title):
            return False
    if "震度" in title and "岡山" not in title:
        return False
    if RE_OTHER_AREA.search(title) and "岡山" not in title:
        # 他県の地名が混ざる見出しは、はっきり岡山とわかる言葉がある場合だけ認める。
        # 「新見」「玉野」のような人名・店名と紛らわしい短い地名だけでは通さない
        if not any(w in title for w in STRONG_PLACE_WORDS):
            return False
    return True


def make_item(raw):
    """生の見出しを整えて、岡山に関係あれば項目を返す。関係なければ None"""
    title = raw["title"]
    source = raw["source"]
    if source and title.endswith(" - " + source):
        title = title[: -(len(source) + 3)]
    title = title.split(" | ")[0]
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None

    region = find_region(title)
    if raw.get("official"):
        if region == REGION_OTHER and raw.get("region"):
            region = raw["region"]
        cat = find_cat(title)
        if not cat:
            return None
        pub = raw["pub"]
        return {
            "id": hashlib.sha1(raw["link"].encode("utf-8")).hexdigest()[:16],
            "title": title,
            "url": raw["link"],
            "source": source,
            "cat": cat,
            "region": region,
            "pub": pub.isoformat(),
            "event_date": find_event_date(title, pub) if cat == "催し" else "",
        }
    # 地名が見出しにない記事は、山陽新聞・RSKなど地元の配信元でも採用しない
    # (共同通信配信の全国ニュースが混ざるため)
    if not is_okayama_news(title):
        return None

    cat = find_cat(title)
    if not cat:
        return None
    pub = raw["pub"]
    event_date = find_event_date(title, pub) if cat == "催し" else ""
    return {
        "id": hashlib.sha1(raw["link"].encode("utf-8")).hexdigest()[:16],
        "title": title,
        "url": raw["link"],
        "source": source,
        "cat": cat,
        "region": region,
        "pub": pub.isoformat(),
        "event_date": event_date,
    }


def norm_key(title):
    t = re.sub(r"[\s\u3000【】\[\]（）()「」『』、。・!！?？\-ー~〜,，.．:：/／]", "", title)
    return t[:40]


# ------------------------------------------------------------
# 保存データ
# ------------------------------------------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
        items = d.get("items", []) if isinstance(d, dict) else []
        need = ("id", "title", "url", "source", "cat", "region", "pub")
        return [i for i in items if isinstance(i, dict) and all(k in i for k in need)]
    except Exception as e:  # noqa: BLE001
        print("data.json を読めませんでした(新規として扱います):", e)
        return []


def merge(old, new, now):
    seen_id, seen_key, out = set(), set(), []
    # 先に古い方を入れる(最初に見つけた方を残す)
    for it in old + new:
        key = norm_key(it["title"])
        if it["id"] in seen_id or key in seen_key:
            continue
        seen_id.add(it["id"])
        seen_key.add(key)
        out.append(it)

    today = now.strftime("%Y-%m-%d")
    kept = []
    for it in out:
        try:
            pub = datetime.fromisoformat(it["pub"])
        except Exception:  # noqa: BLE001
            continue
        days = KEEP_DAYS_EVENT if it["cat"] == "催し" else KEEP_DAYS
        if pub < now - timedelta(days=days):
            continue
        if it["cat"] == "催し" and it.get("event_date") and it["event_date"] < today:
            continue  # 終わった催し
        if pub > now + timedelta(hours=1):
            continue  # 未来日付の異常値
        kept.append(it)
    kept.sort(key=lambda x: x["pub"], reverse=True)
    return kept[:MAX_ITEMS]


def save_data(items, now, stats=None):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"updated": now.isoformat(), "source_stats": stats or {}, "items": items},
            f, ensure_ascii=False, indent=1,
        )


# 今回の取得で、見出しを採用できた取得元の名前(main が入れる)。画面下の「情報源」に表示する
ACTIVE_SOURCES = []


def sources_text():
    seen, out = set(), []
    for n in ACTIVE_SOURCES or ["Googleニュース", "気象庁"]:
        base = n.split("(")[0]
        if base in seen:
            continue
        seen.add(base)
        out.append("気象庁(岡山地方気象台の防災情報)" if base == "気象庁" else base)
    return "、".join(out)


# ------------------------------------------------------------
# ページ作成
# ------------------------------------------------------------
CSS = """
:root{--bg:#eef2f7;--fg:#14202e;--sub:#44536a;--card:#fff;--line:#c9d3e0;--main:#1f3a5f;--main2:#2d5a8e;--on:#fff;--focus:#1f3a5f}
@media (prefers-color-scheme:dark){:root{--bg:#10151c;--fg:#f0f4f9;--sub:#b4c0d0;--card:#1a222c;--line:#364457;--main:#16263f;--main2:#9bbbe6;--on:#f0f4f9;--focus:#9bbbe6}}
.k-事件{--k:#c62828;--kt:rgba(198,40,40,.07)}
.k-事故{--k:#b34700;--kt:rgba(179,71,0,.07)}
.k-火災{--k:#ad1457;--kt:rgba(173,20,87,.07)}
.k-災害{--k:#1565c0;--kt:rgba(21,101,192,.07)}
.k-催し{--k:#2e7d32;--kt:rgba(46,125,50,.07)}
@media (prefers-color-scheme:dark){.k-事件{--k:#ff8a80}.k-事故{--k:#ffb04d}.k-火災{--k:#f48fb1}.k-災害{--k:#74bdf5}.k-催し{--k:#81c784}}
*{box-sizing:border-box}
html{font-size:17px;scroll-padding-top:70px}
html.fs2{font-size:19.5px}html.fs3{font-size:22px}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"Hiragino Kaku Gothic ProN","Hiragino Sans","BIZ UDPGothic","Yu Gothic","Noto Sans JP",Meiryo,sans-serif;line-height:1.7}
[hidden]{display:none!important}
.ic{width:1.3em;height:1.3em;flex:none;vertical-align:-.25em}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.wrap{max-width:860px;margin:0 auto;padding:0 14px}
/* 1. 帯(サイト名・更新時間) */
.band{background:linear-gradient(135deg,var(--main),var(--main2));color:#fff}
.band .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 18px;padding-top:14px;padding-bottom:14px}
.brand{display:flex;align-items:center;gap:12px;color:#fff;text-decoration:none}
.brand .ic{width:2.8rem;height:2.8rem;background:#fff;color:#d6457a;border-radius:50%;padding:.35rem}
.brand h1{margin:0;font-size:1.45rem;line-height:1.3;font-weight:800}
.brand p{margin:0;font-size:.85rem;opacity:.92}
.upd{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.4);border-radius:10px;padding:4px 10px;font-size:.78rem;line-height:1.35}
.upd .ic{width:1.5em;height:1.5em}
.upd b{display:block;font-size:.88rem}
.upd small{display:block;opacity:.9}
/* 2. メニュー */
.menu{position:sticky;top:0;z-index:10;background:var(--card);border-bottom:3px solid var(--main2);box-shadow:0 2px 6px rgba(0,0,0,.12)}
.menu .wrap{display:flex;flex-wrap:wrap;gap:6px;padding-top:8px;padding-bottom:8px}
.mi{flex:none;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;min-width:4.6rem;min-height:3.6rem;padding:4px 10px;border:2px solid var(--line);border-radius:12px;background:var(--card);color:var(--fg);font:inherit;font-size:.92rem;font-weight:700;line-height:1.3;cursor:pointer;text-decoration:none}
.mi .ic{width:1.6em;height:1.6em;color:var(--k,var(--main2))}
.mi small{font-weight:600;color:var(--sub);font-size:.8rem}
.mi[aria-pressed=true]{background:var(--k,var(--main2));border-color:var(--k,var(--main2));color:#fff}
.mi[aria-pressed=true] .ic,.mi[aria-pressed=true] small{color:#fff}
.mi.about{margin-left:auto;border-style:dashed}
/* 3. さがす */
.search{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:14px 0 10px;padding:12px 14px}
.search h2{margin:0 0 8px;font-size:1.05rem;display:flex;align-items:center;gap:6px}
.sbox{display:flex;gap:8px}
.sbox input{flex:1;min-width:0}
input[type=search],select{font:inherit;color:var(--fg);background:var(--bg);border:2px solid var(--line);border-radius:10px;padding:10px 12px;min-height:50px;width:100%}
.btn{font:inherit;font-weight:700;min-height:50px;padding:6px 16px;border:2px solid var(--main2);border-radius:10px;background:var(--card);color:var(--fg);cursor:pointer}
.btn.go{background:var(--main2);color:#fff}
@media (prefers-color-scheme:dark){.btn.go{color:#10151c}}
.srow{display:grid;grid-template-columns:5.5em 1fr;align-items:center;gap:8px;margin-top:10px}
.srow label{font-weight:700;font-size:.95rem}
.tools{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:12px;padding-top:10px;border-top:1px dashed var(--line);font-size:.9rem}
.tools b{margin-right:4px}
.fsb{font:inherit;min-height:44px;padding:4px 14px;border:2px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);cursor:pointer}
.fsb[aria-pressed=true]{background:var(--main2);border-color:var(--main2);color:#fff;font-weight:800}
@media (prefers-color-scheme:dark){.fsb[aria-pressed=true]{color:#10151c}}
/* 4. 一覧 */
.status{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin:4px 2px 6px}
.status p{margin:0;font-weight:800}
.status .sub{font-weight:400;color:var(--sub);font-size:.9rem}
.reset{font:inherit;font-size:.9rem;min-height:40px;padding:2px 14px;border:2px solid var(--main2);border-radius:999px;background:var(--card);color:var(--fg);cursor:pointer;font-weight:700}
section.day h2{position:sticky;top:5.4rem;z-index:5;margin:18px 0 8px;padding:6px 12px;font-size:1.05rem;background:var(--main);color:#fff;border-radius:10px}
ul{list-style:none;margin:0;padding:0}
li{background:linear-gradient(var(--kt),var(--kt)),var(--card);border:1px solid var(--line);border-left:8px solid var(--k);border-radius:12px;padding:10px 14px 12px;margin-bottom:10px}
.meta{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:.85rem;color:var(--sub);margin-bottom:4px;align-items:center}
.tag{display:inline-flex;align-items:center;gap:4px;background:var(--k);color:#fff;font-weight:800;font-size:.9rem;border-radius:8px;padding:1px 10px 1px 7px}
.tag .ic{width:1.15em;height:1.15em;color:#fff}
@media (prefers-color-scheme:dark){.tag{color:#10151c}.tag .ic{color:#10151c}}
.new{background:#ffd600;color:#222;font-weight:800;border-radius:8px;padding:0 8px}
.ev{background:#e8f5e9;color:#1b5e20;font-weight:800;border-radius:8px;padding:0 8px}
@media (prefers-color-scheme:dark){.ev{background:#1f3d24;color:#a5e6ad}}
li a.t{display:block;color:var(--fg);font-weight:800;font-size:1.08rem;line-height:1.55;text-decoration:none;word-break:break-all}
li a.t:hover,li a.t:focus{text-decoration:underline}
.empty{padding:28px 12px;text-align:center;color:var(--sub);background:var(--card);border:2px dashed var(--line);border-radius:14px}
.empty .ic{width:3em;height:3em;color:var(--sub)}
.note{font-size:.85rem;color:var(--sub);margin:18px 2px}
footer{background:var(--card);border-top:3px solid var(--main2);margin-top:20px;padding:14px 0 28px;font-size:.88rem;color:var(--sub)}
footer a{color:var(--main2);font-weight:700}
@media (prefers-color-scheme:dark){footer a{color:#9bbbe6}}
.aboutlink{display:none}
@media (max-width:640px){
.band .wrap{gap:6px 10px;padding-top:8px;padding-bottom:8px}
.brand{gap:8px}
.brand .ic{width:2.2rem;height:2.2rem;padding:.25rem}
.brand h1{font-size:1.12rem}
.brand p{display:none}
.upd{width:100%;padding:3px 10px;border-radius:8px;font-size:.72rem}
.upd .ic{display:none}
.upd>div{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 8px}
.upd b{display:inline;font-size:.78rem}
.menu{position:static}
.menu .wrap{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding-top:8px;padding-bottom:8px}
.mi{min-width:0;min-height:3.3rem;padding:3px 4px}
.mi.about{display:none}
.aboutlink{display:inline-block;margin-left:auto;color:#fff;font-size:.82rem;text-decoration:underline}
section.day h2{top:0}
.search{padding:8px 10px;margin:8px 0 6px;border-radius:10px}
.search h2{font-size:.9rem;margin:0 0 4px}
input[type=search],select{min-height:40px;padding:6px 10px;font-size:.95rem;border-radius:8px}
.btn{min-height:40px;padding:2px 12px;font-size:.88rem;border-radius:8px}
.sbox{gap:6px}
.srow{grid-template-columns:3em 1fr;gap:6px;margin-top:6px}
.srow label{font-size:.85rem}
.tools{margin-top:8px;padding-top:6px;gap:4px;font-size:.8rem}
.fsb{min-height:32px;padding:0 10px;font-size:.8rem}
.status{margin:2px 2px 4px;font-size:.9rem}}
"""

JS = """
(function(){
  var cat="all",reg="all",q="";
  var items=[].slice.call(document.querySelectorAll("#list li"));
  var days=[].slice.call(document.querySelectorAll("#list section"));
  var cnt=document.getElementById("count");
  var cond=document.getElementById("cond");
  var empty=document.getElementById("empty");
  var reset=document.getElementById("reset");
  var qi=document.getElementById("q");
  var rg=document.getElementById("region");
  function apply(){
    var n=0;
    items.forEach(function(li){
      var ok=(cat==="all"||li.getAttribute("data-cat")===cat)&&
             (reg==="all"||li.getAttribute("data-region")===reg)&&
             (!q||li.getAttribute("data-t").indexOf(q)>-1);
      li.hidden=!ok; if(ok)n++;
    });
    days.forEach(function(s){s.hidden=!s.querySelector("li:not([hidden])");});
    cnt.textContent=n+"件";
    var c=[];
    if(cat!=="all")c.push("種類:"+cat);
    if(reg!=="all")c.push("地域:"+reg);
    if(q)c.push("ことば:「"+qi.value.trim()+"」");
    cond.textContent=c.length?c.join(" / "):"すべての見出しを表示中";
    reset.hidden=!c.length;
    empty.hidden=n>0;
  }
  [].forEach.call(document.querySelectorAll("[data-catbtn]"),function(b){
    b.addEventListener("click",function(){
      cat=b.getAttribute("data-catbtn");
      [].forEach.call(document.querySelectorAll("[data-catbtn]"),function(x){
        x.setAttribute("aria-pressed",x===b?"true":"false");});
      apply();
    });
  });
  rg.addEventListener("change",function(e){reg=e.target.value;apply();});
  qi.addEventListener("input",function(e){q=e.target.value.trim().toLowerCase();apply();});
  document.getElementById("sform").addEventListener("submit",function(e){e.preventDefault();qi.blur();apply();});
  document.getElementById("qclear").addEventListener("click",function(){qi.value="";q="";apply();qi.focus();});
  reset.addEventListener("click",function(){
    cat="all";reg="all";q="";qi.value="";rg.value="all";
    [].forEach.call(document.querySelectorAll("[data-catbtn]"),function(x){
      x.setAttribute("aria-pressed",x.getAttribute("data-catbtn")==="all"?"true":"false");});
    apply();
  });
  function setFs(n){
    document.documentElement.className="fs"+n;
    [].forEach.call(document.querySelectorAll("[data-fs]"),function(x){
      x.setAttribute("aria-pressed",x.getAttribute("data-fs")==String(n)?"true":"false");});
    try{localStorage.setItem("okayama_fs",String(n));}catch(e){}
  }
  [].forEach.call(document.querySelectorAll("[data-fs]"),function(b){
    b.addEventListener("click",function(){setFs(b.getAttribute("data-fs"));});
  });
  var s="1";try{s=localStorage.getItem("okayama_fs")||"1";}catch(e){}
  setFs(s);
  apply();
})();
"""


def esc(s):
    return html.escape(s, quote=True)


def render_index(items, now):
    # 日ごとにまとめる
    groups = []
    cur_key, cur = None, None
    for it in items:
        pub = datetime.fromisoformat(it["pub"])
        key = pub.strftime("%Y-%m-%d")
        if key != cur_key:
            cur_key = key
            cur = {"date": pub, "items": []}
            groups.append(cur)
        cur["items"].append((pub, it))

    parts = []
    for g in groups:
        d = g["date"]
        parts.append('<section class="day"><h2>%d月%d日(%s)</h2><ul>' % (d.month, d.day, WEEK[d.weekday()]))
        for pub, it in g["items"]:
            ev = ""
            if now - pub <= timedelta(hours=3):
                ev += '<span class="new">新着</span>'
            if it.get("event_date"):
                ed = it["event_date"]
                ev = '<span class="ev">開催日 %d/%d</span>' % (int(ed[5:7]), int(ed[8:10]))
            search_text = (it["title"] + " " + it["region"] + " " + it["source"] + " " + it["cat"]).lower()
            parts.append(
                '<li class="k-%s" data-cat="%s" data-region="%s" data-t="%s">'
                '<div class="meta"><span class="tag"><svg class="ic" aria-hidden="true"><use href="icons.svg#%s"/></svg>%s</span><span>%s</span>%s'
                '<span>%d/%d %d:%02d</span><span>%s</span></div>'
                '<a class="t" href="%s" target="_blank" rel="noopener nofollow">%s</a></li>'
                % (
                    esc(it["cat"]), esc(it["cat"]), esc(it["region"]), esc(search_text),
                    CAT_ICON.get(it["cat"], "i-news"), esc(it["cat"]), esc(it["region"]), ev,
                    pub.month, pub.day, pub.hour, pub.minute, esc(it["source"]),
                    esc(it["url"]), esc(it["title"]),
                )
            )
        parts.append("</ul></section>")
    list_html = "\n".join(parts)

    regions_present = {it["region"] for it in items}
    order = [n for n, _ in MUNICIPALITIES] + [REGION_OTHER]
    region_opts = '<option value="all">すべての地域</option>' + "".join(
        '<option value="%s">%s</option>' % (esc(r), esc(r)) for r in order if r in regions_present
    )
    counts = {c: 0 for c in CATS}
    for it in items:
        if it["cat"] in counts:
            counts[it["cat"]] += 1
    def ico(name):
        return '<svg class="ic" aria-hidden="true"><use href="icons.svg#%s"/></svg>' % name
    cat_btns = '<button class="mi" data-catbtn="all" aria-pressed="true">%s<span>すべて</span><small>%d件</small></button>' % (ico("i-all"), len(items)) + "".join(
        '<button class="mi k-%s" data-catbtn="%s" aria-pressed="false">%s<span>%s</span><small>%d件</small></button>' % (c, c, ico(CAT_ICON[c]), c, counts[c])
        for c in CATS
    )

    updated_text = "%d年%d月%d日 %d:%02d" % (now.year, now.month, now.day, now.hour, now.minute)
    desc = "岡山県の事件・事故・火災・災害のニュースと、これから開かれる催しの見出しを、1時間ごとに自動で集めて一覧にしています。"

    page = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<link rel="canonical" href="__BASE__">
<meta property="og:type" content="website">
<meta property="og:locale" content="ja_JP">
<meta property="og:site_name" content="__TITLE__">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="__BASE__">
<meta name="theme-color" content="#1f3a5f">
<style>__CSS__</style>
</head>
<body>
<header class="band">
<div class="wrap">
<a class="brand" href="./"><svg class="ic" aria-hidden="true"><use href="icons.svg#i-peach"/></svg>
<div><h1>__TITLE__</h1><p>岡山県のニュース見出しを、自動で集めて一覧にしています</p></div></a>
<a class="aboutlink" href="about.html">このサイトについて</a>
<div class="upd"><svg class="ic" aria-hidden="true"><use href="icons.svg#i-clock"/></svg>
<div><small>最終更新</small><b>__UPDATED__</b><small>__TIMES__自動で更新</small></div></div>
</div>
</header>
<nav class="menu" aria-label="種類をえらぶメニュー">
<div class="wrap">__CATBTNS__
<a class="mi about" href="about.html"><svg class="ic" aria-hidden="true"><use href="icons.svg#i-info"/></svg>このサイトについて</a>
</div>
</nav>
<main class="wrap">
<section class="search" aria-label="さがす">
<h2><svg class="ic" aria-hidden="true"><use href="icons.svg#i-search"/></svg>さがす</h2>
<form id="sform" role="search">
<div class="sbox"><input id="q" type="search" placeholder="例:倉敷 火災 / 花火 / 駅" aria-label="ことばでさがす" autocomplete="off">
<button type="button" class="btn" id="qclear">クリア</button></div>
<div class="srow"><label for="region">地域</label>
<select id="region">__REGIONOPTS__</select></div>
</form>
<div class="tools"><b>文字の大きさ</b>
<button class="fsb" data-fs="1" aria-pressed="true">ふつう</button>
<button class="fsb" data-fs="2" aria-pressed="false">大きい</button>
<button class="fsb" data-fs="3" aria-pressed="false">とても大きい</button></div>
</section>
<div class="status"><p><span id="count"></span> <span class="sub" id="cond"></span></p>
<button type="button" class="reset" id="reset" hidden>条件をリセット</button></div>
<div id="list">
__LIST__
</div>
<div class="empty" id="empty" hidden><svg class="ic" aria-hidden="true"><use href="icons.svg#i-empty"/></svg><br>該当する見出しはありません。<br>ことばや種類・地域を変えてみてください。</div>
<p class="note">見出しと元記事へのリンクだけを表示しています。くわしい内容は、必ず元記事で確認してください。<br>
種類や地域は、見出しの言葉による自動判定です。まちがいや、もれがあります。催しの開催日は元記事で確認してください。<br>
情報源:__SOURCES__</p>
</main>
<footer>
<div class="wrap">
<a href="about.html">このサイトについて(収集方法・免責事項・プライバシーポリシー・連絡先)</a><br>
運営:__OPERATOR__
</div>
</footer>
<script>__JS__</script>
</body>
</html>
"""
    for k, v in {
        "__TITLE__": esc(SITE_TITLE),
        "__DESC__": esc(desc),
        "__BASE__": esc(BASE_URL),
        "__CSS__": CSS,
        "__UPDATED__": esc(updated_text),
        "__TIMES__": esc(UPDATE_TIMES_TEXT),
        "__CATBTNS__": cat_btns,
        "__REGIONOPTS__": region_opts,
        "__LIST__": list_html,
        "__OPERATOR__": esc(OPERATOR),
        "__SOURCES__": esc(sources_text()),
        "__JS__": JS,
    }.items():
        page = page.replace(k, v)
    return page


FALLBACK_ABOUT = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>このサイトについて | __TITLE__</title>
<style>body{font-family:-apple-system,"Hiragino Sans","Yu Gothic UI",Meiryo,sans-serif;max-width:760px;margin:0 auto;padding:16px;line-height:1.8;color:#1c2430}h1{font-size:1.3rem}h2{font-size:1.05rem;margin-top:1.6em}a{color:#1f3a5f}</style></head>
<body>
<h1>このサイトについて</h1>
<p><a href="./">← 一覧にもどる</a></p>
<h2>運営者</h2>
<p>__OPERATOR__(<a href="https://leben-k.github.io/">https://leben-k.github.io/</a>)</p>
<h2>収集方法</h2>
<p>岡山県・岡山市の公式RSS、Googleニュース・Bingニュースのニュース検索(RSS)、気象庁の防災情報から、岡山県に関する見出しを自動で集めています。随時、プログラムが自動で更新します。本文は転載せず、見出しと元記事へのリンクだけを表示します。</p>
<h2>免責事項</h2>
<p>種類や地域は見出しの言葉による自動判定のため、まちがいやもれがあります。くわしい内容や最新の情報は、必ず元記事や公的機関の情報で確認してください。当サイトの利用により生じた損害について、責任を負いかねます。</p>
<h2>プライバシーポリシー</h2>
<p>当サイトは、お問い合わせフォームやアクセス解析などで個人情報を集めていません。ページは GitHub Pages で公開されており、アクセス記録は GitHub が管理します。</p>
<h2>連絡先</h2>
<p>運営者のサイト(<a href="https://leben-k.github.io/">https://leben-k.github.io/</a>)をご覧ください。</p>
</body></html>
"""


def write_site(items, now):
    if os.path.isdir(SITE_DIR):
        shutil.rmtree(SITE_DIR)
    os.makedirs(SITE_DIR)

    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(items, now))

    # icons.svg(絵): index.html と about.html で使う
    if os.path.exists("icons.svg"):
        shutil.copy("icons.svg", os.path.join(SITE_DIR, "icons.svg"))

    # about.html: リポジトリにあればそれを使う(運営者情報・プライバシーポリシー)
    if os.path.exists("about.html"):
        shutil.copy("about.html", os.path.join(SITE_DIR, "about.html"))
    else:
        with open(os.path.join(SITE_DIR, "about.html"), "w", encoding="utf-8") as f:
            f.write(FALLBACK_ABOUT.replace("__TITLE__", esc(SITE_TITLE)).replace("__OPERATOR__", esc(OPERATOR)))

    with open(os.path.join(SITE_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n" % BASE_URL)

    today = now.strftime("%Y-%m-%d")
    with open(os.path.join(SITE_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "<url><loc>%s</loc><lastmod>%s</lastmod><changefreq>daily</changefreq></url>\n"
            "<url><loc>%sabout.html</loc><lastmod>%s</lastmod></url>\n"
            "</urlset>\n" % (BASE_URL, today, BASE_URL, today)
        )
    open(os.path.join(SITE_DIR, ".nojekyll"), "w").close()


# ------------------------------------------------------------
def latest_slot(now):
    """いちばん新しい『集める予定の時刻』(いま以前)を返す"""
    cands = []
    for day_back in (0, 1):
        d = now - timedelta(days=day_back)
        for h, m in SLOTS:
            cands.append(d.replace(hour=h, minute=m, second=0, microsecond=0))
    cands = [c for c in cands if c <= now]
    return max(cands)


def last_updated():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return datetime.fromisoformat(d["updated"])
    except Exception:  # noqa: BLE001
        return None


def set_output(skip):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("skip=%s\n" % ("true" if skip else "false"))


def main():
    now = datetime.now(JST)
    print("開始:", now.strftime("%Y-%m-%d %H:%M:%S JST"))

    # 手動実行(FORCE=1)のときは必ず集める。自動実行のときは「集め損ねている時だけ」集める
    if os.environ.get("FORCE") != "1":
        slot = latest_slot(now)
        upd = last_updated()
        print("直近の予定時刻:", slot.strftime("%m/%d %H:%M"), "/ 前回の収集:", upd.strftime("%m/%d %H:%M") if upd else "なし")
        if upd is not None and upd >= slot:
            print("すでに収集済みのため、今回は何もしません。")
            set_output(True)
            return
        print("未収集のため、収集します。")
    else:
        print("手動実行のため、収集します。")
    set_output(False)

    raws, ok_news, stats = [], 0, {}
    if USE_GOOGLE:
        raws, ok_news = collect_gnews()
        for r in raws:
            r["via"] = "Googleニュース"
        n_queries = len(NEWS_QUERIES) + len(CITY_QUERIES)
        stats["Googleニュース"] = {"ok": ok_news, "ng": n_queries - ok_news, "raw": len(raws)}
    extra_raws, extra_stats = collect_extra()
    raws += extra_raws
    stats.update(extra_stats)
    jma_items, ok_jma = collect_jma()
    stats["気象庁"] = {"ok": ok_jma, "ng": 1 - ok_jma, "raw": len(jma_items)}
    if ok_news == 0 and ok_jma == 0 and not any(s.get("ok") for s in extra_stats.values()):
        print("エラー: どの情報源からも取得できませんでした。")
        sys.exit(1)

    new_items = []
    for r in raws:
        it = make_item(r)
        if it:
            it["via"] = r["via"]
            new_items.append(it)
    for it in jma_items:
        it["via"] = "気象庁"
    new_items.extend(jma_items)
    print("岡山関連として採用: %d件" % len(new_items))

    old = load_data()
    # 前に集めた見出しも、新しい判定で見直す(公式RSS・気象庁は岡山の情報なので、そのまま残す)
    keep_old = []
    for i in old:
        official = i["source"] == "気象庁" or i["source"].startswith(("岡山県", "岡山市"))
        if not official and not is_okayama_news(i["title"]):
            continue
        keep_old.append(i)
    if len(keep_old) != len(old):
        print("岡山以外の見出しを %d件 外しました。" % (len(old) - len(keep_old)))
    old = keep_old
    if not (USE_GOOGLE or USE_BING or USE_OUTLET_QUERIES or USE_YAHOO_SEARCH):
        # 報道各社の見出しを集めない設定のときは、前に集めた報道各社の見出しも残さない
        allowed = {label for label, _u, _r in EXTRA_FEEDS} | {"気象庁"}
        dropped = [i for i in old if i["source"] not in allowed]
        old = [i for i in old if i["source"] in allowed]
        print("報道各社の古い見出しを %d件 外しました。" % len(dropped))

    # 取得元ごとに「採用できた数」と「今まで無かった新しい見出しの数」を数える(data.json に記録)
    seen_id = {i["id"] for i in old}
    seen_key = {norm_key(i["title"]) for i in old}
    for s in stats.values():
        s["adopted"] = 0
        s["new"] = 0
    for it in new_items:
        s = stats.setdefault(it["via"], {"ok": 0, "ng": 0, "raw": 0, "adopted": 0, "new": 0})
        s["adopted"] += 1
        key = norm_key(it["title"])
        if it["id"] not in seen_id and key not in seen_key:
            s["new"] += 1
        seen_id.add(it["id"])
        seen_key.add(key)
        it.pop("via", None)
    ACTIVE_SOURCES[:] = [name for name, s in stats.items() if s.get("adopted")]
    for name, s in stats.items():
        print("  %-18s 取得 %s / 採用 %d件 / 新しい見出し %d件" % (name, s.get("raw", 0), s["adopted"], s["new"]))

    items = merge(old, new_items, now)
    print("保存する見出し: %d件(前回 %d件)" % (len(items), len(old)))

    save_data(items, now, stats)
    write_site(items, now)
    print("完了: %s/ にページを作りました。" % SITE_DIR)


if __name__ == "__main__":
    main()
