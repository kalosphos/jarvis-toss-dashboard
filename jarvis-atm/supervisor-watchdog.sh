#!/bin/bash
# supervisor-watchdog: auto_trading_manager.py (슈퍼바이저) 항시 기동 유지
# 거래권한 토글(.control/trade-control.json enabled)이 실거래 유일 게이트.
# 워치독은 슈퍼바이저 프로세스만 관리하며, 토글 상태와 무관하게 기동한다.
set -u

ROOT="/Volumes/web/toss"
PIDFILE="$ROOT/.control/supervisor.pid"
LOG="$ROOT/logs/supervisor-watchdog.log"
BIN="/Users/jarvis/.local/bin/tossctl"
SESSION="/Users/jarvis/Library/Application Support/tossctl/session.json"
mkdir -p "$(dirname "$LOG")"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# 이미 프로세스 떠 있으면 종료
if pgrep -f "auto_trading_manager.py" >/dev/null 2>&1; then
  # PID 파일과 실제 일치 확인
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
    exit 0
  fi
fi

log "supervisor not running - starting"
cd "$ROOT" || exit 1
TOSSCTL_BIN="$BIN" TOSSCTL_SESSION_FILE="$SESSION" JARVIS_TOSS_ROOT="$ROOT" \
  nohup python3 "$ROOT/auto_trading_manager.py" >> "$ROOT/logs/supervisor.out" 2>&1 &
echo $! > "$PIDFILE"
log "supervisor started pid=$(cat "$PIDFILE")"
