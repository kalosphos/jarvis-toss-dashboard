#!/usr/bin/env python3
"""jarvis_daily_briefing.py — 09:00 KST 운용 브리핑 생성기 (NAS 독립 실행).

대시보드 허용 필드만 투영:
  status / generated_at / summary / evidence / red_team / action_labels

포함 내용:
- 실행 안전(실행 안전 분류 + 이유)
- 당일 승인 상태(승인 여부 + 시각)
- 당일 계획 요약
- 위험 플래그 요약
- 신호 제안(참고용)
- 거시/정세(briefing-macro.json 또는 비어 있음)

외부 거시 소스: web_search 도구 부재로 briefing-macro.json(사용자 갱신) 또는
추후 RSS/뉴스 API 연동 지점(macro_sources)으로 채움. 없으면 빈 섹션.

실거래와 무관. 참고용이며 실거래 gate(대시보드 토글)와 독립.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("JARVIS_TOSS_ROOT") or "/var/services/web/toss").expanduser()
DATA_FILE = ROOT / "dashboard-data.json"
BRIEFING_FILE = ROOT / "ai-daily-briefing.json"
BRIEFING_HISTORY_FILE = ROOT / "ai-daily-briefing-history.json"
MACRO_FILE = ROOT / "briefing-macro.json"
NEWS_BRIEFING_FILE = ROOT / "news_briefing.json"
BRIEFING_HISTORY_LIMIT = 30
KST = timezone(timedelta(hours=9))

# 대시보드 표시 허용 필드 only (비밀 필터링)
ALLOWED_BRIEFING_FIELDS = (
    "state",
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
    "news",
    "advisory",
)

NEWS_BRIEFING_FILE = ROOT / "news_briefing.json"


def load_news_briefing() -> dict:
    """08시 뉴스 수집 단계가 만든 news_briefing.json을 읽는다 (파이프라인 연결)."""
    if not NEWS_BRIEFING_FILE.exists():
        return {}
    try:
        data = json.loads(NEWS_BRIEFING_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def summarize_news(news: dict) -> dict:
    """대시보드 표시용 뉴스 요약 (허용 필드만)."""
    if not isinstance(news, dict):
        return {}
    return {
        "generated_at": safe_text(news.get("generated_at")),
        "per_position": news.get("per_position") if isinstance(news.get("per_position"), dict) else {},
        "global_risks": news.get("global_risks") if isinstance(news.get("global_risks"), list) else [],
        "calendar": news.get("calendar") if isinstance(news.get("calendar"), list) else [],
    }


def news_one_liner(news: dict) -> str:
    """summary에 편입할 뉴스 한 줄. 없으면 빈 문자열."""
    if not isinstance(news, dict):
        return ""
    parts = []
    risks = news.get("global_risks") if isinstance(news.get("global_risks"), list) else []
    cal = news.get("calendar") if isinstance(news.get("calendar"), list) else []
    if risks:
        parts.append(f"글로벌 리스크 {len(risks)}건")
    if cal:
        parts.append(f"경제일정 {len(cal)}건")
    pos = news.get("per_position") if isinstance(news.get("per_position"), dict) else {}
    named = [v.get("name") for v in pos.values() if isinstance(v, dict) and v.get("name")]
    if named:
        parts.append("보유뉴스: " + ", ".join(named[:4]))
    return " | ".join(parts)


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_macro() -> dict:
    """사용자가 갱신하는 거시경제/정세 컨텍스트."""
    try:
        return json.loads(MACRO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_dashboard_data() -> dict:
    """대시보드 데이터를 로컬에서 직접 읽는다 (Mac mount 불필요)."""
    return load_json(DATA_FILE, {})


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    # 마크다운/HTML 유출 방지: 제어문자 정리, 길이 제한
    s = "".join(ch if ch.isprintable() or ch in "\n\t" else "" for ch in s)
    return s.strip()[:2000]


def summarize_execution_safety(exec_safety: dict) -> dict:
    """대시보드 execution_safety를 브리핑 요약으로 투영."""
    classification = safe_text(exec_safety.get("classification"))
    reason_ko = safe_text(exec_safety.get("reason_ko"))
    return {
        "classification": classification,
        "reason_ko": reason_ko,
        "controller_gated_notice": safe_text(
            exec_safety.get("controller_gated_notice", "")
        ),
    }


def summarize_trade_control(trade_control: dict) -> dict:
    """당일승인상태를 브리핑 요약으로 투영."""
    return {
        "enabled": bool(trade_control.get("enabled")),
        "updated_at": safe_text(trade_control.get("updated_at")),
        "valid": bool(trade_control.get("valid")),
    }


def summarize_daily_plan(daily_plan: dict) -> dict:
    """당일계획 요약을 브리핑용으로 투영."""
    if not isinstance(daily_plan, dict):
        return {}
    return {
        "date": safe_text(daily_plan.get("date")),
        "status": safe_text(daily_plan.get("status")),
        "summary": safe_text(daily_plan.get("summary")),
        "generated_at": safe_text(daily_plan.get("generated_at")),
    }


def summarize_risk_flags(risk_flags: list) -> dict:
    """위험 플래그 요약. block 레벨만 분류해서 표시."""
    if not isinstance(risk_flags, list):
        return {"block_count": 0, "items": []}
    blocks = [f for f in risk_flags if isinstance(f, dict) and f.get("level") == "block"]
    return {
        "block_count": len(blocks),
        "items": [
            {
                "key": safe_text(f.get("key")),
                "message": safe_text(f.get("message")),
            }
            for f in blocks[:10]
        ],
    }


def summarize_signals(positions: list, kr_screen: list) -> dict:
    """참고용 신호 제안. 실제 주문 추천 아님."""
    suggestions: list[dict[str, str]] = []

    # KR 스크린 후보(있을 때만)
    if isinstance(kr_screen, list) and kr_screen:
        top = kr_screen[:5]
        names = ", ".join(str(c.get("name", "")) for c in top if c.get("name"))
        if names:
            suggestions.append({
                "label": "KR 스크린 참고",
                "detail": f"스크린 후보 {len(top)}건: {names} (참고용, 매수 추천 아님)",
            })

    # 포지션 기반 제안(있을 때만)
    if isinstance(positions, list) and positions:
        op_positions = [
            p for p in positions
            if str(p.get("bucket", "")) == "jarvis_operation"
        ]
        if op_positions:
            down = [p for p in op_positions if float(p.get("daily_rate") or 0) <= -0.03]
            if down:
                names = ", ".join(
                    f"{p.get('name')}({p.get('symbol')})" for p in down[:5]
                )
                suggestions.append({
                    "label": "변동성 확대 참고",
                    "detail": f"일간 등락률 -3% 이하 운용 포지션 {len(down)}건: {names} (참고용)",
                })

    if not suggestions:
        suggestions.append({
            "label": "참고",
            "detail": "현재 별도 신호 제안 없음 (참고용)",
        })

    return {"suggestions": suggestions, "note": "모두 참고용이며 실거래 gate와 독립"}


def build_briefing() -> dict:
    macro = load_macro()
    data = load_dashboard_data()

    # 거시/정세
    macro_sections = macro.get("sections") or []
    macro_summary = safe_text(macro.get("summary")) or "거시경제/정세 컨텍스트 미갱신 (briefing-macro.json 확인)"

    # 08시 뉴스 수집 결과 연결
    news = load_news_briefing()
    news_summary = summarize_news(news)
    news_line = news_one_liner(news)

    # 대시보드 필드 투영
    config = data.get("config") or {}
    metrics = data.get("metrics") or {}
    exec_safety = data.get("execution_safety") or {}
    trade_control = data.get("trade_control") or {}
    daily_plan = data.get("daily_trade_plan") or {}
    risk_flags = data.get("risk_flags") if isinstance(data.get("risk_flags"), list) else []
    positions = data.get("positions") or []
    kr_screen = data.get("kr_screen_candidates") or []

    execution_summary = summarize_execution_safety(exec_safety)
    approval_summary = summarize_trade_control(trade_control)
    plan_summary = summarize_daily_plan(daily_plan)
    risk_summary = summarize_risk_flags(risk_flags)
    signal_summary = summarize_signals(positions, kr_screen)

    # 위험 플래그가 있으면 요약 앞에 붙이기
    risk_note = ""
    if risk_summary["block_count"] > 0:
        risk_note = (
            f"⚠ 위험 플래그 {risk_summary['block_count']}건 차단 중: "
            + "; ".join(item["message"] for item in risk_summary["items"][:3])
        )

    dashboard_notes = []
    if execution_summary["classification"]:
        detail = f"실행 안전: {execution_summary['classification']}"
        if execution_summary["reason_ko"]:
            detail += f" ({execution_summary['reason_ko']})"
        dashboard_notes.append(detail)
    dashboard_notes.append(
        f"당일 승인: {'활성' if approval_summary['enabled'] and approval_summary['valid'] else '미승인'}"
    )
    if plan_summary["summary"] or plan_summary["status"]:
        dashboard_notes.append(
            f"당일 계획: {plan_summary['summary'] or plan_summary['status']}"
        )
    if risk_note:
        dashboard_notes.append(risk_note)
    if news_line:
        dashboard_notes.append(news_line)
    summary = f"[09시 운용 브리핑] {macro_summary} | " + " | ".join(dashboard_notes)

    briefing = {
        "status": "available",
        "generated_at": now_kst(),
        "summary": summary,
        "evidence": {
            "execution_safety": execution_summary,
            "approval_state": approval_summary,
            "daily_plan": plan_summary,
            "risk_flags": risk_summary,
            "signals": signal_summary,
            "macro_sections": macro_sections,
            "source": "dashboard-data.json (local, NAS-independent) + briefing-macro.json (user-curated) + news_briefing.json (08시 수집)",
            "note": "거시/정세 및 신호는 참고용이며 실제 주문 결정은 대시보드 토글 게이트·당일 승인·당일 계획을 따름",
            "news": news_summary,
        },
        "red_team": [
            {"안전이유": "브리핑은 참고용이며 실거래 gate(대시보드 토글)와 독립."},
            {"가드레일위험플래그": "briefing_is_advisory_only"},
            {"근거": "execution_safety/approval_state/daily_plan/risk_flags는 대시보드 허용 필드만 투영."},
        ],
        "action_labels": ["참고용", "실거래와 무관", "제안"],
        # 확장 필드(대시보드 표시용)
        "execution_safety": execution_summary,
        "approval_state": approval_summary,
        "daily_plan": plan_summary,
        "risk_flags": risk_summary,
        "signals": signal_summary,
        "macro": {
            "summary": macro_summary,
            "sections": macro_sections,
        },
        "news": news_summary,
        "advisory": True,
    }
    return briefing


def project_allowed(briefing: dict) -> dict:
    """대시보드 표시 허용 필드만 남긴 프로젝션."""
    result: dict = {}
    for key in ALLOWED_BRIEFING_FIELDS:
        if key in briefing:
            result[key] = briefing[key]
    result.setdefault("status", "available")
    return result


def merge_briefing_history(current: dict, history: Any) -> list[dict]:
    """Keep only projected records, deduplicated by generated_at, newest first."""
    records = [current] + (history if isinstance(history, list) else [])
    result: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        projected = project_allowed(record)
        generated_at = projected.get("generated_at")
        if not isinstance(generated_at, str) or not generated_at or generated_at in seen:
            continue
        seen.add(generated_at)
        result.append(projected)
    return sorted(result, key=lambda item: item["generated_at"], reverse=True)[:BRIEFING_HISTORY_LIMIT]


def write_json_with_retry(path: Path, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    last_err = None
    for attempt in range(3):
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            return
        except Exception as e:
            last_err = e
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(0.3 * (attempt + 1))
    try:
        path.write_text(text, encoding="utf-8")
    except Exception as e:
        raise last_err or e


def write_briefing_history(briefing: dict) -> None:
    """Append the safe projection only; malformed history is treated as empty."""
    history = load_json(BRIEFING_HISTORY_FILE, [])
    write_json_with_retry(BRIEFING_HISTORY_FILE, merge_briefing_history(project_allowed(briefing), history))


def write_briefing(briefing: dict) -> None:
    """ai-daily-briefing.json에 허용 필드 프로젝션 저장."""
    write_json_with_retry(BRIEFING_FILE, project_allowed(briefing))


def write_dashboard_ai_briefing(briefing: dict) -> None:
    """dashboard-data.json의 ai_briefing 필드만 갱신(허용 필드 프로젝션)."""
    data = load_dashboard_data()
    allowed = dict(project_allowed(briefing))
    data["ai_briefing"] = allowed
    data["ai_briefing_history"] = merge_briefing_history(allowed, load_json(BRIEFING_HISTORY_FILE, []))
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = DATA_FILE.with_suffix(DATA_FILE.suffix + ".tmp")
    last_err = None
    for attempt in range(3):
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(DATA_FILE)
            return
        except Exception as e:
            last_err = e
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(0.3 * (attempt + 1))
    try:
        DATA_FILE.write_text(text, encoding="utf-8")
    except Exception as e:
        raise last_err or e


def self_test() -> bool:
    global load_macro, load_dashboard_data
    b = build_briefing()
    required = ("status", "generated_at", "summary", "evidence", "red_team", "action_labels", "macro", "advisory")
    projected = project_allowed(b)
    history = merge_briefing_history(
        {**projected, "generated_at": "2026-01-03T09:00:00+09:00"},
        [{"generated_at": "2026-01-02T09:00:00+09:00", "summary": "older", "secret": "blocked"}, {"generated_at": "2026-01-03T09:00:00+09:00", "summary": "duplicate"}],
    )
    original_macro, original_dashboard = load_macro, load_dashboard_data
    try:
        load_macro = lambda: {"summary": "고정 거시"}
        load_dashboard_data = lambda: {
            "execution_safety": {"classification": "safe", "reason_ko": "정상"},
            "trade_control": {"enabled": False, "valid": False},
            "daily_trade_plan": {"status": "hold", "summary": "대기"},
        }
        first_summary = build_briefing()["summary"]
        load_dashboard_data = lambda: {
            "execution_safety": {"classification": "blocked", "reason_ko": "차단"},
            "trade_control": {"enabled": True, "valid": True},
            "daily_trade_plan": {"status": "ready", "summary": "검토"},
        }
        second_summary = build_briefing()["summary"]
    finally:
        load_macro, load_dashboard_data = original_macro, original_dashboard
    dynamic_summary = (
        first_summary != second_summary
        and "실행 안전: safe (정상)" in first_summary
        and "당일 승인: 미승인" in first_summary
        and "당일 계획: 대기" in first_summary
        and "실행 안전: blocked (차단)" in second_summary
        and "당일 승인: 활성" in second_summary
        and "당일 계획: 검토" in second_summary
    )
    ok = (
        all(k in projected for k in required)
        and len(history) == 2
        and "secret" not in history[1]
        and dynamic_summary
    )
    print(
        f"self_test: {'OK' if ok else 'FAIL'} history={len(history)} "
        f"dynamic_summary={dynamic_summary} keys={list(projected.keys())}"
    )
    return ok


def _kst_date(generated_at: str | None) -> str:
    """generated_at(KST ISO)에서 YYYY-MM-DD만 추출, 실패 시 빈 문자열."""
    if not isinstance(generated_at, str) or len(generated_at) < 10:
        return ""
    return generated_at[:10]


def main() -> int:
    if "--self-test" in sys.argv:
        return 0 if self_test() else 1

    # 날짜 기준 중복 방지: 오늘(KST) 이미 브리핑을 생성했으면 스킵.
    # 요약 텍스트가 같아도 다른 날이면 신규 항목으로 갱신된다.
    history = load_json(BRIEFING_HISTORY_FILE, [])
    today = _kst_date(now_kst())
    already_today = bool(history) and _kst_date(history[0].get("generated_at")) == today

    if already_today:
        print(f"briefing skipped: already generated today ({today})")
        return 0

    briefing = build_briefing()

    write_briefing(briefing)
    write_briefing_history(briefing)
    write_dashboard_ai_briefing(briefing)
    print(f"briefing written: {BRIEFING_FILE}")
    print(f"dashboard-data.json ai_briefing updated")
    print(json.dumps({
        "generated_at": briefing["generated_at"],
        "summary": briefing["summary"][:200],
        "execution_classification": briefing["evidence"]["execution_safety"]["classification"],
        "approval_enabled": briefing["evidence"]["approval_state"]["enabled"],
        "risk_block_count": briefing["evidence"]["risk_flags"]["block_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
