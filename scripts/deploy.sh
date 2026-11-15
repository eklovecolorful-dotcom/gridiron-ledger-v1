#!/bin/sh
# 部署網站：GitHub Pages 與 Vercel。
# 用法： sh scripts/deploy.sh            # 兩個都部署
#        sh scripts/deploy.sh pages      # 只部署 GitHub Pages
#        sh scripts/deploy.sh vercel     # 只部署 Vercel
#
# GitHub Pages：重新產生 site/，推到 origin 的 gh-pages 分支。保留分支歷史（不 force push），
#               site/ 沒有變動時不會產生新 commit。
# Vercel：用 ledger.config.json 裡 vercel.base_url 另外產生一份網站到 site-vercel/，
#         部署到 vercel.project_id 那個專案的正式環境。需要先 `npx vercel login`。
# 兩邊都只上傳產生出來的網站，不會上傳 40-data/ 的資料庫或會員名單。
set -eu
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

TARGET="${1:-all}"
case "$TARGET" in
  all|pages|vercel) ;;
  *) echo "用法：sh scripts/deploy.sh [all|pages|vercel]" >&2; exit 2 ;;
esac

# 讀 ledger.config.json 裡的值，例如 cfg base_url、cfg vercel.project_id
cfg() {
  python3 -c 'import json,sys
v=json.load(open("ledger.config.json",encoding="utf-8"))
for k in sys.argv[1].split("."):
    v=v.get(k,"") if isinstance(v,dict) else ""
print(v)' "$1"
}

case "$(cfg base_url)" in
  ""|https://example.com*) echo "base_url 仍是占位值，請先改 ledger.config.json 再部署。" >&2; exit 1 ;;
esac

deploy_pages() {
  BRANCH=gh-pages
  REMOTE="$(git remote get-url origin)" || { echo "找不到 git remote origin。" >&2; return 1; }
  python3 ledger.py build

  TMP="$(mktemp -d)"
  if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
    git clone -q --depth 1 --branch "$BRANCH" "$REMOTE" "$TMP"
  else
    git init -q -b "$BRANCH" "$TMP"
  fi
  # 用最新的 site/ 取代分支內容（保留 .git）
  find "$TMP" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  cp -R site/. "$TMP"/

  (
    cd "$TMP"
    git add -A
    if git diff --cached --quiet; then
      echo "GitHub Pages：site/ 沒有變動，不需要部署。"
    else
      git commit -q -m "Deploy site $(date '+%Y-%m-%d %H:%M')"
      git push -q "$REMOTE" "HEAD:$BRANCH"
      echo "GitHub Pages：已推到 ${BRANCH}，通常一兩分鐘內更新。"
    fi
  )
  rm -rf "$TMP"
}

deploy_vercel() {
  URL="$(cfg vercel.base_url)"
  PROJECT="$(cfg vercel.project_id)"
  ORG="$(cfg vercel.org_id)"
  if [ -z "$URL" ] || [ -z "$PROJECT" ] || [ -z "$ORG" ]; then
    echo "Vercel：ledger.config.json 缺 vercel.base_url / project_id / org_id。" >&2
    return 1
  fi
  python3 ledger.py build --base-url "$URL" --out site-vercel
  VERCEL_ORG_ID="$ORG" VERCEL_PROJECT_ID="$PROJECT" npx --yes vercel deploy site-vercel --prod --yes
  echo "Vercel：已部署到 ${URL}"
}

if [ "$TARGET" = all ] || [ "$TARGET" = pages ]; then deploy_pages; fi
if [ "$TARGET" = all ] || [ "$TARGET" = vercel ]; then deploy_vercel; fi
