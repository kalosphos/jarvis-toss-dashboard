#!/usr/bin/env python3
"""Jarvis Toss Securities dashboard generator.

Read-only data path:
- Toss WTS session cookie from tossctl login
- Toss WTS dashboard asset API
- tossctl account summary, read-only

No order or trading mutation is performed.
"""
from __future__ import annotations

import json
import os
import fcntl
import pathlib
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

try:
    import pymysql
except ImportError:
    pymysql = None

ROOT = pathlib.Path(os.environ.get("JARVIS_TOSS_ROOT", "/var/services/web/toss")).expanduser()
# The NAS supervisor runs as root, while the authenticated Toss session and CLI
# belong to the NAS user.  Environment overrides keep this deployable elsewhere.
SESSION_FILE = pathlib.Path(os.environ.get(
    "TOSSCTL_SESSION_FILE",
    "/var/services/homes/kwangho79/Library/Application Support/tossctl/session.json",
))
TOSSCTL_BIN = os.environ.get(
    "TOSSCTL_BIN",
    "/var/services/homes/kwangho79/.local/bin/tossctl",
)
DATA_FILE = ROOT / "dashboard-data.json"
DAILY_PLAN_FILE = ROOT / "daily-trade-plan.json"
TRADE_CONTROL_FILE = ROOT / ".control" / "trade-control.json"
AI_BRIEFING_FILE = ROOT / "ai-daily-briefing.json"
AI_BRIEFING_HISTORY_FILE = ROOT / "ai-daily-briefing-history.json"
HISTORY_FILE = Path(os.environ.get("JARVIS_HISTORY_FILE", str(ROOT / "dashboard-history.json")))
CONFIG_FILE = ROOT / "jarvis_config.json"
AUTO_STATUS_FILE = ROOT / "auto-trading-status.json"
KR_SCREEN_CACHE_FILE = ROOT / ".kr_screen_cache.json"


def get_toss_auth_status() -> dict[str, Any]:
    """tossctl auth status JSON을 읽어 대시보드 인증 상태 표시용으로 정규화.

    만료 임박(7일 이내) 또는 invalid/세션파일 없음 → needs_reauth.
    호출 실패 시 기본값(needs_reauth) 반환.
    """
    try:
        env = dict(os.environ)
        for k in ("TOSSCTL_AUTH_HELPER_DIR", "TOSSCTL_AUTH_HELPER_PYTHON", "TOSSCTL_BIN", "TOSSCTL_SESSION_FILE"):
            v = os.environ.get(k)
            if v:
                env[k] = v
        proc = subprocess.run(
            [TOSSCTL_BIN, "auth", "status", "--output", "json"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if proc.returncode != 0:
            return {"valid": False, "needs_reauth": True, "source": "cli_error", "detail": (proc.stderr or "").strip()[:200]}
        data = json.loads(proc.stdout)
        valid = bool(data.get("valid"))
        server_expires = data.get("server_expires_at")
        soon = False
        if server_expires:
            try:
                exp = datetime.fromisoformat(server_expires.replace("Z", "+00:00"))
                soon = (exp - datetime.now(timezone.utc)).days <= 7
            except Exception:
                soon = False
        return {
            "valid": valid,
            "needs_reauth": (not valid) or soon,
            "server_expires_at": server_expires,
            "provider": data.get("provider"),
            "soon": soon,
            "source": "tossctl",
        }
    except Exception as e:
        return {"valid": False, "needs_reauth": True, "source": "exception", "detail": str(e)[:200]}
KST = timezone(timedelta(hours=9))

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "live_trading_paused",
    "read_only_mode": False,
    "live_trading_enabled": False,
    "live_switch_status": "paused_by_user",
    "initial_operating_capital_krw": 4842484,
    "initial_operating_capital_note": "사용자 지정 고정 초기 운용원금 4,842,484원. 현재 운용 매입원금·현금으로 재계산하거나 덮어쓰지 않는다.",
    "initial_operating_capital_policy": "fixed_config",
    "require_manual_approval_for_live": False,
    "manual_approval_mechanism": "dashboard_toggle_confirm_dialog",
    "reset_initial_operating_capital_at_live_start": False,
    "operating_cash_policy": "include_account_balance_orderable_cash",
    "tactical_purchase_basis_overrides": [
        {
            "stock_code": "A315930",
            "symbol": "315930",
            "name": "KODEX Top5PlusTR",
            "bucket": "jarvis_operation",
            "quantity": 60.0,
            "purchase_price_krw": 103260.0,
            "reason": "사용자 지정: 자비스 운용 60주는 103,260원 매입 기준 적용. 운용 제외 100주와 분리 계산.",
        }
    ],
    "agabang_reference": {
        "enabled": True,
        "mode": "priority_risk_guardrail",
        "priority": "highest",
        "block_new_buys_on_checks": True,
        "source_label": "겸손은 힘들다 [12시에 만나요] · 주식아가방",
        "source_url": "https://juaga.co.kr/",
        "required_reference": "겸손은 힘들다 [12시에 만나요]",
        "absolute_reference_required": True,
        "source_interpretation": "매수 신호 생성용이 아니라 자비스 주식운용의 최우선 위험관리·손실관리·추격매수 금지 기준으로 절대 참조한다.",
        "principles": [
            {"key": "risk_first", "title": "위험관리 최우선", "detail": "위험관리와 잃지 않는 투자를 최상위 원칙으로 둔다."},
            {"key": "short_loss_long_profit", "title": "손실은 짧게, 이익은 길게", "detail": "손실·낙폭 점검을 먼저 통과하지 못하면 신규 매수를 막는다."},
            {"key": "etf_core_first", "title": "ETF·지수 코어 우선", "detail": "코어 ETF 비중을 먼저 채운 뒤 개별주를 검토한다."},
            {"key": "no_chasing", "title": "추격매수 금지", "detail": "급등·불장에서는 가격 위치와 변동성을 확인하고 감정적 매수를 막는다."},
        ],
    },
    "overseas_risk_considerations": [
        {
            "key": "fx_risk",
            "title": "환율 리스크",
            "detail": "주가가 올라도 환율 하락 시 환차손이 발생할 수 있으며, 환전 우대와 환율 흐름을 함께 확인한다.",
        },
        {
            "key": "tax",
            "title": "세금 및 과세",
            "detail": "매매차익은 연 250만 원 기본공제 후 22% 양도소득세 대상이며, 배당은 15.4% 배당소득세 원천징수를 고려한다.",
        },
        {
            "key": "fees",
            "title": "수수료 및 제비용",
            "detail": "증권사 매매 수수료, 환전 수수료, 미국 매도 시 SEC fee 등 현지 제비용과 최소 수수료를 확인한다.",
        },
        {
            "key": "trading_hours",
            "title": "거래 시간 및 결제일",
            "detail": "시차, 정규장/프리장/애프터장, 결제 지연을 고려하고 장외 유동성 저하를 주의한다.",
        },
        {
            "key": "information_access",
            "title": "기업 정보 및 공시",
            "detail": "현지 언어 공시와 재무제표를 확인해야 하며 국내 공시보다 접근성과 해석 난도가 높을 수 있다.",
        },
        {
            "key": "no_deposit_protection",
            "title": "예금자 보호 없음",
            "detail": "해외주식 투자원금은 예금자보호법 보호 대상이 아니므로 손실 가능성을 전제로 관리한다.",
        },
    ],
    "operation_exclusions": [
        {
            "stock_code": "A069500",
            "symbol": "069500",
            "name": "KODEX 200",
            "excluded_quantity": 350.0,
            "reason": "사용자 지정: 자비스 주식운용 제외",
        },
        {
            "stock_code": "A315930",
            "symbol": "315930",
            "name": "KODEX Top5PlusTR",
            "excluded_quantity": 100.0,
            "reason": "사용자 지정: 자비스 주식운용 제외",
        },
    ],
    "notes": [
        "이 대시보드는 읽기 전용이며 실제 주문을 실행하지 않는다.",
        "operation_exclusions 수량은 자비스 운용 평가에서 보호/제외 수량으로 분리한다.",
        "KODEX Top5PlusTR 100주 제외 후 남은 60주 전량을 103,260원 매입 기준의 자비스 운용 바구니로 계산한다.",
    ],
}


def atomic_write_json(path: pathlib.Path, data: Any) -> None:
    """Durably publish complete JSON with one atomic replacement."""
    temporary_path: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = pathlib.Path(temporary.name)
            json.dump(data, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _normalize_dt(value: Any) -> str:
    """ISO 8601(타임존 포함) → MariaDB DATETIME 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=9)))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def db_conn() -> Optional[Any]:
    """NAS MariaDB 연결. pymysql 없거나 실패 시 None 반환(파일 fallback 유지)."""
    if pymysql is None:
        return None
    try:
        return pymysql.connect(
            host=os.environ.get("JARVIS_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("JARVIS_DB_PORT", "3306")),
            user=os.environ.get("JARVIS_DB_USER", "root"),
            password=os.environ.get("JARVIS_DB_PASS", ""),
            database="jarvis",
            charset="utf8mb4",
            connect_timeout=5,
        )
    except Exception:
        return None


def write_dashboard_to_db(payload: dict[str, Any]) -> None:
    """dashboard-data.json을 MariaDB jarvis.dashboard_data 에 최신행으로 기록.
    실패해도 파일 fallback이 있으므로 조용히 무시."""
    conn = db_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO dashboard_data (generated_at, payload) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE payload = VALUES(payload)",
                (_normalize_dt(payload.get("generated_at")), json.dumps(payload, ensure_ascii=False)),
            )
        conn.commit()
    except Exception as e:
        print(f"dashboard_data DB write skipped: {e}")
    finally:
        conn.close()


def fetch_usd_krw() -> float:
    """실시간 USD/KRW 환율 (open.er-api.com, 키 불필요). 실패 시 None."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return float(data["rates"]["KRW"])
    except Exception as e:
        print(f"fx fetch failed: {e}")
        return 0.0


def get_buy_fx_rate(symbol: str, current_fx: float) -> float:
    """종목 매입 시점 환율 스냅샷. 최초 1회만 저장(고정), 이후 조회만.
    DB 없거나 실패 시 현재 환율로 fallback."""
    conn = db_conn()
    if conn is None or current_fx <= 0:
        return current_fx
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT buy_fx_rate FROM position_fx_snapshot WHERE symbol=%s", (symbol,))
            row = cur.fetchone()
            if row:
                return float(row[0])
            # 최초 기록: 현재 환율을 매입시점 환율로 스냅샷
            cur.execute(
                "INSERT INTO position_fx_snapshot (symbol, buy_fx_rate, first_seen) VALUES (%s, %s, %s)",
                (symbol, current_fx, datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            return current_fx
    except Exception as e:
        print(f"fx snapshot skipped for {symbol}: {e}")
        return current_fx
    finally:
        conn.close()


def ensure_config() -> dict[str, Any]:
    ROOT.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n")
    return json.loads(CONFIG_FILE.read_text())


def load_auto_status() -> dict[str, Any]:
    if not AUTO_STATUS_FILE.exists():
        return {"status": "not_started", "live_trading_enabled": False}
    try:
        data = json.loads(AUTO_STATUS_FILE.read_text())
        return data if isinstance(data, dict) else {"status": "invalid"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def load_daily_plan() -> dict[str, Any]:
    try:
        if not DAILY_PLAN_FILE.exists():
            return {}
        data = json.loads(DAILY_PLAN_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_trade_control() -> dict[str, Any]:
    result: dict[str, Any] = {"enabled": False, "updated_at": None, "valid": False, "file_present": TRADE_CONTROL_FILE.exists()}
    try:
        data = json.loads(TRADE_CONTROL_FILE.read_text(encoding="utf-8")) if result["file_present"] else {}
    except Exception:
        return result
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
        return result
    result.update({
        "enabled": data["enabled"],
        "updated_at": data.get("updated_at") if isinstance(data.get("updated_at"), str) else None,
        "valid": True,
    })
    return result


def build_execution_safety(config: dict[str, Any], trade_control: dict[str, Any], auto_status: dict[str, Any]) -> dict[str, Any]:
    """Expose the controller's dashboard-toggle contract without reinterpreting it."""
    configured_live = bool(config.get("live_trading_enabled", False))
    process_config = config.get("auto_trading_process") or {}
    control_required = bool(process_config.get("dashboard_trade_control_required", True))
    dry_run = auto_status.get("dry_run_decision") if isinstance(auto_status, dict) else None
    dry_run = dry_run if isinstance(dry_run, dict) else {}
    can_place = dry_run.get("can_place_order_now") if isinstance(dry_run.get("can_place_order_now"), bool) else None
    required_fields = (
        "dashboard_trade_control_required",
        "dashboard_trade_enabled",
        "dashboard_trade_control_updated_at",
        "can_place_order_now",
        "reason",
    )
    runtime_complete = all(key in dry_run for key in required_fields)
    runtime_control = dry_run.get("dashboard_trade_enabled") if runtime_complete else None
    control_enabled = bool(trade_control.get("valid") and trade_control.get("enabled"))
    if not configured_live:
        classification, reason = "locked", "설정상 실거래가 비활성화되어 있습니다."
    elif control_required and not control_enabled:
        classification, reason = "locked", "대시보드 거래 제어 토글이 OFF이거나 제어 파일이 유효하지 않습니다."
    elif not runtime_complete:
        classification, reason = "policy_mismatch", "런타임이 대시보드 거래 제어 필드를 완전하게 보고하지 않습니다."
    elif runtime_control is not control_enabled:
        classification, reason = "policy_mismatch", "제어 파일과 런타임의 거래 토글 상태가 일치하지 않습니다."
    elif can_place is True:
        classification, reason = "runtime_ready", "대시보드 토글을 포함한 컨트롤러의 모든 주문 게이트가 준비되었습니다."
    else:
        classification, reason = "locked", str(dry_run.get("reason") or "런타임 주문 게이트가 잠겨 있습니다.")
    return {
        "configured_live_trading_enabled": configured_live,
        "dashboard_trade_control_required": control_required,
        "dashboard_trade_enabled": control_enabled,
        "dashboard_trade_control_updated_at": trade_control.get("updated_at"),
        "runtime_can_place_order_now": can_place,
        "runtime_fields_complete": runtime_complete,
        "runtime_reason": dry_run.get("reason"),
        "classification": classification,
        "reason_ko": reason,
        "display_only": True,
        "controller_gated_notice": "대시보드 서버 토글은 유일한 사람 거래 승인이고, 주문은 컨트롤러의 나머지 안전 게이트도 모두 통과해야 합니다.",
    }

AI_BRIEFING_DISPLAY_FIELDS = (
    "status",
    "generated_at",
    "summary",
    "evidence",
    "red_team",
    "action_labels",
    "execution_safety",
    "approval_state",
    "daily_plan",
    "risk_flags",
    "signals",
    "macro",
    "trade_suggestions",
    "advisory",
)


def project_ai_briefing(data: Any) -> dict[str, Any]:
    """Strict non-secret display projection shared by latest and history."""
    if not isinstance(data, dict):
        return {}
    result: dict[str, Any] = {key: data[key] for key in AI_BRIEFING_DISPLAY_FIELDS if key in data}
    raw_suggestions = result.get("trade_suggestions")
    if isinstance(raw_suggestions, list):
        proposals: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_suggestions):
            if isinstance(item, dict):
                proposals.append({
                    "id": f"briefing-suggestion-{idx}",
                    "label": (item.get("label") or "").strip() or None,
                    "basis": (item.get("detail") or "").strip() or None,
                    "status": "requires_human_approval",
                })
        if proposals:
            result["execution_proposals"] = proposals
    return result


def load_ai_briefing() -> dict[str, Any]:
    """Read the optional latest briefing through the display allowlist."""
    try:
        data = json.loads(AI_BRIEFING_FILE.read_text()) if AI_BRIEFING_FILE.exists() else None
    except Exception:
        data = None
    result = project_ai_briefing(data)
    if not result:
        return {"state": "not_configured", "status": "not_configured"}
    result["state"] = "configured"
    result.setdefault("status", "available")
    return result


def load_ai_briefing_history() -> list[dict[str, Any]]:
    """Malformed or absent history is safe empty; never pass unlisted fields through."""
    try:
        data = json.loads(AI_BRIEFING_HISTORY_FILE.read_text())
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    history: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data[:30]:
        projected = project_ai_briefing(item)
        generated_at = projected.get("generated_at")
        if not isinstance(generated_at, str) or not generated_at or generated_at in seen:
            continue
        seen.add(generated_at)
        projected.setdefault("status", "available")
        history.append(projected)
    return sorted(history, key=lambda item: item["generated_at"], reverse=True)


def dashboard_contract(config: dict[str, Any], auto_status: dict[str, Any]) -> dict[str, Any]:
    trade_control = load_trade_control()
    dry_run = auto_status.get("dry_run_decision") if isinstance(auto_status, dict) else None
    dry_run = dry_run if isinstance(dry_run, dict) else {}
    return {
        "trade_control": trade_control,
        "dashboard_trade_control_required": dry_run.get("dashboard_trade_control_required"),
        "dashboard_trade_enabled": dry_run.get("dashboard_trade_enabled"),
        "dashboard_trade_control_updated_at": dry_run.get("dashboard_trade_control_updated_at"),
        "can_place_order_now": dry_run.get("can_place_order_now"),
        "can_place_order_reason": dry_run.get("reason"),
        "execution_safety": build_execution_safety(config, trade_control, auto_status),
        "ai_briefing": load_ai_briefing(),
        "ai_briefing_history": load_ai_briefing_history(),
    }


def load_kr_screen_candidates() -> list[dict[str, Any]]:
    if not KR_SCREEN_CACHE_FILE.exists():
        return []
    try:
        data = json.loads(KR_SCREEN_CACHE_FILE.read_text())
        candidates = data.get("candidates", []) if isinstance(data, dict) else []
        return [
            {"code": row.get("code"), "name": row.get("name"), "price": row.get("price")}
            for row in candidates[:30]
            if isinstance(row, dict)
        ]
    except Exception:
        return []


def get_positions() -> list[dict[str, Any]]:
    """tossctl portfolio positions → allocate_position_buckets 호환 raw_items.

    ponytail: WTS 세션 쿠키 직접 관리(post_json/urllib) 제거, tossctl output 재사용.
    basePrice는 원본 미제공 → currentPrice로 대체(일간등락률 정밀도 하락, 허용).
    """
    try:
        proc = subprocess.run(
            [TOSSCTL_BIN, "--session-file", str(SESSION_FILE), "portfolio", "positions", "--output", "json"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        rows = json.loads(proc.stdout)
    except Exception as exc:
        print(f"positions fetch failed: {exc}")
        return []
    raw = []
    for r in rows:
        sym = str(r.get("symbol") or "")
        # config operation_exclusions.stock_code uses "A"+symbol (WTS format)
        stock_code = ("A" + sym) if not sym.startswith("A") else sym
        raw.append({
            "stockCode": stock_code,
            "stockSymbol": sym,
            "stockName": r.get("name"),
            "marketType": r.get("market_type"),
            "shareHoldingsType": (r.get("market_type") or "").lower(),
            "quantity": float(r.get("quantity") or 0),
            "currentPrice": float(r.get("current_price") or 0),
            "basePrice": float(r.get("current_price") or 0),
            "purchasePrice": float(r.get("average_price") or 0),
            "marketValue": float(r.get("market_value") or 0),
            "dailyProfitRate": float(r.get("daily_profit_rate") or 0),
        })
    return raw


def get_account_summary() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [TOSSCTL_BIN, "--session-file", str(SESSION_FILE), "account", "summary", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(proc.stdout)
    except Exception as exc:  # keep dashboard alive even when summary parser changes
        return {"error": str(exc)}


def get_realized_pnl_krw() -> float:
    """tossctl 원장의 순실현금액(매도·배당·이자 포함)"""
    try:
        proc = subprocess.run(
            [TOSSCTL_BIN, "--session-file", str(SESSION_FILE), "profit", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(proc.stdout)
        return round(money(data.get("earning_amount")), 2)
    except Exception as exc:
        print(f"realized_pnl fetch failed: {exc}")
        return 0.0


def money(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("krw")
    if value is None:
        return 0.0
    return float(value)


def rate(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("krw")
    if value is None:
        return 0.0
    return float(value)


def proportional_item(
    item: dict[str, Any],
    quantity: float,
    bucket: str,
    purchase_price_override_krw: Optional[float] = None,
    purchase_basis_source: str = "broker_average",
    fx_rate: float = 1.0,
    buy_fx_rate: float = 0.0,
) -> dict[str, Any]:
    total_qty = float(item.get("quantity") or 0)
    if total_qty <= 0 or quantity <= 0:
        ratio = 0.0
    else:
        ratio = min(quantity, total_qty) / total_qty
    # 미국 종목: 매입가는 매입시점 환율, 현재가는 현재 환율 적용 → 토스앱 원화 수익률과 일치
    is_us = (item.get("shareHoldingsType") or "").lower() == "us"
    if is_us:
        cur_fx = fx_rate if fx_rate > 0 else 1.0
        buy_fx = buy_fx_rate if buy_fx_rate > 0 else cur_fx
    else:
        cur_fx = 1.0
        buy_fx = 1.0
    current_price_krw = money(item.get("currentPrice")) * cur_fx
    base_price_krw = money(item.get("basePrice")) * cur_fx
    purchase_price_raw = float(purchase_price_override_krw) if purchase_price_override_krw is not None else money(item.get("purchasePrice"))
    purchase_price_krw = purchase_price_raw * buy_fx
    evaluated_krw = current_price_krw * quantity
    purchase_krw = purchase_price_krw * quantity
    pnl_krw = evaluated_krw - purchase_krw
    daily_pnl_krw = (current_price_krw - base_price_krw) * quantity
    pnl_rate = 0.0 if purchase_krw <= 0 else pnl_krw / purchase_krw
    # 일간 등락률: tossctl이 제공하는 daily_profit_rate를 우선 사용 (basePrice 원본 미제공 대비)
    daily_profit_rate = item.get("dailyProfitRate")
    if daily_profit_rate is not None and daily_profit_rate != 0.0:
        daily_rate = float(daily_profit_rate)
    else:
        # fallback: 전일 종가(basePrice) 기준 계산
        daily_base_krw = base_price_krw * quantity
        daily_rate = 0.0 if daily_base_krw <= 0 else daily_pnl_krw / daily_base_krw
    return {
        "bucket": bucket,
        "bucket_label": {
            "jarvis_operation": "자비스 운용",
            "excluded_from_jarvis_operation": "운용 제외",
            "unassigned_not_in_jarvis_operation": "미배정(자비스 운용 제외)",
            "full_account": "계좌 전체",
        }.get(bucket, bucket),
        "market_type": item.get("marketType"),
        "share_holdings_type": item.get("shareHoldingsType"),
        "stock_code": item.get("stockCode"),
        "symbol": item.get("stockSymbol") or (str(item.get("stockCode") or "")[1:] if str(item.get("stockCode") or "").startswith("A") else str(item.get("stockCode") or "")),
        "name": item.get("stockName"),
        "quantity": round(quantity, 6),
        "total_quantity": total_qty,
        "current_price_krw": round(current_price_krw, 4),
        "base_price_krw": round(base_price_krw, 4),
        "purchase_price_krw": round(purchase_price_krw, 4),
        "purchase_basis_source": purchase_basis_source,
        "evaluated_krw": round(evaluated_krw, 4),
        "purchase_krw": round(purchase_krw, 4),
        "pnl_krw": round(pnl_krw, 4),
        "pnl_rate": round(pnl_rate, 6),
        "daily_pnl_krw": round(daily_pnl_krw, 4),
        "daily_rate": round(daily_rate, 6),
        "allocation_ratio_of_position": round(ratio, 6),
    }


def allocate_position_buckets(
    raw_items: list[dict[str, Any]], config: dict[str, Any], fx_rate: float = 1.0, buy_fx_map: Optional[dict] = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split actual inventory into operating, explicitly excluded, and unassigned buckets."""
    exclusions = {e["stock_code"]: float(e["excluded_quantity"]) for e in config["operation_exclusions"]}
    tactical_overrides = {
        o["stock_code"]: o
        for o in config.get("tactical_purchase_basis_overrides", [])
        if o.get("bucket") == "jarvis_operation" and o.get("quantity") is not None
    }
    operating_positions: list[dict[str, Any]] = []
    protected_positions: list[dict[str, Any]] = []
    unassigned_positions: list[dict[str, Any]] = []
    full_positions: list[dict[str, Any]] = []
    exclusion_checks: list[dict[str, Any]] = []
    buy_fx_map = buy_fx_map or {}

    for item in raw_items:
        stock_code = item.get("stockCode")
        sym = item.get("stockSymbol") or (str(stock_code)[1:] if str(stock_code or "").startswith("A") else str(stock_code or ""))
        buy_fx = buy_fx_map.get(sym, fx_rate)
        total_qty = float(item.get("quantity") or 0)
        excluded_qty = min(total_qty, exclusions.get(stock_code, 0.0))
        available_qty = max(total_qty - excluded_qty, 0.0)
        override = tactical_overrides.get(stock_code)
        operating_qty = min(available_qty, float(override["quantity"])) if override else available_qty
        unassigned_qty = max(available_qty - operating_qty, 0.0)
        full_positions.append(proportional_item(item, total_qty, "full_account", fx_rate=fx_rate, buy_fx_rate=buy_fx))
        if excluded_qty > 0:
            protected_positions.append(proportional_item(item, excluded_qty, "excluded_from_jarvis_operation", fx_rate=fx_rate, buy_fx_rate=buy_fx))
        if operating_qty > 0:
            override_price = float(override["purchase_price_krw"]) if override and override.get("purchase_price_krw") is not None else None
            operating_positions.append(
                proportional_item(item, operating_qty, "jarvis_operation", override_price, "user_tactical_lot" if override_price is not None else "broker_average", fx_rate=fx_rate, buy_fx_rate=buy_fx)
            )
        if unassigned_qty > 0:
            unassigned_positions.append(proportional_item(item, unassigned_qty, "unassigned_not_in_jarvis_operation", fx_rate=fx_rate, buy_fx_rate=buy_fx))
        if stock_code in exclusions or override:
            exclusion_checks.append(
                {
                    "stock_code": stock_code,
                    "name": item.get("stockName"),
                    "held_quantity": total_qty,
                    "excluded_quantity": excluded_qty,
                    "operating_quantity": operating_qty,
                    "remaining_operating_quantity": operating_qty,
                    "unassigned_not_in_jarvis_operation_quantity": unassigned_qty,
                    "fully_excluded": operating_qty == 0,
                }
            )
    return operating_positions, protected_positions, unassigned_positions, full_positions, exclusion_checks


def operating_return_rate(current_operating_capital: float, initial_operating_capital: float) -> float:
    return 0.0 if initial_operating_capital <= 0 else round(current_operating_capital / initial_operating_capital - 1, 6)


def build_source(config: dict[str, Any]) -> dict[str, Any]:
    """config의 live_trading_enabled를 따라 계약 반영(2026-07-16). live면 armed_auto_trading."""
    live = bool(config.get("live_trading_enabled", False))
    return {
        "name": "Toss Securities WTS 자산 API · 시장데이터 갱신",
        "endpoint": "/api/v2/dashboard/asset/sections/all SORTED_OVERVIEW",
        "mode": "armed_auto_trading" if live else "live_trading_paused",
        "data_path_mode": "market_data_refresh",
        "configured_live_trading_enabled": live,
        "live_trading_enabled": live,
        "live": live,
        "require_manual_approval_for_live": bool(config.get("require_manual_approval_for_live", True)),
        "manual_approval_mechanism": config.get("manual_approval_mechanism", "dashboard_toggle_confirm_dialog"),
        "live_order_mutations_blocked": not live,
    }


def build_payload() -> dict[str, Any]:
    config = ensure_config()
    source = build_source(config)
    auto_status = load_auto_status()
    raw_items = get_positions()
    if not raw_items:
        print("dashboard skipped: empty positions")
        return {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "daily_trade_plan": load_daily_plan(),
            "source": source,
            "skipped": True,
            "reason": "empty_positions",
            "metrics": {},
            "positions": [],
            "protected_positions": [],
            "full_positions": [],
            "account_summary_error": "empty_positions",
            **dashboard_contract(config, auto_status),
        }
    account_summary = get_account_summary()
    realized_pnl = get_realized_pnl_krw()

    # 미국 종목 원화 환산용 실효환율: (계좌 미국 원화평가액) / (tossctl 미국 달러총평가액)
    # 토스앱은 종목 수익률을 원화 기준으로 표시하므로, 대시보드도 동일 기준으로 통일.
    us_market_value_usd = sum(float(r.get("marketValue") or 0) for r in raw_items if (r.get("shareHoldingsType") or "").lower() == "us")
    us_evaluated_krw = money(account_summary.get("markets", {}).get("us", {}).get("evaluated_amount")) if isinstance(account_summary, dict) else 0.0
    fx_rate = (us_evaluated_krw / us_market_value_usd) if us_market_value_usd > 0 else 1.0
    # 매입시점 환율 스냅샷 (토스앱 원화 수익률과 일치시키기 위해 보유 시작 시점 환율 고정)
    live_fx = fetch_usd_krw()
    current_fx = live_fx if live_fx > 0 else fx_rate
    buy_fx_map = {}
    for r in raw_items:
        sym = r.get("stockSymbol") or (str(r.get("stockCode") or "")[1:] if str(r.get("stockCode") or "").startswith("A") else str(r.get("stockCode") or ""))
        if (r.get("shareHoldingsType") or "").lower() == "us":
            buy_fx_map[sym] = get_buy_fx_rate(sym, current_fx)

    operating_positions, protected_positions, unassigned_positions, full_positions, exclusion_checks = allocate_position_buckets(raw_items, config, fx_rate, buy_fx_map)

    # 보호 투자원금 = 전체 평가액 - 운용 투자원금 - 미배정 투자원금
    # 보호 수량의 단가는 해당 금액을 보호 수량으로 나눈 값으로 계산한다.
    operating_by_code = {row.get("stock_code"): row for row in operating_positions}
    unassigned_by_code = {row.get("stock_code"): row for row in unassigned_positions}
    full_by_code = {row.get("stock_code"): row for row in full_positions}
    for protected in protected_positions:
        code = protected.get("stock_code")
        full = full_by_code.get(code, {})
        operating = operating_by_code.get(code, {})
        unassigned = unassigned_by_code.get(code, {})
        protected_purchase = max(
            float(full.get("evaluated_krw") or 0)
            - float(operating.get("purchase_krw") or 0)
            - float(unassigned.get("purchase_krw") or 0),
            0.0,
        )
        protected_quantity = float(protected.get("quantity") or 0)
        protected_unit_price = protected_purchase / protected_quantity if protected_quantity > 0 else 0.0
        protected["purchase_price_krw"] = round(protected_unit_price, 4)
        protected["purchase_krw"] = round(protected_purchase, 4)
        protected["pnl_krw"] = round(float(protected.get("evaluated_krw") or 0) - protected_purchase, 4)
        protected["pnl_rate"] = round(protected["pnl_krw"] / protected_purchase, 6) if protected_purchase > 0 else 0.0

    def total(rows: list[dict[str, Any]], key: str) -> float:
        return round(sum(float(r.get(key) or 0) for r in rows), 4)

    orderable_cash = money(account_summary.get("orderable_amount_krw")) if isinstance(account_summary, dict) else 0.0
    operating_eval = total(operating_positions, "evaluated_krw")
    operating_purchase = total(operating_positions, "purchase_krw")
    operating_pnl = total(operating_positions, "pnl_krw")
    protected_eval = total(protected_positions, "evaluated_krw")
    protected_purchase = total(protected_positions, "purchase_krw")
    protected_pnl = total(protected_positions, "pnl_krw")
    unassigned_eval = total(unassigned_positions, "evaluated_krw")
    unassigned_purchase = total(unassigned_positions, "purchase_krw")
    unassigned_pnl = total(unassigned_positions, "pnl_krw")
    current_operating_capital = round(operating_eval + orderable_cash, 4)
    initial_policy = "fixed_config"
    initial_position_purchase = operating_purchase
    initial_cash = orderable_cash
    initial_operating_capital = float(config.get("initial_operating_capital_krw", DEFAULT_CONFIG["initial_operating_capital_krw"]))
    initial_components = [
        {
            "kind": "position_purchase_basis",
            "stock_code": row.get("stock_code"),
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "quantity": row.get("quantity"),
            "purchase_price_krw": row.get("purchase_price_krw"),
            "purchase_basis_source": row.get("purchase_basis_source"),
            "purchase_krw": row.get("purchase_krw"),
        }
        for row in operating_positions
    ]
    initial_components.append(
        {
            "kind": "cash",
            "name": "계좌잔액",
            "purchase_krw": round(initial_cash, 4),
            "purchase_basis_source": "orderable_cash",
        }
    )
    return_rate = operating_return_rate(current_operating_capital, initial_operating_capital)
    payload = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "daily_trade_plan": load_daily_plan(),
        "source": source,
        "live_trading_active": bool(config.get("live_trading_enabled")),
        "config": config,
        "metrics": {
            "account_total_asset_krw": money(account_summary.get("total_asset_amount")) if isinstance(account_summary, dict) else 0.0,
            "account_evaluated_amount_krw": money(account_summary.get("markets", {}).get("kr", {}).get("evaluated_amount")) if isinstance(account_summary, dict) else 0.0,
            "account_principal_krw": money(account_summary.get("markets", {}).get("kr", {}).get("principal_amount")) if isinstance(account_summary, dict) else 0.0,
            "account_profit_loss_krw": money(account_summary.get("evaluated_profit_amount")) if isinstance(account_summary, dict) else 0.0,
            "account_profit_loss_rate": rate(account_summary.get("profit_rate")) if isinstance(account_summary, dict) else 0.0,
            "broker_buying_power_krw": orderable_cash,
            "operating_cash_krw": orderable_cash,
            "operating_cash_policy": config.get("operating_cash_policy"),
            "initial_operating_capital_policy": initial_policy,
            "initial_position_purchase_krw": initial_position_purchase,
            "initial_cash_krw": initial_cash,
            "initial_operating_capital_krw": initial_operating_capital,
            "initial_operating_capital_note": config.get("initial_operating_capital_note"),
            "reset_initial_operating_capital_at_live_start": bool(config.get("reset_initial_operating_capital_at_live_start", False)),
            "current_operating_capital_krw": current_operating_capital,
            "operating_return_rate": return_rate,
            "operating_evaluated_krw": operating_eval,
            "operating_purchase_krw": operating_purchase,
            "operating_profit_loss_krw": operating_pnl,
            "operating_profit_loss_rate": 0.0 if operating_purchase <= 0 else round(operating_pnl / operating_purchase, 6),
            "protected_evaluated_krw": protected_eval,
            "protected_purchase_krw": protected_purchase,
            "protected_profit_loss_krw": protected_pnl,
            "protected_profit_loss_rate": 0.0 if protected_purchase <= 0 else round(protected_pnl / protected_purchase, 6),
            "unassigned_not_in_jarvis_operation_evaluated_krw": unassigned_eval,
            "unassigned_not_in_jarvis_operation_purchase_krw": unassigned_purchase,
            "unassigned_not_in_jarvis_operation_profit_loss_krw": unassigned_pnl,
            "unassigned_not_in_jarvis_operation_profit_loss_rate": 0.0 if unassigned_purchase <= 0 else round(unassigned_pnl / unassigned_purchase, 6),
            "domestic_tactical_evaluated_krw": total([p for p in operating_positions if p.get("share_holdings_type") == "kr"], "evaluated_krw"),
            "overseas_tactical_evaluated_krw": total([p for p in operating_positions if p.get("share_holdings_type") == "us"], "evaluated_krw"),
            # 실현+평가 합계 수익률: (평가손익 + 순실현) / 투자원금(국내+해외 principal)
            "_principal_kr": money(account_summary.get("markets", {}).get("kr", {}).get("principal_amount")) if isinstance(account_summary, dict) else 0.0,
            "_principal_us": money(account_summary.get("markets", {}).get("us", {}).get("principal_amount")) if isinstance(account_summary, dict) else 0.0,
            "total_pnl_krw": round(float(money(account_summary.get("evaluated_profit_amount")) if isinstance(account_summary, dict) else 0.0) + realized_pnl, 2),
            "total_pnl_rate": (lambda p, e: round((e + realized_pnl) / max(p, 1) * 100, 2) if p > 0 else 0.0)(
                (money(account_summary.get("markets", {}).get("kr", {}).get("principal_amount")) if isinstance(account_summary, dict) else 0.0)
                + (money(account_summary.get("markets", {}).get("us", {}).get("principal_amount")) if isinstance(account_summary, dict) else 0.0),
                float(money(account_summary.get("evaluated_profit_amount")) if isinstance(account_summary, dict) else 0.0),
            ),
        },
        "exclusion_checks": exclusion_checks,
        "initial_operating_capital_components": initial_components,
        "auto_trading_status": auto_status,
        **dashboard_contract(config, auto_status),
        "agabang_reference": config.get("agabang_reference", {}),
        "overseas_risk_considerations": config.get("overseas_risk_considerations", []),
        "positions": operating_positions,
        "protected_positions": protected_positions,
        "unassigned_not_in_jarvis_operation": unassigned_positions,
        "full_positions": full_positions,
        "account_summary_error": account_summary.get("error") if isinstance(account_summary, dict) else None,
        "kr_screen_candidates": load_kr_screen_candidates(),
        "toss_auth": get_toss_auth_status(),
    }
    update_history(payload)
    payload["history"] = read_history()
    atomic_write_json(DATA_FILE, payload)
    write_dashboard_to_db(payload)
    return payload


def read_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def update_history(payload: dict[str, Any]) -> None:
    metrics = payload.get("metrics") or {}
    point = {
        "generated_at": payload.get("generated_at"),
        "metric": "current_operating_capital",
        "current_operating_capital_krw": metrics.get("current_operating_capital_krw"),
        "initial_operating_capital_krw": metrics.get("initial_operating_capital_krw"),
        "operating_return_rate": metrics.get("operating_return_rate"),
        "operating_evaluated_krw": metrics.get("operating_evaluated_krw"),
        "protected_evaluated_krw": metrics.get("protected_evaluated_krw"),
        "account_total_asset_krw": metrics.get("account_total_asset_krw"),
    }
    if point["current_operating_capital_krw"] is None:
        return
    # account_total_asset_krw가 0/null이면 스냅샷 자체를 기록하지 않음 (flat line 방지)
    if not point["account_total_asset_krw"]:
        return
    # 파일 락으로 직렬화: capture-intraday-snapshot.py와 동시 쓰기 레이스 방지
    with HISTORY_FILE.open("r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            try:
                history = json.loads(f.read() or "[]")
            except Exception:
                history = []
            if not isinstance(history, list):
                history = []
            if not history or history[-1].get("current_operating_capital_krw") != point["current_operating_capital_krw"]:
                history.append(point)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(history[-1200:], ensure_ascii=False, indent=2) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


if __name__ == "__main__":
    payload = build_payload()
    if payload.get("skipped"):
        print(f"dashboard skipped at {payload['generated_at']}: {payload.get('reason')}")
        raise SystemExit(0)
    m = payload["metrics"]
    print(
        "dashboard-data.json updated | "
        f"generated_at={payload['generated_at']} | "
        f"operating={m['current_operating_capital_krw']:.0f} | "
        f"protected={m['protected_evaluated_krw']:.0f}"
    )
