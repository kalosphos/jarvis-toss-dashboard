#!/usr/bin/env python3
"""Read-only Toss public-market data for Jarvis ATM v2.1."""
from __future__ import annotations

import json
import math
import time
import urllib.request
from typing import Any

BASE_URL = "https://wts-info-api.tossinvest.com"
CERT_BASE_URL = "https://wts-cert-api.tossinvest.com"
TIMEOUT = 30
QUOTE_TTL = 5.0
RANKING_TTL = 60.0
CANDLE_TTL = 600.0

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.tossinvest.com",
    "Referer": "https://www.tossinvest.com/",
    "User-Agent": "Mozilla/5.0 jarvis-toss-data/2.1",
}
_cache: dict[tuple[str, str, str], tuple[float, Any]] = {}


def _get(
    path: str,
    *,
    base: str = BASE_URL,
    body: dict[str, Any] | None = None,
    cache_ttl: float = 0.0,
) -> Any | None:
    key = (base, path, json.dumps(body, sort_keys=True) if body is not None else "")
    now = time.time()
    hit = _cache.get(key)
    if hit and cache_ttl > 0 and now - hit[0] < cache_ttl:
        return hit[1]
    try:
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = dict(_HEADERS)
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            base + path,
            data=encoded,
            headers=headers,
            method="GET" if encoded is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = json.loads(response.read().decode("utf-8"))
        # Public endpoints used here have a required top-level result envelope.
        if not isinstance(raw, dict) or "result" not in raw:
            return None
        result = raw["result"]
        _cache[key] = (now, result)
        return result
    except Exception:
        return None


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def normalize_product_code(code: str) -> str:
    value = str(code).strip().upper()
    return f"A{value}" if value.isdigit() and len(value) == 6 else value


def strip_a(code: str) -> str:
    value = str(code).strip().upper()
    return value[1:] if len(value) == 7 and value.startswith("A") and value[1:].isdigit() else value


def quote_close(symbol: str, cache_ttl: float = QUOTE_TTL) -> float | None:
    data = _get(
        f"/api/v3/stock-prices/{normalize_product_code(symbol)}/quotes?investMode=krx",
        cache_ttl=cache_ttl,
    )
    return _positive_number(data.get("close")) if isinstance(data, dict) else None


def daily_candles(symbol: str, count: int = 30, cache_ttl: float = CANDLE_TTL) -> list[dict[str, Any]]:
    data = _get(
        f"/api/v1/c-chart/kr-s/{normalize_product_code(symbol)}/day:1"
        f"?count={max(1, int(count))}&session=all&investMode=krx&useAdjustedRate=true",
        cache_ttl=cache_ttl,
    )
    chart = data.get("chart") if isinstance(data, dict) and isinstance(data.get("chart"), dict) else data
    candles = chart.get("candles") if isinstance(chart, dict) else None
    if not isinstance(candles, list):
        return []
    by_dt: dict[str, dict[str, Any]] = {}
    for candle in candles:
        if not isinstance(candle, dict) or not isinstance(candle.get("dt"), str) or not candle["dt"]:
            continue
        normalized = dict(candle)
        valid = True
        for key in ("open", "high", "low", "close"):
            number = _positive_number(candle.get(key))
            if number is None:
                valid = False
                break
            normalized[key] = number
        if not valid:
            continue
        for key in ("volume", "amount"):
            if key in candle and candle[key] is not None:
                try:
                    number = float(candle[key])
                except (TypeError, ValueError):
                    valid = False
                    break
                if not math.isfinite(number) or number < 0:
                    valid = False
                    break
                normalized[key] = number
        if valid:
            by_dt[normalized["dt"]] = normalized
    return [by_dt[key] for key in sorted(by_dt, reverse=True)]


def change_rate(symbol: str, cache_ttl: float = CANDLE_TTL) -> float | None:
    candles = daily_candles(symbol, count=2, cache_ttl=cache_ttl)
    if len(candles) < 2:
        return None
    return candles[0]["close"] / candles[1]["close"] - 1.0


def rsi(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    closes: list[float] = []
    for candle in reversed(candles):
        if not isinstance(candle, dict):
            continue
        close = _positive_number(candle.get("close"))
        if close is not None:
            closes.append(close)
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(gains)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
    return 100.0 if average_loss == 0 else 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def top_kr_products(limit: int = 100, cache_ttl: float = RANKING_TTL) -> list[dict[str, Any]]:
    body = {
        "id": "biggest_market_amount",
        "tag": "kr",
        "duration": "realtime",
        "filters": [],
        "investMode": "krx",
    }
    data = _get(
        "/api/v2/dashboard/wts/overview/ranking",
        base=CERT_BASE_URL,
        body=body,
        cache_ttl=cache_ttl,
    )
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        return []
    output: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        symbol = strip_a(product.get("productCode") or "")
        name = product.get("name")
        price = product.get("price")
        close = _positive_number(price.get("close")) if isinstance(price, dict) else None
        if not (symbol.isdigit() and len(symbol) == 6 and isinstance(name, str) and name.strip() and close):
            continue
        output.append({"symbol": symbol, "name": name.strip(), "price": close})
        if len(output) >= max(0, int(limit)):
            break
    return output


def screen_kr_candidates(
    limit: int = 30,
    max_price: float | None = None,
    cache_ttl: float = RANKING_TTL,
) -> list[tuple[str, str, float]]:
    selected: list[tuple[str, str, float]] = []
    ceiling = _positive_number(max_price) if max_price is not None else None
    for item in top_kr_products(limit=100, cache_ttl=cache_ttl):
        price = item["price"]
        if ceiling is not None and price > ceiling:
            continue
        name = item["name"]
        # 레버리지/인버스/선물/옵션만 제외, ETF 허용
        if any(k in name for k in ('레버리지', '인버스', '선물', '옵션')):
            continue
        selected.append((item["symbol"], name, price))
        if len(selected) >= max(0, int(limit)):
            break
    return selected
