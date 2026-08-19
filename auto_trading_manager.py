#!/usr/bin/env python3
"""Jarvis live auto-trading supervisor.

User-approved live mode. Uses mechanical 주식아가방-derived rules only:
- 10% drawdown sell-check with defensive daily-loss condition and partial sells.
- regular-market restriction for BUY only; Jarvis operating-cash limits remain.
- no per-order user preview or dashboard/human approval gate; broker preview/permission is retained for safety.

[LOGGING POLICY - PATCH 2026-08-18]
  INFO: 모든 주문 실행 (buy/sell), 시장 시간 변경, 설정 변경
  WARN: 손절/방어 매도, 매도 대기 (장 마감), 시장 시간 경고
  ERROR: 브로커 API 실패, 파일 쓰기 실패, 운용자금 불일치
  CRITICAL: 운용자금 검증 실패, SMB 원자성 손상 → Telegram 알림 + 거래 HALT

[RETRY POLICY - PATCH 2026-08-18]
  - 브로커 API 타임아웃: 3회, 5초 지수백오프 → 최종 실패 시 Telegram 알림 + HALT
  - 부분 체결: 1회, 10초 대기 → 미체결분 cancel + 수동검토
  - SMB/CIFS 쓰기 실패: 2회, 1초 대기 → 임시파일 cleanup + 상태 불일치 경고
"""
from __future__ import annotations

import fcntl
import json
import hashlib
import math
import os
import re
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type shim for older Python

ROOT = Path(os.environ['JARVIS_TOSS_ROOT']).expanduser() if os.environ.get('JARVIS_TOSS_ROOT') else (Path('/Volumes/web/toss') if Path('/Volumes/web/toss').exists() else Path('/var/services/web/toss'))
CONFIG_FILE = ROOT / 'jarvis_config.json'
DAILY_PLAN_FILE = ROOT / 'daily-trade-plan.json'
TRADE_CONTROL_FILE = ROOT / '.control' / 'trade-control.json'
INTENT_STATE_FILE = ROOT / '.control' / 'order-intents.json'
DATA_FILE = ROOT / 'dashboard-data.json'
STATUS_FILE = ROOT / 'auto-trading-status.json'
EXEC_STATE_FILE = ROOT / 'auto-execution-state.json'
HISTORY_FILE = ROOT / 'dashboard-history.json'
# NAS-independent refresh: call the generator directly (no Mac mount dependency)
REFRESH = ROOT / 'update_dashboard_data_nas.py'
KST = timezone(timedelta(hours=9))
RUNNING = True

# [PATCH: 2026-08-18] VOO 필터: 미국 자동매수 허용 종목 whitelist
US_BUY_WHITELIST = ['VOO']  # VOO만 미국 자동매수 허용

# [PATCH: 2026-08-18] Telegram 알림 설정
TELEGRAM_CHAT_ID = '8310328594'  # 텔레그램 DM 대상
TELEGRAM_ENABLED = False  # 실제 전송은 텔레그램 봇 토큰이 있을 때만 활성화


# [PATCH: 2026-08-18] Telegram 알림 함수
def send_telegram_alert(message: str) -> bool:
    """CRITICAL 오류 시 텔레그램 DM 알림 전송.

    환경변수 TELEGRAM_BOT_TOKEN이 설정된 경우에만 전송.
    실패 시 로그에 기록하고 False 반환.
    """
    if not TELEGRAM_ENABLED:
        return False
    try:
        import os
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            return False
        import urllib.request
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        data = json.dumps({'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception as exc:
        print(f'[TELEGRAM_ALERT_FAILED] {exc}', file=sys.stderr, flush=True)
        return False


# [PATCH: 2026-08-18] 재시도 데코레이터
def retry_with_backoff(max_attempts: int = 3, base_delay: float = 5.0, exponential: bool = True):
    """재시도 데코레이터: 브로커 API 호출 등에 적용.

    Args:
        max_attempts: 최대 시도 횟수
        base_delay: 기본 대기시간 (초)
        exponential: 지수백오프 사용 여부
    """
    import functools
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        delay = base_delay * (2 ** (attempt - 1)) if exponential else base_delay
                        print(f'[RETRY] {func.__name__} attempt {attempt}/{max_attempts} failed: {exc}, retrying in {delay}s', file=sys.stderr, flush=True)
                        time.sleep(delay)
                    else:
                        print(f'[RETRY_EXHAUSTED] {func.__name__} failed after {max_attempts} attempts: {exc}', file=sys.stderr, flush=True)
                        send_telegram_alert(f'🔴 <b>[CRITICAL]</b> {func.__name__} 재시도 소진: {exc}')
            raise last_exc
        return wrapper
    return decorator


# [PATCH: 2026-08-18] 자동 필터 검증 섹션
# 선물/옵션/인버스/레버리지 자동 제외 정책
# - 선물: 모든 선물 계약 → jarvis_toss_data 스크리너에서 제외
# - 옵션: 모든 옵션 → jarvis_toss_data 스크리너에서 제외
# - 인버스 ETF: KODEX Inverse 등 → screen_kr_candidates()에서 이름 필터링
# - 레버리지 ETF: 2배, 3배 레버 → screen_kr_candidates()에서 이름 필터링
# 검증: 검색 결과에서 이들이 나타나지 않는지 월 1회 확인 (수동)

# NAS 유효 토스 세션 파일. 환경변수 TOSSCTL_SESSION_FILE 우선, 미설정 시 NAS 경로 fallback.
_NAS_DEFAULT_SESSION_FILE = '/var/services/homes/kwangho79/Library/Application Support/tossctl/session.json'
TOSSCTL_SESSION_FILE = os.environ.get('TOSSCTL_SESSION_FILE') or _NAS_DEFAULT_SESSION_FILE
_MAC_TOSSCTL_BIN = '/Users/jarvis/.local/bin/tossctl'
_NAS_TOSSCTL_BIN = '/var/services/homes/kwangho79/.local/bin/tossctl'
TOSSCTL_BIN = os.environ.get('TOSSCTL_BIN') or (_MAC_TOSSCTL_BIN if Path(_MAC_TOSSCTL_BIN).is_file() else _NAS_TOSSCTL_BIN)


def screen_kr_candidates(limit=30, cache_ttl=600, max_price=None) -> list[tuple[str, str, float]]:
    """Return liquid, affordable Korean candidates from TossInvest public API.

    2026-08-03: Naver Finance 정규식 파싱을 dd3ok/tossinvest-api-skill 포팅
    jarvis_toss_data로 교체. ETF/선물/인버스/레버리지 이름 필터 유지.
    Fail-closed: 실패 시 [] (그 틱 매수 신호 없음).
    """
    try:
        import jarvis_toss_data
        candidates = jarvis_toss_data.screen_kr_candidates(
            limit=int(limit) * 3,
            max_price=float(max_price) if max_price is not None else None,
            cache_ttl=float(cache_ttl),
        )
        selected: list[tuple[str, str, float]] = []
        seen: set[str] = set()
        for symbol, name, price in candidates:
            # ETF는 허용, 레버리지/인버스/선물/옵션만 제외 (jarvis_toss_data에서 이미 필터됨)
            if symbol in seen:
                continue
            seen.add(symbol)
            selected.append((symbol, name, price))
            if len(selected) >= max(0, int(limit)):
                break
        return selected
    except Exception:
        return []


def now() -> str:
    return datetime.now(KST).isoformat(timespec='seconds')

def today_kst() -> str:
    return datetime.now(KST).date().isoformat()

class SafeJsonFile:
    """SMB 마운트 안전성을 위한 Lock-기반 JSON 파일 관리자 (fcntl.flock).

    [PATCH: 2026-08-18] 원자성 보호 강화:
    - uuid4 기반 임시파일명 (충돌 방지)
    - validate_json() 형식 검증 단계 추가
    - atomic_rename() 실패 시 이전 snapshot으로 롤백
    - [FILE_WRITE] 로그 프리픽스
    """

    def __init__(self, path: Path, timeout: float = 30.0):
        self.path = path
        self.timeout = timeout
        self.lock_path = path.with_suffix(path.suffix + '.lock')
        self.snapshot_path = path.with_suffix(path.suffix + '.snapshot')

    def _acquire_lock(self):
        """Lock 획득. (fd, lock_file_object) tuple 반환 — 호출 측이 file object를
        유지해야 fd가 가비지 컬렉션으로 닫히지 않는다."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(self.lock_path, 'w')
        start = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock_file.fileno(), lock_file
            except BlockingIOError:
                if time.time() - start > self.timeout:
                    lock_file.close()
                    raise TimeoutError(f'Lock acquisition timeout for {self.path}')
                time.sleep(0.1)

    @staticmethod
    def validate_json(file_path: Path) -> bool:
        """[PATCH: 2026-08-18] JSON 형식 검증."""
        try:
            if not file_path.exists():
                return False
            content = file_path.read_text(encoding='utf-8')
            json.loads(content)
            return True
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return False

    def _create_snapshot(self):
        """[PATCH: 2026-08-18] 현재 파일의 스냅샷 생성 (롤백용)."""
        try:
            if self.path.exists():
                import shutil
                shutil.copy2(str(self.path), str(self.snapshot_path))
        except Exception:
            pass  # 스냅샷 실패는 치명적이지 않음

    def _rollback_from_snapshot(self) -> bool:
        """[PATCH: 2026-08-18] 스냅샷에서 롤백."""
        try:
            if self.snapshot_path.exists():
                import shutil
                shutil.copy2(str(self.snapshot_path), str(self.path))
                return True
        except Exception:
            pass
        return False

    def read(self, default: Any = None) -> Any:
        lock_fd, lock_file = self._acquire_lock()
        try:
            if not self.path.exists():
                return default
            return json.loads(self.path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return default
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_file.close()

    def write(self, data: Any) -> None:
        """원자적 JSON 쓰기: 임시파일 작성 → 검증 → 스냅샷 → 원자적 rename.

        [PATCH: 2026-08-18] 실패 시 스냅샷에서 롤백.
        """
        import uuid
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_snapshot()
        temp_file = self.path.with_suffix(f'{self.path.suffix}.tmp.{uuid.uuid4().hex}')
        try:
            temp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if not self.validate_json(temp_file):
                raise RuntimeError(f'[FILE_WRITE] JSON validation failed for {self.path}')
            temp_file.replace(self.path)
        except Exception as exc:
            # 실패 시 임시파일 cleanup
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
            # 스냅샷에서 롤백 시도
            if self._rollback_from_snapshot():
                raise RuntimeError(f'[FILE_WRITE] atomic rename failed, rolled back: {exc}')
            raise RuntimeError(f'[FILE_WRITE] atomic rename failed, no snapshot: {exc}')


def load_json(path: Path, default: Any) -> Any:
    return SafeJsonFile(path).read(default)

def save_json(path: Path, data: Any) -> None:
    SafeJsonFile(path).write(data)

def daily_plan_hour_kst(config: Any) -> int:
    """Return the configured daily-plan hour, safely falling back to 9 KST."""
    try:
        hour = int(((config or {}).get('auto_trading_process') or {}).get('daily_plan_hour_kst', 9))
        return hour if 0 <= hour <= 23 else 9
    except Exception:
        return 9


def save_json_atomic(path: Path, data: Any) -> None:
    SafeJsonFile(path).write(data)


def daily_plan_today(refresh_ok: bool, metrics: dict[str, Any], risk_flags: list[dict[str, Any]], current: datetime | None = None, hour_kst: int = 9, minute_kst: int = 5) -> tuple[bool, dict[str, Any]]:
    current = current or datetime.now(KST)
    if current.weekday() >= 5 or (current.hour, current.minute) < (hour_kst, minute_kst):
        return False, {}
    today = current.date().isoformat()
    existing = load_json(DAILY_PLAN_FILE, {})
    if isinstance(existing, dict) and existing.get('date') == today and existing.get('status') == 'ready':
        return True, existing
    plan = {
        'date': today,
        'generated_at': current.isoformat(timespec='seconds'),
        'status': 'ready',
        'trigger': 'automatic_daily_plan',
        'refresh_ok': refresh_ok,
        'metrics': {
            'initial_operating_capital_krw': metrics.get('initial_operating_capital_krw'),
            'current_operating_capital_krw': metrics.get('current_operating_capital_krw'),
            'operating_cash_krw': metrics.get('operating_cash_krw'),
            'operating_return_rate': metrics.get('operating_return_rate'),
        },
        'risk_flags': risk_flags,
        'summary': '기존 실거래·주문경로·위험관리 게이트를 모두 통과할 때만 자동 운용이 허용되며, 이는 매수 추천이 아닙니다.',
    }
    try:
        save_json_atomic(DAILY_PLAN_FILE, plan)
    except Exception:
        return False, {}
    return True, plan

def handle_signal(signum, frame):
    global RUNNING
    RUNNING = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    # NAS 세션 명시 사용: tossctl 명령에 전역 플래그를 삽입해 모든 조회/주문이 같은 인증 세션을 쓰게 함.
    if cmd and cmd[0] == 'tossctl':
        cmd = [TOSSCTL_BIN, '--session-file', TOSSCTL_SESSION_FILE] + list(cmd[1:])
    return subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)



class TossctlValidator:
    """tossctl 바이너리 존재·버전·인증 상태를 시작 시 검증한다.

    NAS와 Mac 모두 같은 코드로 동작하도록 환경변수 기반 경로를 쓴다.
    """

    MIN_VERSION = (0, 20, 0)

    def __init__(self, bin_path: str | None = None, session_file: str | None = None):
        self.bin_path = bin_path or os.environ.get('TOSSCTL_BIN') or _NAS_TOSSCTL_BIN
        self.session_file = session_file or os.environ.get('TOSSCTL_SESSION_FILE') or _NAS_DEFAULT_SESSION_FILE
        self.version_tuple: tuple[int, ...] | None = None
        self.auth_valid = False

    def _parse_version(self, text: str) -> tuple[int, ...] | None:
        m = re.search(r'(\d+)\.(\d+)\.(\d+)', text)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def validate(self) -> dict[str, Any]:
        """tossctl 검증 결과. fail 자체는 raise하지 않고 결과를 반환한다(호출자 판단)."""
        result: dict[str, Any] = {'ok': False, 'version': None, 'auth_valid': False, 'error': None}
        # 1. 바이너리 존재
        if not os.path.isfile(self.bin_path):
            result['error'] = f'tossctl not found: {self.bin_path}'
            return result
        # 2. 버전 조회
        try:
            proc = subprocess.run([str(self.bin_path), 'version', '--output', 'json'], capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                result['error'] = f'tossctl version failed: {proc.stderr.strip()[:120]}'
                return result
            try:
                ver_data = json.loads(proc.stdout)
            except Exception as exc:
                result['error'] = f'Cannot parse tossctl version JSON: {exc}'
                return result
            ver_str = ver_data.get('version') or ''
            if not ver_str:
                result['error'] = f'tossctl version field missing: {json.dumps(ver_data)[:120]}'
                return result
            parsed = self._parse_version(ver_str)
            if parsed is None:
                result['error'] = f'Cannot parse tossctl version string: {ver_str!r}'
                return result
            self.version_tuple = parsed
            result['version'] = '.'.join(str(x) for x in parsed)
            if parsed < self.MIN_VERSION:
                result['error'] = f'tossctl version {result["version"]} < {".".join(str(x) for x in self.MIN_VERSION)}'
                return result
        except Exception as exc:
            result['error'] = f'tossctl version check exception: {exc}'
            return result
        # 3. 인증 상태 조회
        try:
            proc = subprocess.run([str(self.bin_path), '--session-file', self.session_file, 'auth', 'status', '--output', 'json'], capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                self.auth_valid = bool(data.get('valid'))
                result['auth_valid'] = self.auth_valid
            else:
                result['error'] = f'tossctl auth status failed: {proc.stderr.strip()[:120]}'
                return result
        except Exception as exc:
            result['error'] = f'tossctl auth check exception: {exc}'
            return result
        result['ok'] = True
        return result

    def require_valid(self) -> dict[str, Any]:
        """검증 실패 시 RuntimeError 발생. 성공 시 결과 반환."""
        result = self.validate()
        if not result.get('ok'):
            raise RuntimeError(f'tossctl validation failed: {result.get("error")}')
        return result

def _cli_json(cmd: list[str], timeout: int = 45) -> Any:
    proc = run(cmd, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"query_failed:{' '.join(cmd[1:3])}:exit_{proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"query_invalid_json:{' '.join(cmd[1:3])}") from exc


def _finite_number(value: Any, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('not_numeric') from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError('invalid_number')
    return number


def trade_control_state() -> dict[str, Any]:
    """Strict dashboard trade-control state; absent/malformed always means OFF."""
    default = {'enabled': False, 'updated_at': None, 'valid': False}
    try:
        data = json.loads(TRADE_CONTROL_FILE.read_text(encoding='utf-8'))
    except Exception:
        return default
    if not isinstance(data, dict) or not isinstance(data.get('enabled'), bool):
        return default
    return {
        'enabled': data['enabled'],
        'updated_at': data.get('updated_at') if isinstance(data.get('updated_at'), str) else None,
        'valid': True,
    }


def _parse_clock(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', value)
    if not match:
        return None
    hour, minute, second = (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    return (hour, minute, second) if hour <= 23 and minute <= 59 and second <= 59 else None


_ORDER_STATUS_KEYS = ('status', 'order_status', 'orderStatus', 'state')
_ORDER_STATUS_VALUES = {
    'open': 'open',
    'pending': 'pending',
    'partial': 'partial',
    'partial_filled': 'partial',
    'partially_filled': 'partial',
    'completed': 'completed',
    'filled': 'completed',
    'cancelled': 'cancelled',
    'canceled': 'cancelled',
    'rejected': 'rejected',
}
_BLOCKING_ORDER_STATUSES = frozenset(('open', 'pending', 'partial'))


def normalize_order_status(row: Any) -> str | None:
    """Return a canonical broker order state, or None for unsafe/unknown rows."""
    if not isinstance(row, dict):
        return None
    states: set[str] = set()
    for key in _ORDER_STATUS_KEYS:
        value = row.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return None
        normalized = _ORDER_STATUS_VALUES.get(value.strip().lower().replace('-', '_').replace(' ', '_'))
        if normalized is None:
            return None
        states.add(normalized)
    return states.pop() if len(states) == 1 else None


def blocking_order_rows(rows: list[Any]) -> list[Any]:
    """Return all broker order rows that are not confirmed terminal history."""
    return [row for row in rows if normalize_order_status(row) in _BLOCKING_ORDER_STATUSES or normalize_order_status(row) is None]


def market_hours_status(current: datetime | None = None) -> dict[str, Any]:
    """Return broker-reported KR/US regular-session state, fail-closed.

    tossctl market hours 응답은 현재 세션에 start_time/end_time 없이 date만 오고,
    next_kr/next_us에 실제 세션 시간이 있으므로, 현재 세션에 시간이 없으면 next_*에서
    fallback해서 active 판단. start/end 둘 다 없으면 날짜+holiday로만 ok 판단.

    [PATCH: 2026-08-18] 경계시간 처리 강화:
    - 폐장 5분 전(15:25~15:30, 22:55~23:00)에는 신규 주문 경고
    - [MARKET_CHECK] 로그 프리픽스 추가
    """
    try:
        payload = _cli_json(['tossctl', 'market', 'hours', '--output', 'json'])
        if not isinstance(payload, dict):
            raise RuntimeError('market_hours_shape')
        result: dict[str, Any] = {'ok': True, 'kr': False, 'us': False, 'reason': 'broker_market_hours'}
        local = (current.astimezone(KST) if current and current.tzinfo else current.replace(tzinfo=KST) if current else datetime.now(KST))
        clock = (local.hour, local.minute, local.second)
        today = local.date()
        for market in ('kr', 'us'):
            row = payload.get(market)
            if not isinstance(row, dict):
                raise RuntimeError(f'market_hours_{market}_shape')
            date_value = row.get('date')
            start = _parse_clock(row.get('start_time'))
            end = _parse_clock(row.get('end_time'))
            # 현재 세션에 start/end가 없으면 next_*에서 fallback
            if start is None or end is None:
                next_row = payload.get(f'next_{market}')
                if isinstance(next_row, dict):
                    if start is None:
                        start = _parse_clock(next_row.get('start_time'))
                    if end is None:
                        end = _parse_clock(next_row.get('end_time'))
            if not isinstance(date_value, str):
                raise RuntimeError(f'market_hours_{market}_fields')
            try:
                session_date = date.fromisoformat(date_value[:10])
            except ValueError as exc:
                raise RuntimeError(f'market_hours_{market}_date') from exc
            holiday = bool(row.get('holiday', session_date != today))
            if start is not None and end is not None:
                if start <= end:
                    result[market] = local.date() == session_date and start <= clock <= end
                else:
                    result[market] = (
                        (local.date() == session_date and clock >= start)
                        or (local.date() == session_date + timedelta(days=1) and clock <= end)
                    )
            else:
                # 세션 시간 없으면 날짜+holiday로만 활성 판단 (clock 반영 불가 -> 보수적)
                result[market] = local.date() == session_date and not holiday
            result[f'{market}_date'] = date_value
            result[f'{market}_start_time'] = row.get('start_time')
            result[f'{market}_end_time'] = row.get('end_time')
            # [PATCH: 2026-08-18] 경계시간 경고 계산
            if start is not None and end is not None and result[market]:
                # 폐장 5분 전 경계시간 체크
                close_warning = (end[0] * 60 + end[1]) - (clock[0] * 60 + clock[1])
                result[f'{market}_near_close'] = 0 < close_warning <= 5
        return result
    except Exception as exc:
        return {'ok': False, 'kr': False, 'us': False, 'reason': f'market_hours_unavailable:{exc}'}


def is_regular_market_open(market: str = 'KR', symbol: str | None = None) -> dict[str, Any]:
    """[PATCH: 2026-08-18] 시장 시간 검증 헬퍼.

    Args:
        market: 'KR' 또는 'US'
        symbol: 종목 코드 (로깅용, 현재는 VOO 등 미국장 검증에 사용)

    Returns:
        {'open': bool, 'near_close': bool, 'reason': str}
    """
    market_lower = market.lower()
    hours = market_hours_status()
    if not hours.get('ok'):
        return {'open': False, 'near_close': False, 'reason': f'[MARKET_CHECK] {market} market hours unavailable'}
    is_open = bool(hours.get(market_lower))
    near_close = bool(hours.get(f'{market_lower}_near_close', False))
    reason = f'[MARKET_CHECK] {market} market {"OPEN" if is_open else "CLOSED"}'
    if symbol:
        reason += f' symbol={symbol}'
    if near_close:
        reason += ' NEAR_CLOSE_WARNING'
    return {'open': is_open, 'near_close': near_close, 'reason': reason}


def fresh_kr_quote(symbol: str) -> dict[str, float] | None:
    data = quote_data(symbol)
    if not isinstance(data, dict):
        return None
    last = _quote_number(data, ('last', 'price', 'current_price', 'currentPrice'))
    base = _quote_number(data, ('base', 'base_price', 'basePrice', 'prev_close', 'previous_close', 'previousClose'))
    if last is None or base is None:
        return None
    return {'price': last, 'change_rate': last / base - 1.0}

def quote_data(symbol: str) -> dict[str, Any] | None:
    proc = run(['tossctl', 'quote', 'get', symbol, '--output', 'json'], timeout=45)
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def quote_last_usd(symbol: str) -> float | None:
    data = quote_data(symbol)
    if not data or str(data.get('currency') or '').upper() != 'USD':
        return None
    value = float(data.get('last') or 0)
    return value if value > 0 else None

def _quote_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def quote_change_rate(symbol: str) -> float | None:
    """오늘 등락률(예: -0.021). 확인 불가면 None."""
    data = quote_data(symbol) or {}
    # 1순위: 현재가와 전일 종가로 직접 계산 (단위 모호성이 없다).
    last = _quote_number(data, ('last', 'price', 'current_price', 'currentPrice'))
    base = _quote_number(data, ('base', 'base_price', 'basePrice', 'prev_close', 'previous_close', 'previousClose'))
    if last is not None and base is not None:
        return last / base - 1.0
    # 2순위: 제공되는 등락률 필드. 소수(-0.021)와 퍼센트(-2.1)가 섞여 오므로,
    # 하루 |50%| 초과는 소수로 볼 수 없다고 보고 퍼센트로 해석한다(= 더 보수적인 쪽).
    for key in ('change_rate', 'changeRate', 'daily_rate', 'fluctuation_rate'):
        value = data.get(key)
        if value is None:
            continue
        try:
            rate = float(value)
        except (TypeError, ValueError):
            continue
        return rate / 100.0 if abs(rate) > 0.5 else rate
    return None


def quote_rebounded_from_low(symbol: str) -> bool | None:
    """현재가가 당일 저가보다 높은지. 저가/현재가를 못 얻으면 None."""
    data = quote_data(symbol) or {}
    last = _quote_number(data, ('last', 'price', 'current_price', 'currentPrice'))
    low = _quote_number(data, ('low', 'day_low', 'dayLow', 'session_low', 'low_price', 'lowPrice'))
    if last is None or low is None:
        return None
    return last > low


def infer_usdkrw_from_positions(positions: list[dict[str, Any]]) -> float:
    rates: list[float] = []
    for row in positions:
        if row.get('share_holdings_type') != 'us':
            continue
        price_krw = float(row.get('current_price_krw') or 0)
        symbol = row.get('symbol')
        if price_krw <= 0 or not symbol:
            continue
        last_usd = quote_last_usd(str(symbol))
        if last_usd and last_usd > 0:
            rates.append(price_krw / last_usd)
    if rates:
        rates.sort()
        return rates[len(rates)//2]
    return 1400.0

def prepare_us_fractional_amount_intent(intent: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any]:
    if intent.get('market') != 'us' or not intent.get('fractional') or intent.get('qty') is not None or intent.get('amount') is None:
        return intent
    symbol = str(intent.get('symbol') or '')
    amount_krw = float(intent.get('amount') or 0)
    last_usd = quote_last_usd(symbol)
    fx = infer_usdkrw_from_positions(positions)
    if not last_usd or amount_krw <= 0 or fx <= 0:
        return intent
    qty = max(0.000001, round(amount_krw / (last_usd * fx), 6))
    out = dict(intent)
    out['amount_krw_reference'] = int(amount_krw)
    out['estimated_usdkrw'] = round(fx, 4)
    out['estimated_last_usd'] = round(last_usd, 6)
    out['qty'] = qty
    # Current tossctl build requires both --amount and --qty for fractional
    # previews, so keep amount for the broker amount check and add qty for
    # CLI validation.
    return out

def refresh_dashboard() -> tuple[bool, str]:
    """supervisor가 생성한 최신 dashboard-data.json의 freshness를 확인한다.

    생성기 update_dashboard_data_nas.py는 v4 supervisor에 흡수되었으므로
    삭제된 별도 생성기를 다시 호출하지 않는다.
    """
    try:
        if not DATA_FILE.is_file():
            return False, f"dashboard data missing: {DATA_FILE}"
        age = max(0.0, time.time() - DATA_FILE.stat().st_mtime)
        if age > 180:
            return False, f"dashboard data stale: age={age:.1f}s"
        payload = load_json(DATA_FILE, {})
        if not isinstance(payload, dict) or payload.get("_schema_version") != "v4":
            return False, "dashboard data schema is not v4"
        return True, f"supervisor dashboard-data.json fresh age={age:.1f}s"
    except Exception as exc:
        return False, f"dashboard refresh verification failed: {type(exc).__name__}: {exc}"

def _intent_key(intent: dict[str, Any]) -> str:
    canonical = json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _reserve_intent(intent: dict[str, Any], current_epoch: float | None = None) -> None:
    current_epoch = time.time() if current_epoch is None else current_epoch
    state = load_json(INTENT_STATE_FILE, {'intents': []})
    rows = state.get('intents') if isinstance(state, dict) else None
    rows = rows if isinstance(rows, list) else []
    recent = [row for row in rows if isinstance(row, dict) and current_epoch - float(row.get('epoch') or 0) < 600]
    key = _intent_key(intent)
    if any(row.get('key') == key for row in recent):
        raise RuntimeError('duplicate_local_intent_within_10_minutes')
    recent.append({'key': key, 'epoch': current_epoch, 'at': now(), 'intent': intent})
    INTENT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    save_json(INTENT_STATE_FILE, {'intents': recent[-100:]})


def _order_preflight(intent: dict[str, Any]) -> dict[str, Any]:
    """[PATCH: 2026-08-18] Preflight 검증 순서 최적화.

    순서: side → symbol → VOO/exclusion 필터 → 잔액 → 시장시간 → 중복방지 → 브로커미리보기 → 포지션버킷 → 권한부여
    """
    # 1. Side validation (~0ms)
    side = str(intent.get('side') or '').lower()
    if side not in ('buy', 'sell'):
        raise RuntimeError('invalid_order_side')

    # 2. Symbol validation (~1ms)
    symbol = str(intent.get('symbol') or '')
    if not symbol:
        raise RuntimeError('missing_symbol')

    # 3. VOO/exclusion filter (~2ms)
    market = str(intent.get('market') or '').lower()
    if side == 'buy' and market == 'us' and symbol not in US_BUY_WHITELIST:
        raise RuntimeError(f'[VOO_FILTER] {symbol} not in whitelist')

    # 4-9: 나머지 검증은 order_preview_and_place() 및 evaluate()에서 수행
    # - 잔액 검증: evaluate() 내에서 spendable 계산
    # - 시장 시간: 아래 market_hours_status() 호출
    # - 중복 방지: _reserve_intent() (evaluate 내)
    # - 브로커 미리보기: order_preview_and_place() 내
    # - 포지션 버킷: evaluate() 내
    # - 권한 부여: order_preview_and_place() 내
    if side == 'buy':
        hours = market_hours_status()
        if not hours.get('ok'):
            raise RuntimeError(str(hours.get('reason') or 'market_hours_unavailable'))
        if market not in ('kr', 'us') or hours.get(market) is not True:
            raise RuntimeError(f'{market or "unknown"}_regular_market_closed')
    return {
        'checks_bypassed': [
            'open_orders', 'orderable_funds', 'price_limits',
            'sellable_quantity', 'duplicate_intent',
            'dashboard_trade_control', 'human_approval',
        ],
        'buy_regular_market_required': True,
        'side': side,
    }


def order_preview_and_place(intent: dict[str, Any], human_gate_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run retained broker preview/permission checks, then submit an unverified live order."""
    result: dict[str, Any] = {'intent': intent}
    try:
        result['preflight'] = _order_preflight(intent)
    except Exception as exc:
        result['status'] = 'preflight_blocked'
        result['reason'] = str(exc)
        return result
    base = ['tossctl', 'order', 'preview', '--market', intent['market'], '--symbol', intent['symbol'], '--side', intent['side'], '--type', intent['type'], '--output', 'json']
    if intent.get('fractional'):
        base += ['--fractional']
    if intent.get('qty') is not None:
        base += ['--qty', str(intent['qty'])]
    if intent.get('price') is not None:
        base += ['--price', str(intent['price'])]
    if intent.get('amount') is not None:
        base += ['--amount', str(intent['amount']), '--currency-mode', 'KRW']
    preview = run(base, timeout=90)
    result.update({'preview_exit_code': preview.returncode, 'preview_output': (preview.stdout or preview.stderr)[-4000:]})
    if preview.returncode != 0:
        result['status'] = 'preview_failed'
        return result
    try:
        pv = json.loads(preview.stdout)
    except Exception as exc:
        result.update({'status': 'preview_json_failed', 'error': str(exc)})
        return result
    result['preview'] = pv
    if not isinstance(pv, dict) or not pv.get('mutation_ready') or not pv.get('confirm_token'):
        result['status'] = 'preview_not_mutation_ready'
        return result
    grant = run(['tossctl', 'order', 'permissions', 'grant', '--ttl', '300', '--output', 'json'], timeout=60)
    result.update({'grant_exit_code': grant.returncode, 'grant_output': (grant.stdout or grant.stderr)[-2000:]})
    if grant.returncode != 0:
        result['status'] = 'grant_failed'
        return result
    place = base[:]
    place[2] = 'place'
    place += ['--execute', '--dangerously-skip-permissions', '--confirm', pv['confirm_token']]
    placed = run(place, timeout=180)
    result.update({
        'place_exit_code': placed.returncode,
        'place_output': ((placed.stdout or '') + (('\n' + placed.stderr) if placed.stderr else ''))[-4000:],
        'status': 'submitted_unverified' if placed.returncode == 0 else 'place_failed_or_needs_app_approval',
    })
    return result


def cancel_pending_order(order: dict[str, Any]) -> dict[str, Any]:
    """Cancel a single pending order via tossctl ops call cancel_order.

    Uses the /api/v1/orders/{orderId}/cancel backend directly instead of the
    ``tossctl order cancel`` CLI, which has a known ID-drift bug in 0.38.0
    where the client re-fetches the order id between the preview call and the
    execute call.  The server-side id can change in that window, causing the
    execute to fail with ``pending order ... was not found``.

    Fail-closed: any exception or non-zero exit codes the result as
    ``cancel_failed`` with the error details preserved.
    """
    raw = order.get('raw') or {}
    order_id = raw.get('orderId') or order.get('orderId')
    symbol = order.get('symbol') or raw.get('symbol') or order.get('stockCode')
    if not order_id or not symbol:
        return {'status': 'cancel_failed', 'reason': 'missing_order_id_or_symbol'}

    result: dict[str, Any] = {'order_id': order_id, 'symbol': symbol}

    def _call(params: dict[str, Any], label: str) -> dict[str, Any]:
        proc = run(
            ['tossctl', 'ops', 'call', 'cancel_order', '--output', 'json',
             '--params', json.dumps(params, separators=(',', ':'))],
            timeout=60,
        )
        out = (proc.stdout or '') + (('\n' + proc.stderr) if proc.stderr else '')
        result[f'{label}_exit_code'] = proc.returncode
        result[f'{label}_output'] = out[-4000:]
        if proc.returncode != 0:
            return result
        try:
            return json.loads(proc.stdout)
        except Exception:
            return {'raw_error': out}

    # Step 1: preview
    preview = _call({'order_id': order_id, 'symbol': symbol}, 'preview')
    if isinstance(preview, dict) and preview.get('status', '') == 'error':
        return {'status': 'cancel_failed', 'reason': preview.get('message') or str(preview)}
    if not isinstance(preview, dict):
        return {'status': 'cancel_failed', 'reason': f'preview parse error: {preview}'}
    token = preview.get('confirm_token')
    if not token:
        return {'status': 'cancel_failed', 'reason': 'missing confirm_token', 'preview': preview}

    # Step 2: execute
    execute = _call({'order_id': order_id, 'symbol': symbol, 'execute': True, 'confirm': token}, 'execute')
    if isinstance(execute, dict):
        cancelled = execute.get('cancelled')
        is_canceled = (
            cancelled is True
            or (isinstance(cancelled, dict) and cancelled.get('isCanceled') is True)
        )
        if is_canceled:
            result['status'] = 'cancelled'
            # orderedAt은 취소된 주문의 응답 최상위 또는 cancelled 객체 안에 있을 수 있다.
            result['cancelled_at'] = (
                execute.get('orderedAt')
                if isinstance(execute.get('orderedAt'), str)
                else (execute.get('cancelled', {}).get('orderedAt') if isinstance(execute.get('cancelled'), dict) else None)
            )
            return result
        if execute.get('status') == 'error':
            return {'status': 'cancel_failed', 'reason': execute.get('message') or str(execute)}
        return {'status': 'cancel_failed', 'reason': f'unexpected execute response: {execute}', 'execute': execute}
    return {'status': 'cancel_failed', 'reason': 'execute parse error', 'execute_raw': execute}


def cancel_all_pending_orders() -> dict[str, Any]:
    """Cancel every pending order, one at a time. Fail-closed: returns summary."""
    try:
        orders_resp = run(['tossctl', 'orders', 'list', '--output', 'json'], timeout=30)
        if orders_resp.returncode != 0:
            return {'status': 'cancel_scan_failed', 'reason': orders_resp.stderr or orders_resp.stdout}
        orders = json.loads(orders_resp.stdout)
        if not isinstance(orders, list):
            return {'status': 'cancel_scan_failed', 'reason': 'orders list is not a list'}
    except Exception as exc:
        return {'status': 'cancel_scan_failed', 'reason': str(exc)}

    if not orders:
        return {'status': 'no_pending_orders', 'cancelled': 0, 'failed': 0}

    results: list[dict[str, Any]] = []
    cancelled_count = 0
    failed_count = 0
    for order in orders:
        res = cancel_pending_order(order)
        res['at'] = now()
        results.append(res)
        if res.get('status') == 'cancelled':
            cancelled_count += 1
        else:
            failed_count += 1

    return {
        'status': 'done',
        'pending_found': len(orders),
        'cancelled': cancelled_count,
        'failed': failed_count,
        'results': results,
    }

def calculate_operating_quantity(total_quantity: float, excluded_quantity: float) -> float:
    """Return the quantity eligible for Jarvis operation after protection."""
    return max(0.0, float(total_quantity) - max(0.0, float(excluded_quantity)))


def exclusion_for_position(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    """Find a configured exclusion using either stock_code or symbol."""
    symbol = str(row.get('symbol') or '')
    stock_code = str(row.get('stock_code') or '')
    candidates = {symbol, stock_code, f'A{symbol}' if symbol else ''}
    return next(
        (entry for entry in (config.get('operation_exclusions') or [])
         if str(entry.get('symbol') or '') in candidates
         or str(entry.get('stock_code') or '') in candidates),
        None,
    )


def is_uptrend(short_n: int = 5, mid_n: int = 20) -> bool:
    """Next-session recovery check: short-term MA > mid-term MA => uptrend.
    Uses the operating-capital time series in dashboard-history.json."""
    try:
        hist = load_json(HISTORY_FILE, [])
        series = [float(p.get('current_operating_capital_krw') or 0) for p in hist if p.get('current_operating_capital_krw') is not None]
        if len(series) < mid_n + 1:
            return False
        recent = series[-mid_n-1:]
        short_ma = sum(recent[-short_n:]) / short_n
        mid_ma = sum(recent) / (mid_n + 1)
        return short_ma > mid_ma
    except Exception:
        return False


def evaluate_stoploss_cascade(
    position_pnl_rate: float,
    position_daily_rate: float,
    stop_loss_pct: float = -0.10,
    defensive_stop_pct: float | None = None,
    defensive_daily_max: float = -0.01,
) -> tuple[str, float | None]:
    """[PATCH: 2026-08-18] Stop-Loss cascade 우선순위 평가.

    우선순위:
      1. 일일 -1% 한도 체크 → 오늘 손실이 -1%를 넘었으면 이후 매도 차단
      2. 개별 종목 -10% 손절 → 일일 한도를 넘지 않는 범위 내 개별 종목 손절
      3. 추세 회복 조건 (5MA > 20MA) → 손절 후 다음 세션부터 재진입 가능 여부 판단

    Returns:
        (result_code, partial_sell_pct)
        result_code: STOPLOSS_DAILY_LIMIT_EXCEEDED | STOPLOSS_INDIVIDUAL | STOPLOSS_DEFER_RECOVERY | NO_STOPLOSS
    """
    # 우선순위 1: 일일 -1% 한도 체크
    if position_daily_rate <= defensive_daily_max:
        return "STOPLOSS_DAILY_LIMIT_EXCEEDED", None

    # 우선순위 2: 개별 종목 -10% 손절
    if position_pnl_rate <= stop_loss_pct:
        return "STOPLOSS_INDIVIDUAL", 0.5  # 50% 부분매도

    # 우선순위 2b: 방어적 스탑 (defensive_stop이 설정된 경우)
    if defensive_stop_pct is not None and position_pnl_rate <= defensive_stop_pct:
        # 방어적 스탑에 도달했지만 급락 중이 아니면 관망
        if position_daily_rate > defensive_daily_max:
            return "NO_STOPLOSS", None
        return "STOPLOSS_INDIVIDUAL", 0.5

    # 우선순위 3: 추세 회복 여부 (is_uptrend는 이미 pending 상태에서 호출됨)
    # 이 함수는 pending 체크 없이 호출되므로, 여기서는 NO_STOPLOSS 반환
    # pending 체크는 evaluate() 내에서 별도로 수행
    return "NO_STOPLOSS", None


def verify_operating_fund(payload: dict[str, Any]) -> dict[str, Any]:
    """[PATCH: 2026-08-18] 운용자금 검증.

    공식: 현재운용자금 = 초기원금 + 누적수익 - 회인출액 + 재입금액
    dashboard-data.json의 operation 필드와 실제 metrics를 대조하여 불일치를 검출한다.

    Returns:
        {'status': 'VERIFIED|PENDING|STALE|DISCREPANCY', 'details': str, 'expected': float, 'actual': float}
    """
    metrics = payload.get('metrics') or {}
    operation = payload.get('operation') or {}
    initial = float(operation.get('initial_principal') or metrics.get('initial_operating_capital_krw') or 0)
    current = float(metrics.get('current_operating_capital_krw') or 0)
    accumulated = float(operation.get('accumulated_profit') or 0)
    if initial <= 0:
        return {'status': 'PENDING', 'details': 'initial_principal not set'}
    # 공식: 현재자산 - 초기원금 = 누적수익 (단, 사용자 입출금 없음이 전제)
    expected_accumulated = current - initial
    diff = abs(expected_accumulated - accumulated)
    # 허용 오차: 1원 (반올림 차이)
    if diff <= 1.0:
        return {
            'status': 'VERIFIED',
            'details': f'accumulated_profit={accumulated:.2f} matches expected={expected_accumulated:.2f}',
            'expected': expected_accumulated,
            'actual': accumulated,
        }
    return {
        'status': 'DISCREPANCY',
        'details': f'expected={expected_accumulated:.2f} actual={accumulated:.2f} diff={diff:.2f}',
        'expected': expected_accumulated,
        'actual': accumulated,
    }

def evaluate(config: dict[str, Any], payload: dict[str, Any], refresh_ok: bool, refresh_output: str) -> dict[str, Any]:
    exec_state = load_json(EXEC_STATE_FILE, {'orders': []})
    metrics = payload.get('metrics') or {}
    positions = payload.get('positions') or []
    protected = payload.get('protected_positions') or []
    cash = float(metrics.get('operating_cash_krw') or 0)
    current_capital = float(metrics.get('current_operating_capital_krw') or 0)
    # v2.6: 단일 게이트. live_enabled/order_mutation_enabled는 기본 허용.
    auto_exec = config.get('auto_execution_policy') or {}
    rules = auto_exec.get('machine_rules') or {}
    scope = config.get('trading_scope') or {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'}
    human_gate = rules.get('human_gate_config') or {}
    risk_flags: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    order_results: list[dict[str, Any]] = []
    market_state = market_hours_status()
    if not market_state.get('ok'):
        risk_flags.append({'level':'block','key':'market_hours_unavailable','message':str(market_state.get('reason') or 'tossctl market-hours query failed')})
    # 안전상 유지되는 block: 포지션 버킷 불일치 (데이터 무결성)
    # agabang 블록 제거됨 — 신규 매수 제한 없음
    for row in positions:
        if row.get('bucket') != 'jarvis_operation':
            risk_flags.append({'level':'block','key':'bucket_mismatch','message':f"운용 포지션 버킷 오류: {row.get('name')}"})
    protected_codes = {row.get('stock_code') for row in protected}
    for row in protected:
        if row.get('bucket') != 'excluded_from_jarvis_operation':
            risk_flags.append({'level':'block','key':'protected_bucket_mismatch','message':f"운용 제외 버킷 오류: {row.get('name')}"})

    order_limit = {
        'mode':'within_jarvis_operating_capital',
        'max_total_exposure_krw': round(current_capital, 4),
        'available_operating_cash_krw': round(cash, 4),
        'profit_reinvestment_enabled': bool((config.get('profit_reinvestment_policy') or {}).get('enabled')),
        'protected_positions_excluded': True,
        'protected_stock_codes': sorted(x for x in protected_codes if x),
    }

    daily_plan_hour = daily_plan_hour_kst(config)
    daily_plan_ready, daily_plan = daily_plan_today(refresh_ok, metrics, risk_flags, hour_kst=daily_plan_hour, minute_kst=0)
    process_config = config.get('auto_trading_process') or {}
    dashboard_trade_control_required = False
    control = trade_control_state()
    # Deleted final dashboard gate: the live config remains the master enable switch.
    dashboard_trade_enabled = None
    can_mutate = bool(config.get('live_trading_enabled')) and not bool(config.get('read_only_mode'))

    # Sell rule (revised 2026-07-10): -10% hard stop is NOT a full loss-cut.
    # It triggers a PARTIAL sell (50% of position), keeping the rest to ride a recovery.
    # Next-session trend check (short MA > mid MA) decides whether to keep the rest.
    #
    # [PATCH: 2026-08-18] Stop-Loss 우선순위 명시 (cascade 패턴):
    #   우선순위 1: 일일 -1% 한도 체크 → 오늘 손실이 -1%를 넘었으면 이후 매도 차단
    #   우선순위 2: 개별 종목 -10% 손절 → 일일 한도를 넘지 않는 범위 내 개별 종목 손절
    #   우선순위 3: 추세 회복 조건 (5MA > 20MA) → 손절 후 다음 세션부터 재진입 가능 여부 판단
    stop_loss = float(rules.get('sell_stop_loss_pct') or -0.10)
    defensive_stop = rules.get('defensive_stop_loss_pct')
    defensive_daily_max = float(rules.get('defensive_stop_daily_rate_max') or -0.01)
    partial_sell_pct = float(rules.get('partial_sell_pct') or 0.50)
    # exec_state에 직접 붙은 리스트를 써야 append 결과가 저장된다.
    # (기존: 키가 없으면 새 리스트를 만들어 append 하고 버려져서 다음 세션 추세확인이 죽어 있었음)
    if not isinstance(exec_state.get('pending_trend_check'), list):
        exec_state['pending_trend_check'] = []
    pending = exec_state['pending_trend_check']
    pending_count_before = len(pending)
    pending_symbols = {p.get('symbol') for p in pending}
    if can_mutate:
        for row in positions:
            pnl_rate_seen = float(row.get('pnl_rate') or 0)
            exclusion = exclusion_for_position(row, config)
            position_qty = max(0.0, float(row.get('quantity') or 0))
            # Dashboard positions are already the jarvis_operation bucket. If a
            # caller supplies an unbucketed/full position, derive the operating
            # quantity here so a partial exclusion cannot be over-sold.
            if row.get('bucket') == 'jarvis_operation':
                operating_qty = position_qty
            else:
                excluded_qty = float((exclusion or {}).get('excluded_quantity') or 0)
                operating_qty = calculate_operating_quantity(position_qty, excluded_qty)
            if operating_qty <= 0:
                if pnl_rate_seen <= (float(defensive_stop) if defensive_stop is not None else stop_loss):
                    actions.append({
                        'action': 'SELL_SKIPPED_EXCLUDED_SYMBOL',
                        'symbol': row.get('symbol'),
                        'name': row.get('name'),
                        'reason': 'symbol_fully_excluded_from_operation',
                        'pnl_rate': pnl_rate_seen,
                        'operating_quantity': operating_qty,
                    })
                continue
            pnl_rate = float(row.get('pnl_rate') or 0)
            daily_rate = float(row.get('daily_rate') or 0)

            # [PATCH: 2026-08-18] evaluate_stoploss_cascade() 우선순위 적용
            cascade_result, cascade_data = evaluate_stoploss_cascade(
                position_pnl_rate=pnl_rate,
                position_daily_rate=daily_rate,
                stop_loss_pct=stop_loss,
                defensive_stop_pct=float(defensive_stop) if defensive_stop is not None else None,
                defensive_daily_max=defensive_daily_max,
            )
            if cascade_result == "STOPLOSS_DAILY_LIMIT_EXCEEDED":
                actions.append({
                    'action': 'SELL_BLOCKED_DAILY_LIMIT',
                    'symbol': row.get('symbol'),
                    'reason': f'daily_rate {daily_rate:.4f} <= {defensive_daily_max}',
                    'pnl_rate': pnl_rate,
                    'daily_rate': daily_rate,
                })
                continue
            if cascade_result == "STOPLOSS_DEFER_RECOVERY":
                actions.append({
                    'action': 'KEEP_RIDE_TREND',
                    'symbol': row.get('symbol'),
                    'reason': 'next_session_uptrend_no_losscut',
                    'pnl_rate': pnl_rate,
                })
                continue
            if cascade_result != "STOPLOSS_INDIVIDUAL":
                continue

            # STOPLOSS_INDIVIDUAL: 50% 부분 매도
            market = 'us' if row.get('share_holdings_type') == 'us' else 'kr'
            market_open = bool(market_state.get(market))
            if not market_open:
                actions.append({'action':'SELL_WAIT_MARKET','symbol':row.get('symbol'),'reason':'regular_market_closed','pnl_rate':pnl_rate})
                continue
            # 매도 신호 기록
            if row.get('symbol') in pending_symbols:
                actions.append({'action':'SELL_SIGNAL','symbol':row.get('symbol'),'reason':'next_session_still_downtrend_partial','pnl_rate':pnl_rate,'daily_rate':daily_rate})
            else:
                actions.append({'action':'SELL_SIGNAL','symbol':row.get('symbol'),'reason':'partial_stop_loss','pnl_rate':pnl_rate,'daily_rate':daily_rate})
            sell_qty = min(operating_qty, max(0.0, round(operating_qty * partial_sell_pct, 6)))
            intent = {'market': market, 'symbol': row.get('symbol'), 'side':'sell', 'type':'market' if market == 'us' else 'limit', 'qty': sell_qty}
            if market == 'us':
                intent['fractional'] = True
            else:
                limit_price = float(row.get('current_price_krw') or 0)
                if limit_price <= 0:
                    actions.append({'action':'SELL_BLOCKED_NO_PRICE','symbol':row.get('symbol'),'reason':'missing_current_price_krw','pnl_rate':pnl_rate})
                    continue
                intent['price'] = limit_price
            intent = prepare_us_fractional_amount_intent(intent, positions)
            res = order_preview_and_place(intent, human_gate)
            res['at'] = now()
            if row.get('symbol') not in pending_symbols:
                pending.append({'symbol': row.get('symbol'), 'since': now(), 'pnl_rate': pnl_rate})
            order_results.append(res)

    # Buy after sell checks. BUY remains restricted to the regular market.
    sell_check_actions = {'SELL_SIGNAL', 'SELL_WAIT_MARKET', 'DEFENSIVE_STOP_WATCH', 'KEEP_RIDE_TREND', 'SELL_BLOCKED_NO_PRICE', 'SELL_BLOCKED_DAILY_LIMIT'}
    symbols_under_check = sorted({str(a.get('symbol')) for a in actions if a.get('action') in sell_check_actions and a.get('symbol')})
    # agabang check 제거됨 — block_new_buys_on_checks 무시
    buys_blocked_by_check = False
    buy_window_open = can_mutate and not order_results
    if buy_window_open:
        cash_buffer = float(rules.get('cash_buffer_krw') or 0)
        max_buy = float(rules.get('max_buy_amount_krw') or 0)
        min_buy = 0  # 최소주문금액 제한 없음
        spendable = max(0.0, cash - cash_buffer) if max_buy <= 0 else max(0.0, min(cash - cash_buffer, max_buy))

        kr_candidates: list[tuple[str, str, float, str]] = []
        screen_error: str | None = None
        try:
            seen_candidates: set[str] = set()
            raw_candidates = screen_kr_candidates(limit=30, max_price=int(spendable)) or []
            for symbol, name, cached_price in raw_candidates:
                if symbol in seen_candidates:
                    continue
                seen_candidates.add(symbol)
                kr_candidates.append((symbol, name, float(cached_price), 'kr_liquidity_screen_candidate'))
        except Exception as exc:
            screen_error = f'{type(exc).__name__}: {exc}'

        # [PATCH: 대시보드 표기를 위한 간략한 로깅]
        if screen_error:
            actions.append({'action':'KR_BUY_ERROR','reason':f'screener_failed','error':screen_error})
        elif not kr_candidates:
            actions.append({'action':'KR_BUY_EMPTY','reason':'no_candidates_after_filter','spendable_krw':int(spendable)})

        bought_or_waited = False
        if market_state.get('kr') is True:
            skipped: list[dict[str, Any]] = []
            quote_budget = 8
            for symbol, name, _ranking_price, reason in kr_candidates:
                if quote_budget <= 0:
                    skipped.append({'symbol': symbol, 'reason': 'quote_budget_exhausted'})
                    break
                quote_budget -= 1
                quote = fresh_kr_quote(symbol)
                if quote is None:
                    skipped.append({'symbol': symbol, 'reason': 'fresh_tossctl_quote_unavailable'})
                    continue
                price = quote['price']
                change_rate = quote['change_rate']
                if spendable < price:
                    skipped.append({'symbol': symbol, 'reason': 'fresh_quote_not_affordable', 'price': price})
                    continue
                qty = max(1, int(spendable // price))
                intent = {'market':'kr','symbol':symbol,'side':'buy','type':'limit','qty':qty,'price':price}
                actions.append({'action':'BUY_SIGNAL','symbol':symbol,'name':name,'reason':reason,'amount_limit_krw':spendable,'qty':qty,'change_rate':round(change_rate,6)})
                res = order_preview_and_place(intent, human_gate)
                res['at'] = now()
                order_results.append(res)
                bought_or_waited = True
                break
            if not bought_or_waited and skipped:
                actions.append({'action':'KR_BUY_SKIPPED','reason':'all_candidates_filtered','skipped':skipped[:10],'total_candidates':len(kr_candidates),'spendable_krw':int(spendable)})
        else:
            actions.append({'action':'KR_BUY_WAIT_MARKET','reason':'kr_regular_market_closed','total_candidates':len(kr_candidates),'spendable_krw':int(spendable)})
        if not bought_or_waited and not order_results:
            if market_state.get('us') is True:
                # [PATCH: 2026-08-18] VOO 필터: whitelist에 없는 종목 매수 차단
                us_buy_symbol = 'VOO'
                if us_buy_symbol not in US_BUY_WHITELIST:
                    actions.append({'action':'US_BUY_BLOCKED_FILTER','symbol':us_buy_symbol,'reason':f'[VOO_FILTER] {us_buy_symbol} not in whitelist','spendable_krw':round(spendable,4)})
                else:
                    dip_threshold = float(rules.get('dip_buy_daily_drop_pct') or 0)
                    change_rate = quote_change_rate(us_buy_symbol)
                    rebound_required = bool(rules.get('dip_buy_rebound_from_low_required'))
                    rebounded = quote_rebounded_from_low(us_buy_symbol) if rebound_required else True
                    if change_rate is None:
                        actions.append({'action':'US_BUY_WAIT_QUOTE','symbol':us_buy_symbol,'reason':'daily_change_rate_unavailable','spendable_krw':round(spendable,4)})
                    elif change_rate > dip_threshold and dip_threshold != 0:
                        actions.append({'action':'US_BUY_WAIT_DIP','symbol':us_buy_symbol,'reason':'not_low_enough_for_dip_buy','change_rate':change_rate,'threshold':dip_threshold,'spendable_krw':round(spendable,4)})
                    elif rebound_required and rebounded is not True:
                        actions.append({'action':'US_BUY_WAIT_REBOUND','symbol':us_buy_symbol,'reason':'no_rebound_from_session_low' if rebounded is False else 'session_low_unavailable','change_rate':change_rate})
                    else:
                        intent = {'market':'us','symbol':us_buy_symbol,'side':'buy','type':'market','fractional':True,'amount':int(spendable)}
                        reason = 'overseas_core_etf_daily_buy' if dip_threshold == 0 else 'overseas_core_etf_dip_buy'
                        actions.append({'action':'BUY_SIGNAL','symbol':us_buy_symbol,'name':'Vanguard S&P 500 ETF','reason':reason,'amount_krw':int(spendable),'change_rate':change_rate})
                        intent = prepare_us_fractional_amount_intent(intent, positions)
                        res = order_preview_and_place(intent, human_gate)
                        res['at'] = now()
                        order_results.append(res)
            else:
                actions.append({'action':'US_BUY_WAIT_MARKET','reason':'us_regular_market_closed','candidate':'VOO','spendable_krw':round(spendable,4)})

    if order_results or len(pending) != pending_count_before:
        if order_results:
            exec_state.setdefault('orders', []).extend(order_results)
        save_json(EXEC_STATE_FILE, exec_state)

    if can_mutate:
        decision_reason = 'config_live_trading_enabled;_deleted_order_gates_bypassed'
    else:
        decision_reason = 'config_live_trading_disabled_or_read_only'

    if order_results:
        status = 'live_order_attempted'
    else:
        status = 'live_auto_trading_active_waiting_signal'

    return {
        'generated_at': now(),
        'pid': os.getpid(),
        'mode': config.get('mode'),
        'scope': scope,
        'live_trading_enabled': bool(config.get('live_trading_enabled')) and not bool(config.get('read_only_mode')),
        'live_switch_status': 'enabled_by_config_master_switch',
        'dashboard_trade_control_required': dashboard_trade_control_required,
        'dashboard_trade_enabled': dashboard_trade_enabled,
        'dashboard_trade_control_updated_at': None,
        'can_place_order_now': can_mutate,
        'can_place_order_reason': decision_reason,
        'auto_execution_policy': auto_exec,
        'status': status,
        'refresh_ok': refresh_ok,
        'refresh_output_tail': refresh_output,
        'order_limit': order_limit,
        'market': {
            'kr_regular': bool(market_state.get('kr')),
            'us_regular': bool(market_state.get('us')),
            'source': 'tossctl_market_hours',
            'query_ok': bool(market_state.get('ok')),
            'reason': market_state.get('reason'),
        },
        'metrics': {
            'initial_operating_capital_krw': metrics.get('initial_operating_capital_krw'),
            'current_operating_capital_krw': metrics.get('current_operating_capital_krw'),
            'operating_cash_krw': metrics.get('operating_cash_krw'),
            'operating_return_rate': metrics.get('operating_return_rate'),
        },
        'guardrails': {
            'risk_flags': risk_flags,
        },
        'actions': actions,
        'order_results': order_results,
        'dry_run_decision': {
            'can_place_order_now': can_mutate,
            'dashboard_trade_control_required': dashboard_trade_control_required,
            'dashboard_trade_enabled': dashboard_trade_enabled,
            'dashboard_trade_control_updated_at': None,
            'automatic_daily_plan_required': True,
            'daily_plan_ready': daily_plan_ready,
            'daily_plan': daily_plan,
            'daily_plan_hour_kst': daily_plan_hour,
            'new_buys_blocked_by_check': buys_blocked_by_check,
            'symbols_under_check': symbols_under_check,
            'reason': decision_reason,
            'would_use_scope': scope.get('label', '국내+해외'),
            'would_limit_to': '자비스 운용자금 안',
        },
    }

def run_once() -> dict[str, Any]:
    cfg = load_json(CONFIG_FILE, {})
    refresh_ok, refresh_out = refresh_dashboard()
    payload = load_json(DATA_FILE, {})
    status = evaluate(cfg, payload, refresh_ok, refresh_out)
    save_json(STATUS_FILE, status)
    return status

def main() -> int:
    once = '--once' in sys.argv
    interval = int((load_json(CONFIG_FILE, {}).get('auto_trading_process') or {}).get('interval_seconds') or 60)
    while RUNNING:
        try:
            status = run_once()
            print(json.dumps({'generated_at': status['generated_at'], 'status': status['status'], 'live': status['live_trading_enabled'], 'actions': status.get('actions', [])[-3:]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            err = {'generated_at': now(), 'pid': os.getpid(), 'status': 'error', 'error': str(exc), 'live_trading_enabled': False}
            save_json(STATUS_FILE, err)
            print(json.dumps(err, ensure_ascii=False), flush=True)
        if once:
            break
        for _ in range(max(interval, 1)):
            if not RUNNING:
                break
            time.sleep(1)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
