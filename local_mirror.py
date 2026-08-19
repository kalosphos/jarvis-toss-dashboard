#!/usr/bin/env python3
"""Jarvis 데이터 미러 (NAS toss 폴더 소속, ./ 상대경로 기준).
원천: ./jarvis.sqlite (NAS SQLite). Mac 백업은 backup-sqlite-to-mac.py가 담당.
사용: from local_mirror import mirror_asset, mirror_daily, mirror_dashboard, mirror_quotes, mirror_fx
"""
import json, sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "jarvis.sqlite"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.executescript("""
    CREATE TABLE IF NOT EXISTS asset_history (generated_at TEXT PRIMARY KEY, metric TEXT, estimated INTEGER, payload TEXT, resolution TEXT);
    CREATE TABLE IF NOT EXISTS asset_daily (trade_date TEXT PRIMARY KEY, payload TEXT);
    CREATE TABLE IF NOT EXISTS dashboard_data (generated_at TEXT PRIMARY KEY, payload TEXT);
    CREATE TABLE IF NOT EXISTS quotes_data (generated_at TEXT PRIMARY KEY, payload TEXT);
    CREATE TABLE IF NOT EXISTS position_fx_snapshot (symbol TEXT PRIMARY KEY, buy_fx_rate REAL, snapshot_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_ah_gen ON asset_history(generated_at);
    CREATE INDEX IF NOT EXISTS idx_ad_date ON asset_daily(trade_date);
    """)
    return c


def _norm_iso(s):
    if not s:
        return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    if not isinstance(s, str):
        try:
            return s.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            s = str(s)
    s = s.replace("Z", "+00:00").replace("T", " ")
    if "+" in s:
        s = s.split("+")[0]
    if "." in s:
        s = s.split(".")[0]
    return s[:19]


def mirror_asset(ts, metric, estimated, payload, resolution="intraday"):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO asset_history VALUES (?,?,?,?,?)",
                  (_norm_iso(ts), metric, 1 if estimated else 0,
                   json.dumps(payload, ensure_ascii=False), resolution))
        c.commit()
    finally:
        c.close()


def mirror_daily(trade_date, payload):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO asset_daily VALUES (?,?)",
                  (trade_date, json.dumps(payload, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()


def mirror_dashboard(generated_at, payload_dict):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO dashboard_data VALUES (?,?)",
                  (_norm_iso(generated_at), json.dumps(payload_dict, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()


def mirror_quotes(generated_at, payload_dict):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO quotes_data VALUES (?,?)",
                  (_norm_iso(generated_at), json.dumps(payload_dict, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()


def mirror_fx(symbol, buy_fx_rate):
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO position_fx_snapshot VALUES (?,?,?)",
                  (symbol, float(buy_fx_rate), datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
    finally:
        c.close()


if __name__ == "__main__":
    # 자가 점검: 임시 키만 사용하고 즉시 삭제 (운영 데이터 오염 방지)
    mirror_asset("2099-01-01 00:00:00", "selftest_tmp", 0, {"t": 1})
    c = sqlite3.connect(str(DB_PATH))
    c.execute("DELETE FROM asset_history WHERE metric='selftest_tmp'")
    c.commit(); c.close()
    print("local_mirror OK ->", DB_PATH)
