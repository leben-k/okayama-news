name: okayama-news-collect

on:
  push:
    branches: [main]
    paths:
      - ".github/workflows/collect.yml"
      - "scripts/collect.py"
  schedule:
    # 日本時間 = UTC + 9時間
    # 毎時0分ちょうどは GitHub が混み合って遅れたり飛ばされたりするため、少しずらしています
    - cron: "7 20 * * *"    # 日本時間 05:07
    - cron: "37 2 * * *"    # 日本時間 11:37
    - cron: "7 7 * * *"     # 日本時間 16:07
    - cron: "7 10 * * *"    # 日本時間 19:07
    - cron: "7 13 * * *"    # 日本時間 22:07
  workflow_dispatch:

permissions:
  contents: write
  pages: write

concurrency:
  group: collect
  cancel-in-progress: false

jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Collect news
        run: python scripts/collect.py

      - name: Save changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --cached --quiet || git commit -m "update $(TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M')"
          git pull --rebase
          git push

      # 自動の保存だけではサイトの表示が更新されないことがあるため、公開の更新を直接お願いする
      - name: Request Pages build
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          curl -fsS -X POST \
            -H "Authorization: Bearer $GH_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            "https://api.github.com/repos/${{ github.repository }}/pages/builds"
