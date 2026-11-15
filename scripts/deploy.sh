#!/bin/sh
# 部署網站到 GitHub Pages：重新產生 site/，再把內容推到 origin 的 gh-pages 分支。
# 用法： sh scripts/deploy.sh
# 會保留 gh-pages 的歷史（不 force push）；site/ 沒有變動時不會產生新 commit。
# 只推 site/ 的內容，不會推 40-data/ 的資料庫或會員名單。
set -eu
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

BRANCH=gh-pages
REMOTE="$(git remote get-url origin)" || { echo "找不到 git remote origin。" >&2; exit 1; }

if grep -q '"base_url": *"https://example.com' ledger.config.json 2>/dev/null; then
  echo "base_url 仍是占位值，請先改 ledger.config.json 再部署。" >&2
  exit 1
fi

python3 ledger.py build

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  git clone -q --depth 1 --branch "$BRANCH" "$REMOTE" "$TMP"
else
  git init -q -b "$BRANCH" "$TMP"
fi

# 用最新的 site/ 取代分支內容（保留 .git）
find "$TMP" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R site/. "$TMP"/

cd "$TMP"
git add -A
if git diff --cached --quiet; then
  echo "site/ 沒有變動，不需要部署。"
  exit 0
fi
git commit -q -m "Deploy site $(date '+%Y-%m-%d %H:%M')"
git push -q "$REMOTE" "HEAD:$BRANCH"
echo "已推到 ${BRANCH}。GitHub Pages 通常一兩分鐘內更新。"
