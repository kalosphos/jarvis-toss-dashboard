#!/usr/bin/env python3
"""통합 테스트: 5개 시나리오.

[PATCH: 2026-08-18] JSMD 매매제약 패치 루프 검증.
각 시나리오는 모킹을 사용하여 실제 주문 없이 로직만 검증한다.
"""
from __future__ import annotations

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# 프로젝트 루트 추가
sys.path.insert(0, '/Volumes/web/toss')
os.chdir('/Volumes/web/toss')

KST = timezone(timedelta(hours=9))


def test_scenario_1_kr_buy_regular_market():
    """시나리오 1: 국내 매수 (정규장) - 정상 프로세스."""
    print("\n=== 시나리오 1: 국내 매수 (정규장) ===")

    # 모킹: 정규장 운영 중
    mock_market = {
        'ok': True, 'kr': True, 'us': False,
        'kr_date': '2026-08-18', 'kr_start_time': '09:00', 'kr_end_time': '15:30',
        'us_date': '2026-08-18', 'us_start_time': '23:00', 'us_end_time': '06:00',
    }

    # 모킹: 후보 주식
    mock_candidates = [
        ('005930', '삼성전자', 70000.0),
        ('000660', 'SK하이닉스', 150000.0),
    ]

    # 모킹: 호가
    mock_quote = {'price': 70000.0, 'change_rate': 0.02}

    with patch('auto_trading_manager.market_hours_status', return_value=mock_market), \
         patch('auto_trading_manager.screen_kr_candidates', return_value=mock_candidates), \
         patch('auto_trading_manager.fresh_kr_quote', return_value=mock_quote), \
         patch('auto_trading_manager.order_preview_and_place', return_value={'status': 'submitted_unverified'}):

        from auto_trading_manager import evaluate, load_json

        config = {
            'auto_execution_policy': {
                'machine_rules': {
                    'sell_stop_loss_pct': -0.10,
                    'defensive_stop_loss_pct': -0.10,
                    'defensive_stop_daily_rate_max': -0.01,
                    'partial_sell_pct': 0.50,
                    'cash_buffer_krw': 0,
                    'max_buy_amount_krw': 0,
                    'dip_buy_daily_drop_pct': 0,
                }
            },
            'trading_scope': {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'},
            'live_trading_enabled': True,
            'read_only_mode': False,
            'operation_exclusions': [],
            'profit_reinvestment_policy': {'enabled': True},
        }
        payload = {
            'metrics': {
                'operating_cash_krw': 1000000.0,
                'current_operating_capital_krw': 10000000.0,
                'initial_operating_capital_krw': 4842484.0,
            },
            'positions': [],
            'protected_positions': [],
        }

        result = evaluate(config, payload, True, 'refresh_ok')

        # 검증
        buy_signals = [a for a in result.get('actions', []) if a.get('action') == 'BUY_SIGNAL']
        assert len(buy_signals) >= 1, "BUY_SIGNAL이 하나 이상 있어야 함"
        assert buy_signals[0]['symbol'] == '005930', "첫 번째 후보인 삼성전자가 매수 신호여야 함"
        assert result['live_trading_enabled'] is True, "실거래가 활성화되어야 함"
        print(f"  ✅ 통과: {buy_signals[0]['symbol']} 매수 신호 발생 (qty={buy_signals[0].get('qty')})")


def test_scenario_2_us_buy_voo_dip():
    """시나리오 2: 미국 매수 (VOO, dip_buy) - VOO만 허용."""
    print("\n=== 시나리오 2: 미국 매수 (VOO, dip_buy) ===")

    mock_market = {
        'ok': True, 'kr': False, 'us': True,
        'kr_date': '2026-08-18', 'kr_start_time': '09:00', 'kr_end_time': '15:30',
        'us_date': '2026-08-18', 'us_start_time': '23:00', 'us_end_time': '06:00',
    }

    # VOO가 dip_buy 조건 충족
    mock_change_rate = -0.02  # -2% 하락
    mock_rebounded = True

    with patch('auto_trading_manager.market_hours_status', return_value=mock_market), \
         patch('auto_trading_manager.quote_change_rate', return_value=mock_change_rate), \
         patch('auto_trading_manager.quote_rebounded_from_low', return_value=mock_rebounded), \
         patch('auto_trading_manager.order_preview_and_place', return_value={'status': 'submitted_unverified'}), \
         patch('auto_trading_manager.prepare_us_fractional_amount_intent', side_effect=lambda x, y: x):

        from auto_trading_manager import evaluate

        config = {
            'auto_execution_policy': {
                'machine_rules': {
                    'sell_stop_loss_pct': -0.10,
                    'defensive_stop_loss_pct': -0.10,
                    'defensive_stop_daily_rate_max': -0.01,
                    'partial_sell_pct': 0.50,
                    'cash_buffer_krw': 0,
                    'max_buy_amount_krw': 0,
                    'dip_buy_daily_drop_pct': -0.01,  # -1% 이하 하락 시 매수
                    'dip_buy_rebound_from_low_required': True,
                }
            },
            'trading_scope': {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'},
            'live_trading_enabled': True,
            'read_only_mode': False,
            'operation_exclusions': [],
            'profit_reinvestment_policy': {'enabled': True},
        }
        payload = {
            'metrics': {
                'operating_cash_krw': 1000000.0,
                'current_operating_capital_krw': 10000000.0,
                'initial_operating_capital_krw': 4842484.0,
            },
            'positions': [],
            'protected_positions': [],
        }

        result = evaluate(config, payload, True, 'refresh_ok')

        buy_signals = [a for a in result.get('actions', []) if a.get('action') == 'BUY_SIGNAL']
        assert len(buy_signals) >= 1, "BUY_SIGNAL이 하나 이상 있어야 함"
        assert buy_signals[0]['symbol'] == 'VOO', "VOO만 매수 신호여야 함"
        print(f"  ✅ 통과: VOO 매수 신호 발생 (amount_krw={buy_signals[0].get('amount_krw')})")


def test_scenario_3_stop_loss_sell():
    """시나리오 3: 손절 매도 (-10%) - 50% 부분 매도."""
    print("\n=== 시나리오 3: 손절 매도 (-10%) ===")

    mock_market = {
        'ok': True, 'kr': True, 'us': False,
        'kr_date': '2026-08-18', 'kr_start_time': '09:00', 'kr_end_time': '15:30',
        'us_date': '2026-08-18', 'us_start_time': '23:00', 'us_end_time': '06:00',
    }

    # -15% 손실 포지션
    mock_positions = [{
        'symbol': '005930',
        'name': '삼성전자',
        'bucket': 'jarvis_operation',
        'quantity': 10.0,
        'pnl_rate': -0.15,  # -15% 손실
        'daily_rate': -0.005,  # 일일 -0.5% (방어 조건 미충족)
        'share_holdings_type': 'kr',
        'current_price_krw': 65000.0,
    }]

    with patch('auto_trading_manager.market_hours_status', return_value=mock_market), \
         patch('auto_trading_manager.order_preview_and_place', return_value={'status': 'submitted_unverified'}):

        from auto_trading_manager import evaluate

        config = {
            'auto_execution_policy': {
                'machine_rules': {
                    'sell_stop_loss_pct': -0.10,
                    'defensive_stop_loss_pct': -0.10,
                    'defensive_stop_daily_rate_max': -0.01,
                    'partial_sell_pct': 0.50,
                }
            },
            'trading_scope': {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'},
            'live_trading_enabled': True,
            'read_only_mode': False,
            'operation_exclusions': [],
            'profit_reinvestment_policy': {'enabled': True},
        }
        payload = {
            'metrics': {
                'operating_cash_krw': 1000000.0,
                'current_operating_capital_krw': 10000000.0,
                'initial_operating_capital_krw': 4842484.0,
            },
            'positions': mock_positions,
            'protected_positions': [],
        }

        result = evaluate(config, payload, True, 'refresh_ok')

        sell_signals = [a for a in result.get('actions', []) if a.get('action') == 'SELL_SIGNAL']
        assert len(sell_signals) >= 1, "SELL_SIGNAL이 하나 이상 있어야 함"
        assert sell_signals[0]['symbol'] == '005930', "삼성전자가 매도 신호여야 함"
        print(f"  ✅ 통과: {sell_signals[0]['symbol']} 매도 신호 발생 (reason={sell_signals[0].get('reason')})")


def test_scenario_4_defensive_daily_limit():
    """시나리오 4: 방어 매도 (일일 -1% 초과) - 매도 차단."""
    print("\n=== 시나리오 4: 방어 매도 (일일 -1% 초과) ===")

    mock_market = {
        'ok': True, 'kr': True, 'us': False,
        'kr_date': '2026-08-18', 'kr_start_time': '09:00', 'kr_end_time': '15:30',
        'us_date': '2026-08-18', 'us_start_time': '23:00', 'us_end_time': '06:00',
    }

    # 일일 -2% 하락 (방어 조건 충족), 개별 손실은 -5% (-10% 미달)
    mock_positions = [{
        'symbol': '005930',
        'name': '삼성전자',
        'bucket': 'jarvis_operation',
        'quantity': 10.0,
        'pnl_rate': -0.05,  # -5% 손실 (-10% 미달)
        'daily_rate': -0.02,  # 일일 -2% (방어 조건 충족: -1% 초과)
        'share_holdings_type': 'kr',
        'current_price_krw': 65000.0,
    }]

    with patch('auto_trading_manager.market_hours_status', return_value=mock_market), \
         patch('auto_trading_manager.order_preview_and_place', return_value={'status': 'submitted_unverified'}):

        from auto_trading_manager import evaluate

        config = {
            'auto_execution_policy': {
                'machine_rules': {
                    'sell_stop_loss_pct': -0.10,
                    'defensive_stop_loss_pct': -0.10,
                    'defensive_stop_daily_rate_max': -0.01,
                    'partial_sell_pct': 0.50,
                }
            },
            'trading_scope': {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'},
            'live_trading_enabled': True,
            'read_only_mode': False,
            'operation_exclusions': [],
            'profit_reinvestment_policy': {'enabled': True},
        }
        payload = {
            'metrics': {
                'operating_cash_krw': 1000000.0,
                'current_operating_capital_krw': 10000000.0,
                'initial_operating_capital_krw': 4842484.0,
            },
            'positions': mock_positions,
            'protected_positions': [],
        }

        result = evaluate(config, payload, True, 'refresh_ok')

        # 일일 -1% 초과 → STOPLOSS_DAILY_LIMIT_EXCEEDED → 매도 차단
        blocked = [a for a in result.get('actions', []) if a.get('action') == 'SELL_BLOCKED_DAILY_LIMIT']
        sell_signals = [a for a in result.get('actions', []) if a.get('action') == 'SELL_SIGNAL']
        assert len(blocked) >= 1, "SELL_BLOCKED_DAILY_LIMIT이 하나 이상 있어야 함"
        assert len(sell_signals) == 0, "SELL_SIGNAL이 없어야 함 (일일 한도로 차단)"
        print(f"  ✅ 통과: 일일 -1% 초과로 매도 차단됨 ({blocked[0].get('reason')})")


def test_scenario_5_rejection_cases():
    """시나리오 5: 거부 사항 (비정규장, QQQ 시도, 운용제외 종목)."""
    print("\n=== 시나리오 5: 거부 사항 ===")

    # 5a: 비정규장
    mock_market_closed = {
        'ok': True, 'kr': False, 'us': False,
        'kr_date': '2026-08-18', 'kr_start_time': '09:00', 'kr_end_time': '15:30',
        'us_date': '2026-08-18', 'us_start_time': '23:00', 'us_end_time': '06:00',
    }

    with patch('auto_trading_manager.market_hours_status', return_value=mock_market_closed), \
         patch('auto_trading_manager.screen_kr_candidates', return_value=[('005930', '삼성전자', 70000.0)]):
        from auto_trading_manager import evaluate
        config = {
            'auto_execution_policy': {'machine_rules': {'sell_stop_loss_pct': -0.10, 'defensive_stop_loss_pct': -0.10, 'defensive_stop_daily_rate_max': -0.01, 'partial_sell_pct': 0.50}},
            'trading_scope': {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'},
            'live_trading_enabled': True, 'read_only_mode': False,
            'operation_exclusions': [], 'profit_reinvestment_policy': {'enabled': True},
        }
        payload = {'metrics': {'operating_cash_krw': 1000000.0, 'current_operating_capital_krw': 10000000.0, 'initial_operating_capital_krw': 4842484.0}, 'positions': [], 'protected_positions': []}
        result = evaluate(config, payload, True, 'refresh_ok')
        wait_actions = [a for a in result.get('actions', []) if 'WAIT_MARKET' in a.get('action', '')]
        assert len(wait_actions) >= 1, "비정규장에서는 WAIT_MARKET 액션이 있어야 함"
        print(f"  ✅ 5a 통과: 비정규장 매수 대기 ({wait_actions[0].get('action')})")

    # 5b: QQQ 시도 (VOO whitelist에 없음)
    from auto_trading_manager import US_BUY_WHITELIST, _order_preflight
    assert 'QQQ' not in US_BUY_WHITELIST, "QQQ는 whitelist에 없어야 함"
    try:
        _order_preflight({'market': 'us', 'symbol': 'QQQ', 'side': 'buy'})
        assert False, "QQQ 매수는 차단되어야 함"
    except RuntimeError as e:
        assert '[VOO_FILTER]' in str(e), f"VOO 필터 에러여야 함: {e}"
        print(f"  ✅ 5b 통과: QQQ 매수 차단 ({e})")

    # 5c: 운용제외 종목 (KODEX 200)
    mock_market_open = {
        'ok': True, 'kr': True, 'us': False,
        'kr_date': '2026-08-18', 'kr_start_time': '09:00', 'kr_end_time': '15:30',
        'us_date': '2026-08-18', 'us_start_time': '23:00', 'us_end_time': '06:00',
    }
    # 대시보드에서 jarvis_operation 버킷에서 이미 제외됨 → 실제로 positions에 없어야 함
    # 만약 서버에서 아직 버킷팅되지 않은 원본 데이터인 경우를 시뮬레이션
    mock_positions_excluded = [{
        'symbol': '069500',
        'name': 'KODEX 200',
        'bucket': 'unassigned',  # 버킷 미배정 (원본 데이터)
        'quantity': 300.0,
        'pnl_rate': -0.15,
        'daily_rate': -0.005,
        'share_holdings_type': 'kr',
        'current_price_krw': 35000.0,
    }]
    config_exclusions = {
        'auto_execution_policy': {'machine_rules': {'sell_stop_loss_pct': -0.10, 'defensive_stop_loss_pct': -0.10, 'defensive_stop_daily_rate_max': -0.01, 'partial_sell_pct': 0.50}},
        'trading_scope': {'markets': ['KR_STOCK', 'US_STOCK'], 'label': '국내+해외'},
        'live_trading_enabled': True, 'read_only_mode': False,
        'operation_exclusions': [{'symbol': '069500', 'excluded_quantity': 300}],
        'profit_reinvestment_policy': {'enabled': True},
    }
    with patch('auto_trading_manager.market_hours_status', return_value=mock_market_open):
        result = evaluate(config_exclusions, {'metrics': {'operating_cash_krw': 1000000.0, 'current_operating_capital_krw': 10000000.0, 'initial_operating_capital_krw': 4842484.0}, 'positions': mock_positions_excluded, 'protected_positions': []}, True, 'refresh_ok')
        excluded = [a for a in result.get('actions', []) if 'EXCLUDED' in a.get('action', '')]
        assert len(excluded) >= 1, "운용제외 종목 액션이 있어야 함"
        print(f"  ✅ 5c 통과: 운용제외 종목 매도 차단 ({excluded[0].get('action')})")


def test_verify_operating_fund():
    """추가 테스트: verify_operating_fund() 함수."""
    print("\n=== 추가: verify_operating_fund() ===")
    from auto_trading_manager import verify_operating_fund

    # 정상 케이스
    payload = {
        'metrics': {
            'initial_operating_capital_krw': 4842484.0,
            'current_operating_capital_krw': 10685948.0,
        },
        'operation': {
            'initial_principal': 4842484.0,
            'accumulated_profit': 5843464.0,
        }
    }
    result = verify_operating_fund(payload)
    assert result['status'] == 'VERIFIED', f"VERIFIED여야 함: {result}"
    print(f"  ✅ 통과: 운용자금 검증 성공 ({result['details']})")

    # 불일치 케이스
    payload_bad = {
        'metrics': {
            'initial_operating_capital_krw': 4842484.0,
            'current_operating_capital_krw': 10685948.0,
        },
        'operation': {
            'initial_principal': 4842484.0,
            'accumulated_profit': 9999999.0,  # 의도적 불일치
        }
    }
    result_bad = verify_operating_fund(payload_bad)
    assert result_bad['status'] == 'DISCREPANCY', f"DISCREPANCY여야 함: {result_bad}"
    print(f"  ✅ 통과: 운용자금 불일치 검출 ({result_bad['details']})")


def test_evaluate_stoploss_cascade():
    """추가 테스트: evaluate_stoploss_cascade() 함수."""
    print("\n=== 추가: evaluate_stoploss_cascade() ===")
    from auto_trading_manager import evaluate_stoploss_cascade

    # 케이스 1: 일일 한도 초과
    result, data = evaluate_stoploss_cascade(position_pnl_rate=-0.05, position_daily_rate=-0.02)
    assert result == "STOPLOSS_DAILY_LIMIT_EXCEEDED", f"일일 한도 초과여야 함: {result}"
    print(f"  ✅ 통과: 일일 한도 초과 → {result}")

    # 케이스 2: 개별 손절
    result, data = evaluate_stoploss_cascade(position_pnl_rate=-0.15, position_daily_rate=-0.005)
    assert result == "STOPLOSS_INDIVIDUAL", f"개별 손절여야 함: {result}"
    assert data == 0.5, f"50% 부분매도여야 함: {data}"
    print(f"  ✅ 통과: 개별 손절 → {result}, partial_sell={data}")

    # 케이스 3: 손절 미달
    result, data = evaluate_stoploss_cascade(position_pnl_rate=-0.05, position_daily_rate=-0.005)
    assert result == "NO_STOPLOSS", f"손절 미달이어야 함: {result}"
    print(f"  ✅ 통과: 손절 미달 → {result}")


if __name__ == '__main__':
    print("=" * 60)
    print("JSMD 매매제약 패치 루프 - 통합 테스트")
    print("=" * 60)

    test_scenario_1_kr_buy_regular_market()
    test_scenario_2_us_buy_voo_dip()
    test_scenario_3_stop_loss_sell()
    test_scenario_4_defensive_daily_limit()
    test_scenario_5_rejection_cases()
    test_verify_operating_fund()
    test_evaluate_stoploss_cascade()

    print("\n" + "=" * 60)
    print("🎉 모든 테스트 통과!")
    print("=" * 60)
