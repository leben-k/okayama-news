#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
岡山 事件・事故・災害・催しまとめ
  - Googleニュース(RSS)と気象庁(岡山地方気象台)から見出しを集める
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
SITE_TITLE = "岡山 事件・事故・災害・催しまとめ"
OPERATOR = "地域情報室"
UPDATE_TIMES_TEXT = "5:00 / 11:30 / 16:00 / 19:00 / 22:00ごろ"  # 表示用の文言(時刻はcollect.ymlのcronで決まります)

DATA_FILE = "data.json"
SITE_DIR = "site"
KEEP_DAYS = 7          # 事件・事故・火災・災害を残す日数
KEEP_DAYS_EVENT = 14   # 催しを残す日数
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

CATS = ["事件", "事故", "火災", "災害", "催し"]

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
    r"福岡|熊本|宮崎|鹿児島|沖縄|能登|石川|三陸|岩手|宮古島|奄美|伊豆|台湾|韓国|中国"
)
RE_LOCAL_SOURCE = re.compile(r"山陽新聞|津山朝日|OHK|岡山放送|RSK|山陽放送|山陽新聞デジタル")

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


def make_item(raw):
    """生の見出しを整えて、岡山に関係あれば項目を返す。関係なければ None"""
    title = raw["title"]
    source = raw["source"]
    if source and title.endswith(" - " + source):
        title = title[: -(len(source) + 3)]
    rsk_area = "岡山・香川のニュース" in title
    title = title.split(" | ")[0]
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None

    region = find_region(title)
    has_area = ("岡山" in title) or ("おかやま" in title) or region != REGION_OTHER
    if not has_area and rsk_area and not RE_OTHER_AREA.search(title) and "香川" not in title:
        has_area = True
    if not has_area:
        if not (RE_LOCAL_SOURCE.search(source) and not RE_OTHER_AREA.search(title)):
            return None
    # 他県の地震などを除く
    if "震度" in title and "岡山" not in title:
        return None
    # 地名が岡山市以外の他県で、岡山が付いていないもの
    if RE_OTHER_AREA.search(title) and "岡山" not in title and region == REGION_OTHER:
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


def save_data(items, now):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"updated": now.isoformat(), "items": items}, f, ensure_ascii=False, indent=1
        )


# ------------------------------------------------------------
# ページ作成
# ------------------------------------------------------------
CSS = """
:root{--bg:#f3f5f8;--fg:#1c2430;--sub:#566274;--card:#fff;--line:#d5dbe4;--main:#1f3a5f;--on:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#10151c;--fg:#e8ecf1;--sub:#a3adbb;--card:#18202a;--line:#2a3441;--main:#7fa6d8;--on:#10151c}}
.k-事件{--k:#c62828;--kt:rgba(198,40,40,.09)}
.k-事故{--k:#c75000;--kt:rgba(199,80,0,.09)}
.k-火災{--k:#ad1457;--kt:rgba(173,20,87,.09)}
.k-災害{--k:#1565c0;--kt:rgba(21,101,192,.09)}
.k-催し{--k:#2e7d32;--kt:rgba(46,125,50,.09)}
*{box-sizing:border-box}
html{font-size:100%}
html.fs2{font-size:118%}html.fs3{font-size:138%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic UI","Meiryo",sans-serif;line-height:1.6}
[hidden]{display:none!important}
header{background:var(--main);color:var(--on);padding:14px 16px}
header h1{margin:0;font-size:1.15rem;line-height:1.35}
header p{margin:6px 0 0;font-size:.82rem;opacity:.95}
main{max-width:820px;margin:0 auto;padding:12px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:12px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.row:last-child{margin-bottom:0}
.lbl{font-size:.78rem;color:var(--sub);width:100%}
button,select,input{font:inherit;color:var(--fg)}
.chip{border:2px solid var(--line);background:var(--card);border-radius:999px;padding:6px 14px;cursor:pointer;min-height:42px;font-weight:600}
.chip[aria-pressed=true]{background:var(--main);color:var(--on);border-color:var(--main)}
.chip.cat{border-color:var(--k);color:var(--k)}
.chip.cat[aria-pressed=true]{background:var(--k);color:#fff;border-color:var(--k)}
.chip small{font-weight:400;opacity:.9;margin-left:2px}
select,input[type=search]{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:9px 10px;min-height:42px;flex:1;min-width:140px}
.count{font-size:.85rem;color:var(--sub);margin:4px 2px 8px}
section.day h2{font-size:1rem;margin:18px 2px 8px;color:var(--fg);border-bottom:2px solid var(--line);padding-bottom:4px}
ul{list-style:none;margin:0;padding:0}
li{background:linear-gradient(var(--kt),var(--kt)),var(--card);border:1px solid var(--line);border-left:8px solid var(--k);border-radius:10px;padding:10px 12px;margin-bottom:8px}
.meta{display:flex;flex-wrap:wrap;gap:6px 8px;font-size:.78rem;color:var(--sub);margin-bottom:4px;align-items:center}
.tag{background:var(--k);color:#fff;font-weight:700;font-size:.85rem;border-radius:6px;padding:1px 10px}
.new{background:#ffd600;color:#222;font-weight:700;border-radius:6px;padding:0 7px}
.ev{background:#e8f5e9;color:#1b5e20;font-weight:700;border-radius:6px;padding:0 7px}
@media (prefers-color-scheme:dark){.ev{background:#1f3d24;color:#a5e6ad}}
li a{color:var(--fg);text-decoration:none;font-weight:700;word-break:break-all;font-size:1.02rem}
li a:hover,li a:focus{text-decoration:underline}
.note{font-size:.8rem;color:var(--sub);margin:16px 2px}
footer{max-width:820px;margin:0 auto;padding:4px 12px 28px;font-size:.8rem;color:var(--sub)}
footer a{color:var(--main)}
.empty{padding:20px;text-align:center;color:var(--sub)}
"""

JS = """
(function(){
  var cat="all",reg="all",q="";
  var items=[].slice.call(document.querySelectorAll("#list li"));
  var days=[].slice.call(document.querySelectorAll("#list section"));
  var cnt=document.getElementById("count");
  var empty=document.getElementById("empty");
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
  document.getElementById("region").addEventListener("change",function(e){reg=e.target.value;apply();});
  document.getElementById("q").addEventListener("input",function(e){q=e.target.value.trim().toLowerCase();apply();});
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
                '<div class="meta"><span class="tag">%s</span><span>%s</span>%s'
                '<span>%d/%d %d:%02d</span><span>%s</span></div>'
                '<a href="%s" target="_blank" rel="noopener nofollow">%s</a></li>'
                % (
                    esc(it["cat"]), esc(it["cat"]), esc(it["region"]), esc(search_text),
                    esc(it["cat"]), esc(it["region"]), ev,
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
    cat_btns = '<button class="chip" data-catbtn="all" aria-pressed="true">すべて<small>%d</small></button>' % len(items) + "".join(
        '<button class="chip cat k-%s" data-catbtn="%s" aria-pressed="false">%s<small>%d</small></button>' % (c, c, c, counts[c])
        for c in CATS
    )

    updated_text = "%d年%d月%d日 %d:%02d" % (now.year, now.month, now.day, now.hour, now.minute)
    desc = "岡山県の事件・事故・火災・災害のニュースと、これから開かれる催しの見出しを、毎日5回自動で集めて一覧にしています。"

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
<header>
<h1>__TITLE__</h1>
<p>最終更新:__UPDATED__ ・ 1日5回(__TIMES__)自動で更新</p>
</header>
<main>
<div class="panel">
<div class="row"><span class="lbl">種類</span>__CATBTNS__</div>
<div class="row"><span class="lbl">地域・ことば</span>
<select id="region" aria-label="地域をえらぶ">__REGIONOPTS__</select>
<input id="q" type="search" placeholder="ことばでさがす" aria-label="ことばでさがす"></div>
<div class="row"><span class="lbl">文字の大きさ</span>
<button class="chip" data-fs="1" aria-pressed="true">ふつう</button>
<button class="chip" data-fs="2" aria-pressed="false">大きい</button>
<button class="chip" data-fs="3" aria-pressed="false">とても大きい</button></div>
</div>
<p class="count" id="count"></p>
<div id="list">
__LIST__
</div>
<p class="empty" id="empty" hidden>該当する見出しはありません。</p>
<p class="note">見出しと元記事へのリンクだけを表示しています。くわしい内容は、必ず元記事で確認してください。<br>
種類や地域は、見出しの言葉による自動判定です。まちがいや、もれがあります。催しの開催日は元記事で確認してください。<br>
情報源:Googleニュース(RSS)、気象庁(岡山地方気象台の防災情報)</p>
</main>
<footer>
<a href="about.html">このサイトについて(収集方法・免責事項・プライバシーポリシー・連絡先)</a><br>
運営:__OPERATOR__
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
<p>Googleニュース(RSS)と気象庁の防災情報から、岡山県に関する見出しを自動で集めています。1日5回、プログラムが自動で更新します。本文は転載せず、見出しと元記事へのリンクだけを表示します。</p>
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
def main():
    now = datetime.now(JST)
    print("開始:", now.strftime("%Y-%m-%d %H:%M:%S JST"))

    raws, ok_news = collect_gnews()
    jma_items, ok_jma = collect_jma()
    if ok_news == 0 and ok_jma == 0:
        print("エラー: どの情報源からも取得できませんでした。")
        sys.exit(1)

    new_items = []
    for r in raws:
        it = make_item(r)
        if it:
            new_items.append(it)
    new_items.extend(jma_items)
    print("岡山関連として採用: %d件" % len(new_items))

    old = load_data()
    items = merge(old, new_items, now)
    print("保存する見出し: %d件(前回 %d件)" % (len(items), len(old)))

    save_data(items, now)
    write_site(items, now)
    print("完了: %s/ にページを作りました。" % SITE_DIR)


if __name__ == "__main__":
    main()
