#!/bin/sh
# kr_screen_refresh.sh — 매수후보 실시간 갱신 (Hermes cron 주기 실행)
# NAS SMB 볼륨의 스크립트는 launchd/cron이 거부하므로 사용자 세션(Hermes cron)으로 우회.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export JARVIS_TOSS_ROOT=/Volumes/web/toss
export TOSSCTL_BIN=/opt/homebrew/bin/tossctl
export TOSSCTL_SESSION_FILE="$HOME/Library/Application Support/tossctl/session.json"
ROOT=/Volumes/web/toss
LOG="$ROOT/logs/kr_screen_refresh.log"
mkdir -p "$ROOT/logs"
ts=$(date '+%Y-%m-%d %H:%M:%S')

# 1) 매수후보 스크리닝 (force = 실시간 시세)
cd "$ROOT" || exit 1
if python3 /Volumes/web/toss/kr_screener.py --force >> "$LOG" 2>&1; then
  echo "$ts screen OK" >> "$LOG"
else
  echo "$ts screen FAIL: subprocess not defined" >> "$LOG"
  exit 1
fi

# 2) 대시보드 JSON 갱신 (캐시 반영)
if python3 /Volumes/web/toss/update_dashboard_data_nas.py >> "$LOG" 2>&1; then
  echo "$ts dashboard OK" >> "$LOG"
else
  echo "$ts dashboard FAIL" >> "$LOG"
  exit 1
fi
