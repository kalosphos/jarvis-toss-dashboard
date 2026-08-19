import sqlite3
db="/volume2/web/toss/jarvis.sqlite"
c=sqlite3.connect(db)
c.executescript("""
CREATE TABLE IF NOT EXISTS asset_history (generated_at TEXT PRIMARY KEY, metric TEXT, estimated INTEGER, payload TEXT, resolution TEXT);
CREATE TABLE IF NOT EXISTS asset_daily (trade_date TEXT PRIMARY KEY, payload TEXT);
CREATE TABLE IF NOT EXISTS dashboard_data (generated_at TEXT PRIMARY KEY, payload TEXT);
CREATE TABLE IF NOT EXISTS quotes_data (generated_at TEXT PRIMARY KEY, payload TEXT);
CREATE TABLE IF NOT EXISTS position_fx_snapshot (symbol TEXT PRIMARY KEY, buy_fx_rate REAL, snapshot_at TEXT);
CREATE INDEX IF NOT EXISTS idx_ah_gen ON asset_history(generated_at);
CREATE INDEX IF NOT EXISTS idx_ad_date ON asset_daily(trade_date);
""")
c.commit()
c.close()
print("sqlite ready:", db)
