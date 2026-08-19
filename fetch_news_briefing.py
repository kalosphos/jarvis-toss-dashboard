#!/usr/bin/env python3
"""Fetch news briefing for Jarvis stock holdings.

Produces news_briefing.json with:
- per_position: news linked to each held ticker
- global_risks: today's top global macro risks (middle/high impact)
- calendar: upcoming economic events this week (earnings, rate decisions)

Sources (merged in priority order):
1. Investing.com 주식 RSS — global markets, macro analysis https://kr.investing.com/rss/stock.rss
2. Hankyung News RSS — Korean finance headlines https://www.hankyung.com/feed/all-news
- Manual override: news_briefing_manual.json (if present, takes precedence).

Read-only: no trading mutation. Designed to be called by cron
before update_dashboard_data_nas.py runs.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from xml.etree import ElementTree as ET

ROOT = pathlib.Path(os.environ.get("JARVIS_TOSS_ROOT", "/var/services/web/toss")).expanduser()
OUT_FILE = ROOT / "news_briefing.json"
KST = timezone(timedelta(hours=9))

DEFAULT_TICKERS = [
    {"symbol": "005930", "name": "삼성전자", "market": "KRW"},
    {"symbol": "000660", "name": "SK하이닉스", "market": "KRW"},
    {"symbol": "NVDA", "name": "NVIDIA", "market": "US"},
    {"symbol": "AAPL", "name": "Apple", "market": "US"},
]

# Verified working RSS feeds — Investing.com (global) + Hankyung (Korean)
RSS_FEEDS = [
    "https://kr.investing.com/rss/stock.rss",      # 10+ global finance articles
    "https://www.hankyung.com/feed/all-news",        # 50+ Korean business articles
]

RISK_KEYWORDS = (
    "fed", "interest rate", "inflation", "recession", "war", "conflict",
    "금리", "인플레이션", "경제침체", "전쟁", "충돌", "원자재",
    "채무불이행", "디폴트", "유럽중앙은행", "엔화",
    "중국", "러시아", "시중금리", "정책금리",
)

CALENDAR_KEYWORDS = (
    "CPI", "금리", "interest rate", "FED", "미국 연준", "고용",
    "GDP", "PMI", "소비자물가", "임금", "경제지표",
    "결과 발표", "실적 발표", "분기", "실적",
    "정책금리", "기준금리", "통화정책",
)


def _http_get(url: str, timeout: int = 20, max_bytes: int = 500_000) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (jarvis-briefing/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes)
            return data.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"HTTP GET failed for {url}: {e}")
        return ""


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _parse_rss_xml(xml: str) -> list[dict[str, str]]:
    """Parse RSS XML into list of {title, url, published_at} dicts."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    items = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        date_el = item.find("pubDate")
        title = unescape(title_el.text).strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        if not link:
            guid = item.find("guid")
            link = guid.text.strip() if guid is not None and guid.text else ""
        published = date_el.text.strip() if date_el is not None and date_el.text else ""
        items.append({"title": title, "url": link, "published_at": published})
    return items


def _fetch_rss() -> list[dict[str, str]]:
    """Fetch and parse multiple RSS feeds, merged and deduplicated."""
    all_items = []
    seen_urls = set()
    for feed_url in RSS_FEEDS:
        xml = _http_get(feed_url, timeout=15)
        if not xml:
            continue
        items = _parse_rss_xml(xml)
        print(f"RSS OK: {feed_url} ({len(items)} items)")
        for item in items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)
    return all_items


def fetch_ticker_news(ticker: dict[str, str], rss_items: list[dict[str, str]], max_items: int = 5) -> list[dict[str, str]]:
    """Filter RSS items by ticker name/symbol keywords."""
    name = ticker.get("name", "")
    symbol = ticker.get("symbol", "")
    # Build search keywords (both Korean name and symbol)
    keywords = [name]
    if symbol:
        keywords.append(symbol)
    # US tickers: also search by name
    if ticker.get("market") == "US":
        keywords.extend([name, symbol])

    matches = []
    for item in rss_items:
        title = item.get("title", "").lower()
        matched = False
        for kw in keywords:
            if kw and len(kw) >= 2 and kw.lower() in title:
                matched = True
                break
        if matched:
            matches.append(item)

    # Deduplicate by URL, preserve order
    seen = set()
    deduped = [x for x in matches if x["url"] not in seen and not seen.add(x["url"])]
    return deduped[:max_items]


def fetch_global_risks(rss_items: list[dict[str, str]], max_items: int = 5) -> list[dict[str, str]]:
    """Filter RSS items matching risk keywords."""
    filtered = [
        item for item in rss_items
        if any(kw in (item["title"] + " " + item.get("url", "")).lower() for kw in RISK_KEYWORDS)
    ]
    return filtered[:max_items]


def fetch_economic_calendar(rss_items: list[dict[str, str]], max_items: int = 10) -> list[dict[str, str]]:
    """Filter RSS items matching economic calendar/event keywords."""
    filtered = [
        item for item in rss_items
        if any(kw in (item["title"] + " " + item.get("url", "")).lower() for kw in CALENDAR_KEYWORDS)
    ]
    return filtered[:max_items]


def main() -> int:
    tickers = DEFAULT_TICKERS
    # Read tickers from dashboard-data.json if available
    data_file = ROOT / "dashboard-data.json"
    if data_file.exists():
        try:
            dd = json.loads(data_file.read_text())
            metrics_pos = dd.get("metrics", {}).get("positions", [])
            if metrics_pos:
                tickers = [
                    {"symbol": p.get("stock_code", "").replace("A", ""),
                     "name": p.get("name", ""),
                     "market": "KRW"}
                    for p in metrics_pos if p.get("market_type") == "KOR"
                ] + [
                    {"symbol": p.get("stock_code", ""),
                     "name": p.get("name", ""),
                     "market": "US"}
                    for p in metrics_pos if p.get("market_type") != "KOR"
                ]
        except Exception:
            pass  # fallback to DEFAULT_TICKERS

    # Fetch all RSS items once
    rss_items = _fetch_rss()

    # Check for manual override
    manual_file = ROOT / "news_briefing_manual.json"
    if manual_file.exists():
        try:
            manual = json.loads(manual_file.read_text())
            output = {
                "generated_at": datetime.now(tz=KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
                "per_position": manual.get("per_position", {}),
                "global_risks": manual.get("global_risks", []),
                "calendar": manual.get("calendar", []),
            }
        except Exception:
            output = {
                "generated_at": datetime.now(tz=KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
                "per_position": {},
                "global_risks": [],
                "calendar": [],
            }
    else:
        # Automatic collection from RSS
        per_position = {}
        for ticker in tickers:
            news = fetch_ticker_news(ticker, rss_items)
            if news:
                per_position[ticker["symbol"]] = {
                    "name": ticker.get("name", ""),
                    "market": ticker.get("market", "US"),
                    "news": news,
                }

        output = {
            "generated_at": datetime.now(tz=KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
            "per_position": per_position,
            "global_risks": fetch_global_risks(rss_items),
            "calendar": fetch_economic_calendar(rss_items),
        }

    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    tmp.replace(OUT_FILE)
    print(f"news_briefing.json written with {len(output['per_position'])} positions, "
          f"{len(output['global_risks'])} risks, {len(output['calendar'])} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())