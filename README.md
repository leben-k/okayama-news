# 岡山 事件・事故・災害・催しまとめ

岡山県に関する見出しを、毎日 日本時間 5:00 / 11:30 / 19:00 / 22:00 に自動で集めて表示します(無料)。

## ファイルの説明

- `index.html` … 一覧のページ
- `about.html` … 収集方法・免責事項・プライバシーポリシー・連絡先
- `icons.svg` … 絵(アイコン)
- `data.json` … 集めた見出し(自動で更新されます)
- `scripts/collect.py` … 見出しを集めるプログラム
- `.github/workflows/collect.yml` … 自動で動かす設定(GitHub上で作ります)
- `sitemap.xml` / `robots.txt` … 最初の自動実行のときに自動で作られます

## 調整できるところ(`scripts/collect.py` の上部)

- `NEWS_QUERIES` … 検索ワード
- `KW` / `EVENT_KW` … 種類の判定ワード
- `LOCAL_SOURCES` … 地名がなくても岡山とみなす配信元
- `KEEP_DAYS` … 履歴を残す日数(初期値7日)
- `SLOTS` … ページに表示する更新時刻(`collect.yml` の cron と合わせます)

## 検索エンジンに見つけてもらう

Google Search Console(無料)で、公開URL(`https://ユーザー名.github.io/okayama-news/`)を登録し、
`sitemap.xml` を送信してください。トップページの「URL検査」から「インデックス登録をリクエスト」も押します。
