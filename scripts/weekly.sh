#!/bin/sh
# 每週五例行工作：備份會員名單（雜湊）、產生每週總表、跳出提醒。
# 由 launchd 或 cron 範本呼叫；也可以手動執行： sh scripts/weekly.sh
# 這支腳本只讀寫本機檔案，不連網、不發布任何東西。
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR" || exit 1
python3 ledger.py member export
python3 ledger.py report
if command -v osascript >/dev/null 2>&1; then
  osascript -e 'display notification "每週總表已產生：reports/weekly.html。花 30 分鐘複盤，寫三行預判驗證。" with title "球場帳本 週五複盤"' || true
  open "$DIR/reports/weekly.html" || true
fi
