#!/usr/bin/env python3
"""kr_screen_refresh_final.py — 매수후보 실시간 갱신 (Cron 호환형)

실제 후보 선별: jarvis_toss_data.screen_kr_candidates (TossInvest 공개 API)
실시간 시세 보강: tossctl quote batch (fail-soft, 실패해도 후보 유지)
거짓 성공 금지: 후보 0건이면 WARN + exit 1 (shell에서 screen FAIL 기록)
"""
import os
import sys
import json
import argparse
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path

TOSS_ROOT = Path(os.environ.get('JARVIS_TOSS_ROOT') or '/Volumes/web/toss').expanduser()
sys.path.insert(0, str(TOSS_ROOT))
LOG_DIR = TOSS_ROOT / 'logs'
LOG_FILE = LOG_DIR / 'kr_screen_refresh.log'
DASH_PATH = TOSS_ROOT / 'dashboard-data.json'


def write_log(msg, level="INFO"):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{ts} {level}: {msg}\n")
    except Exception as e:
        print(f"[LOG ERROR] {e}")


def get_candidates(limit=30):
    """TossInvest 공개 API 기반 후보 선별 (fail-closed)."""
    try:
        import jarvis_toss_data
        rows = jarvis_toss_data.screen_kr_candidates(limit=limit)
        out = []
        for row in rows:
            if not (isinstance(row, (list, tuple)) and len(row) >= 3):
                continue
            sym, name, price = row[0], row[1], row[2]
            out.append({"code": str(sym), "symbol": str(sym), "name": str(name), "price": float(price)})
        return out
    except Exception as e:
        write_log(f"screener error: {e}", "ERROR")
        return []


def tossctl_quote_map(symbols):
    """실시간 시세 보강. 실패 시 {} 반환 (후보는 유지)."""
    if not symbols:
        return {}
    bin_path = os.environ.get('TOSSCTL_BIN') or 'tossctl'
    session = os.environ.get('TOSSCTL_SESSION_FILE')
    cmd = [bin_path, 'quote', 'batch'] + symbols + ['--output', 'json']
    if session:
        cmd += ['--session-file', session]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            if isinstance(data, list):
                return {str(d.get('symbol') or d.get('code') or d.get('productCode')): d
                        for d in data if isinstance(d, dict)}
            if isinstance(data, dict):
                return data
    except Exception as e:
        write_log(f"quote batch error: {e}", "WARN")
    return {}


def write_dashboard(candidates):
    quotes = tossctl_quote_map([c['symbol'] for c in candidates])
    for c in candidates:
        q = quotes.get(c['symbol'])
        if isinstance(q, dict):
            for k in ('price', 'close', 'currentPrice'):
                if isinstance(q.get(k), (int, float)):
                    c['price'] = float(q[k])
                    break
    payload = {
        "timestamp": datetime.now().isoformat(),
        "mode": "force",
        "data_version_hash": hashlib.sha256(
            json.dumps(candidates, ensure_ascii=False).encode()).hexdigest()[:12],
        "buy_candidates": candidates,
        "kr_screen_candidates": candidates,
        "market_status": "open" if candidates else None,
    }
    # 캐시 파일로만 저장 (update_dashboard_data_nas.py가 dashboard-data.json에 합침)
    cache = {
        "timestamp": datetime.now().isoformat(),
        "candidates": candidates,
        "data_version_hash": payload["data_version_hash"],
    }
    cache_tmp = TOSS_ROOT / ".kr_screen_cache.json.tmp"
    cache_tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    cache_tmp.replace(TOSS_ROOT / ".kr_screen_cache.json")


def write_empty():
    cache = {
        "timestamp": datetime.now().isoformat(),
        "candidates": [],
        "data_version_hash": payload["data_version_hash"],
    }
    cache_tmp = TOSS_ROOT / ".kr_screen_cache.json.tmp"
    cache_tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    cache_tmp.replace(TOSS_ROOT / ".kr_screen_cache.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.parse_args()

    print("[START] kr_screen_refresh_final.py starting...")
    candidates = get_candidates(limit=30)
    if not candidates:
        write_log("No stock data retrieved", "WARN")
        write_empty()
        print("❌ No candidates retrieved, exit 1")
        exit(1)

    write_dashboard(candidates)
    write_log(f"Screen refresh completed: {len(candidates)} candidates", "INFO")
    print(f"✅ {len(candidates)} candidates collected")
    exit(0)


if __name__ == "__main__":
    main()
