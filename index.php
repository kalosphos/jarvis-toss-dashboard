<?php
declare(strict_types=1);

$GLOBALS['DASHBOARD_GATE_LIB'] = true;
require_once __DIR__ . '/toss-auth.php';

if (validateSessionCookie() === null) {
    header('Location: /toss/login.html', true, 302);
    exit;
}

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');

$dashboardCss = __DIR__ . '/dashboard.css';
$dashboardCssVersion = is_file($dashboardCss) ? (string) filemtime($dashboardCss) : '0';
?>
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="토스증권 자동매매 운영 상태, 자산, 브리핑 및 포지션 대시보드">
  <title>자비스 주식운용 대시보드</title>
  <link rel="stylesheet" href="/toss/dashboard.css?v=<?= rawurlencode($dashboardCssVersion) ?>">
</head>
<body>
  <main class="wrap" id="dashboard">
    <header class="head">
      <div class="head-title">
        <div class="title-row">
          <h1>자비스 주식운용 대시보드</h1>
          <span class="version-badge">v4.3</span>
        </div>
      </div>
      <div class="head-side">
        <div class="meta" aria-label="데이터 갱신 정보">
          <span><b>화면 갱신</b> <time id="screen-updated">-</time></span>
          <span><b>자료 기준</b> <time id="data-generated">-</time></span>
        </div>
        <div class="head-actions" aria-label="대시보드 작업">
          <button type="button" class="action-button" id="top-stocks-button">종목</button>
          <button type="button" class="action-button" id="refresh-button">새로고침</button>
          <button type="button" class="action-button" id="briefing-refresh-button">브리핑</button>
          <button type="button" class="action-button" id="reauth-button">재인증</button>
        </div>
      </div>
    </header>

    <div class="notice" id="notice" role="status" aria-live="polite">대시보드 데이터를 불러오는 중…</div>

    <section class="control-card is-pending" id="control-card" aria-labelledby="control-title" aria-live="polite">
      <div>
        <div class="control-title" id="control-title"><span class="state-dot" aria-hidden="true"></span>거래 권한</div>
        <div class="control-detail" id="control-detail">확인 중…</div>
        <div class="control-updated" id="control-updated"></div>
        <div class="control-error" id="control-error" hidden></div>
      </div>
      <button type="button" role="switch" aria-label="매매 허용" aria-checked="false" class="action-button trade-switch off" id="trade-switch" disabled>
        <span class="switch-track" aria-hidden="true"><span class="switch-knob"></span></span>
        <span id="trade-switch-label">OFF</span>
      </button>
    </section>

    <section class="badges" id="risk-badges" aria-label="차단 상태" hidden></section>

    <section class="card asset-overview" aria-labelledby="asset-overview-title">
      <div class="asset-overview-head">
        <div>
          <h2 id="asset-overview-title">총자산</h2>
          <div class="asset-total" id="asset-total">-</div>
        </div>
        <div class="asset-periods" aria-label="자산 추이 기간">
          <button type="button" class="period-tab is-selected" id="period-1d" aria-pressed="true">1일</button>
          <button type="button" class="period-tab" id="period-7d" aria-pressed="false">7일</button>
          <button type="button" class="period-tab" id="period-1m" aria-pressed="false">1개월</button>
          <button type="button" class="period-tab" id="period-all" aria-pressed="false">전체</button>
        </div>
      </div>
      <div class="asset-chart-container">
        <div class="asset-change-wrap">
          <div class="asset-change" id="asset-change"></div>
        </div>
        <div class="asset-chart-wrap">
          <svg class="asset-chart" id="asset-chart" role="img" aria-label="총자산 추이">
            <defs>
              <linearGradient id="chart-fill-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#ef4444" stop-opacity="0.25"></stop>
                <stop offset="100%" stop-color="#ef4444" stop-opacity="0"></stop>
              </linearGradient>
              <!-- 그래프 해치 패턴 (모든 그래프 통일, dashboard.css가 참조) -->
              <pattern id="chart-hatch-up" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="6" stroke="#ef4444" stroke-width="1" stroke-opacity="0.18"></line>
              </pattern>
              <pattern id="chart-hatch-down" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="6" stroke="#3b82f6" stroke-width="1" stroke-opacity="0.18"></line>
              </pattern>
            </defs>
          </svg>
          <div class="asset-chart-hover" id="asset-chart-hover" hidden>
            <div class="asset-chart-hover-value" id="asset-chart-hover-value"></div>
            <div class="asset-chart-hover-time" id="asset-chart-hover-time"></div>
          </div>
          <div class="asset-chart-xaxis" id="asset-chart-xaxis"></div>
        </div>
      <div class="empty" id="asset-chart-empty" hidden>자산 추이 데이터 부족</div>
      </div>
      <div class="asset-supporting-metrics">
        <div><span>평가손익</span><b id="profit-loss">-</b><small id="profit-loss-rate">-</small></div>
        <div><span>운용자금</span><b id="operating-capital">-</b><small id="initial-capital">-</small></div>
        <div><span>주문가능 현금</span><b id="buying-power">-</b></div>
        <div><span>실현+평가 합계</span><b id="total-pnl">-</b><small id="total-pnl-rate">-</small></div>
      </div>
    </section>

    <section class="card" id="risk-card" aria-labelledby="risk-title" hidden>
      <h2 id="risk-title">위험 가드레일</h2>
      <div id="risk-flags"></div>
    </section>

    <section class="card briefing-card" aria-labelledby="briefing-title">
      <div class="briefing-head">
        <div>
          <h2 id="briefing-title">09시 운용 브리핑</h2>
          <span class="briefing-tag">참고용 · 실거래와 무관</span>
        </div>
      </div>
      <div class="briefing-history">
        <h3>브리핑 이력</h3>
        <div class="briefing-history-list" id="briefing-history" role="list"></div>
        <div class="empty" id="briefing-history-empty">저장된 브리핑 없음</div>
      </div>
      <div class="briefing-body" id="briefing-body" hidden>
        <div class="briefing-meta-row">
          <span><b>기준일</b> <span id="briefing-date">-</span></span>
          <span><b>상태</b> <span id="briefing-status">-</span></span>
        </div>
        <p class="briefing-summary" id="briefing-summary"></p>
        <details class="briefing-details">
          <summary>근거·제안 보기</summary>
          <section class="briefing-detail-section">
            <h3>거시경제 / 정세</h3>
            <div id="briefing-macro"></div>
          </section>
          <section class="briefing-detail-section">
            <h3>뉴스 브리핑 (08시 수집)</h3>
            <div id="briefing-news"></div>
          </section>
          <section class="briefing-detail-section">
            <h3>리스크 플래그 / 레드팀</h3>
            <div id="briefing-red-team"></div>
          </section>
          <section class="briefing-detail-section">
            <h3>행동 라벨</h3>
            <div id="briefing-actions"></div>
          </section>
          <section class="briefing-detail-section">
            <h3>뉴스 브리핑</h3>
            <div id="briefing-news-positions" class="news-positions"></div>
            <div class="news-global-risks" id="briefing-news-global">
              <h4>글로벌 리스크</h4>
              <ul id="briefing-global-risks-list"></ul>
            </div>
            <div class="news-calendar" id="briefing-news-calendar">
              <h4>경제 캘린더 (이번 주)</h4>
              <ul id="briefing-calendar-list"></ul>
            </div>
          </section>
          <section class="briefing-detail-section">
            <h3>실거래 참고 제안</h3>
            <div class="briefing-proposals" id="briefing-proposals"></div>
          </section>
        </details>
      </div>
      <div class="empty" id="briefing-empty">오늘 브리핑 데이터 없음</div>
    </section>

    <section class="card" aria-labelledby="positions-title">
      <h2 id="positions-title">운용 포지션 (0)</h2>
      <div class="pos-table-scroll" id="positions-table-wrap" hidden>
        <table class="pos-table pos-table--operating">
          <thead><tr><th>종목</th><th>수량</th><th>투자원금(원)</th><th>평가손익</th><th>당일</th></tr></thead>
          <tbody id="positions-body"></tbody>
        </table>
      </div>
      <div class="empty" id="positions-empty">없음</div>
    </section>

    <section class="card" id="protected-card" aria-labelledby="protected-title" hidden>
      <h2 id="protected-title">운용 제외 (보호) (0)</h2>
      <div class="pos-table-scroll">
        <table class="pos-table pos-table--protected">
          <thead><tr><th>종목</th><th>수량</th><th>투자원금(원)</th><th>평가손익</th><th>당일</th></tr></thead>
          <tbody id="protected-body"></tbody>
        </table>
      </div>
    </section>

    <section class="card" id="actions-card" aria-labelledby="actions-title" hidden>
      <h2 id="actions-title">거래 기록</h2>
      <div class="action-list" id="actions-list"></div>
      <div class="empty" id="actions-empty">현재 거래 기록 없음</div>
    </section>

    <section class="card" id="quotes-card" aria-labelledby="quotes-title" hidden>
      <h2 id="quotes-title">실시간 시세 · 캔들</h2>
      <div class="quote-tabs" id="quote-tabs"></div>
      <div class="quote-grid">
        <div class="quote-panel">
          <div class="quote-head">
            <span id="quote-sym-name">—</span>
            <span id="quote-last" class="quote-last">—</span>
          </div>
          <div class="quote-canvas-wrap"><canvas id="candleChart"></canvas></div>
          <div class="quote-sub" id="quote-sub">분봉 3m · 일봉 1d</div>
        </div>
        <div class="quote-list" id="quote-list"></div>
      </div>
      <div class="quote-updated" id="quote-updated">시세 갱신 대기</div>
    </section>

    <footer class="foot">로그인된 대시보드의 매매 허용 토글은 controller trade control을 변경합니다. 다른 주문 안전 게이트는 독립적으로 적용됩니다.</footer>
  </main>

  <script>
  (() => {
    "use strict";

    const state = {
      data: null,
      briefingHistory: [],
      selectedBriefingAt: null,
      assetPeriod: "1d",
      control: null,
      controlBusy: false
    };
    const byId = (id) => document.getElementById(id);
    const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
    const asArray = (value) => Array.isArray(value) ? value : [];
    const finiteNumber = (value) => {
      if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    };
    const boundedText = (value, limit = 360) => {
      let output = "-";
      if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") output = String(value);
      if (output.length > limit) output = output.slice(0, limit) + "…";
      return output;
    };
    const describeValue = (value) => {
      if (isRecord(value)) {
        return Object.entries(value).slice(0, 8).map(([key, item]) => key + ": " + boundedText(item, 220)).join(" · ");
      }
      return boundedText(value, 360);
    };
    const formatKrw = (value) => {
      const number = finiteNumber(value);
      return number === null ? "-" : Math.round(number).toLocaleString("ko-KR");
    };
    const formatQty = (value) => {
      const number = finiteNumber(value);
      return number === null || number < 1 ? "-" : number.toLocaleString("ko-KR", { maximumFractionDigits: 6 });
    };
    const formatPct = (value) => {
      const number = finiteNumber(value);
      return number === null ? "-" : (number > 0 ? "+" : "") + (number * 100).toFixed(1) + "%";
    };
    const pnlClass = (value) => {
      const number = finiteNumber(value);
      return number === null ? "" : number > 0 ? "up" : number < 0 ? "down" : "";
    };
    const displayTime = (value) => typeof value === "string" ? value.slice(0, 19).replace("T", " ") : "-";
    const create = (tag, className, value) => {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (value !== undefined) element.textContent = value;
      return element;
    };
    const svgCreate = (tag, attributes = {}) => {
      const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
      return element;
    };
    const setText = (id, value) => { byId(id).textContent = String(value); };
    const setPnl = (id, value, text) => {
      const element = byId(id);
      element.classList.remove("up", "down");
      const className = pnlClass(value);
      if (className) element.classList.add(className);
      element.textContent = text;
    };
    const showNotice = (message, error = false) => {
      const notice = byId("notice");
      notice.textContent = message;
      notice.classList.toggle("error", error);
      notice.hidden = !message;
    };

    async function fetchJson(url, options = {}) {
      const response = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        ...options
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(isRecord(payload) && typeof payload.error === "string" ? payload.error : "HTTP " + response.status);
      }
      return response.json();
    }

    function riskFlags(data) {
      const autoStatus = isRecord(data.auto_trading_status) ? data.auto_trading_status : {};
      const guardrails = isRecord(autoStatus.guardrails) ? autoStatus.guardrails : {};
      const executionSafety = isRecord(data.execution_safety) ? data.execution_safety : {};
      const candidates = [guardrails.risk_flags, data.guardrail_risk_flags, executionSafety.risk_flags];
      return asArray(candidates.find(Array.isArray)).filter(isRecord);
    }

    function renderRisk(data) {
      const flags = riskFlags(data);
      const blocks = flags.filter((flag) => flag.level === "block");
      const badges = byId("risk-badges");
      badges.replaceChildren();
      badges.hidden = blocks.length === 0;
      if (blocks.length) badges.append(create("span", "badge block", "차단 " + blocks.length + "건"));

      const card = byId("risk-card");
      const list = byId("risk-flags");
      list.replaceChildren();
      card.hidden = flags.length === 0;
      flags.forEach((flag) => {
        const level = flag.level === "block" ? "block" : "warn";
        const row = create("div", "flag " + level);
        const label = create("b", "", level === "block" ? "차단 " : "경고 ");
        row.append(label, document.createTextNode(boundedText(flag.message || flag.key, 500)));
        list.append(row);
      });
    }

    function assetPoints(history) {
      return asArray(history).map((entry) => {
        const value = typeof entry === "number" ? entry : isRecord(entry) ? entry.account_total_asset_krw : null;
        // 장중(intraday)은 generated_at, 일봉(daily)은 trade_date 사용
        const tsRaw = isRecord(entry) ? (entry.generated_at || entry.trade_date || "") : "";
        const timestamp = isRecord(entry) ? Date.parse(String(tsRaw)) : NaN;
        const number = finiteNumber(value);
        return number !== null && number > 0 && Number.isFinite(timestamp) ? { t: timestamp, v: number, source: isRecord(entry) ? entry.source : null, estimated: isRecord(entry) ? !!entry.estimated : false } : null;
      }).filter(Boolean).sort((a, b) => a.t - b.t);
    }

    function getPeriodWindow(period, points) {
      if (!points.length) return [];
      const lastT = points[points.length - 1].t;
      const windows = {
        "1d": 1 * 86400000, "7d": 7 * 86400000, "1m": 30 * 86400000,
        "all": Infinity
      };
      if (period === "all") return points;
      const windowMs = windows[period] ?? Infinity;
      // 자비스 기준: 정확히 N×24시간 윈도우 (휴일 무관, 마지막 포인트 시각 기준)
      return points.filter((p) => p.t >= lastT - windowMs);
    }

    function aggregateDaily(points) {
      if (points.length < 2) return points;
      const daily = {};
      for (const p of points) {
        const day = new Date(p.t).toISOString().slice(0, 10);
        daily[day] = p;
      }
      return Object.values(daily).sort((a, b) => a.t - b.t);
    }

    function periodLabel(period) {
      const labels = { "1d": "1일", "7d": "7일", "1m": "1개월", "all": "전체" };
      return labels[period] ?? "전체";
    }

    function renderChart() {
      const chart = byId("asset-chart");
      const empty = byId("asset-chart-empty");
      const change = byId("asset-change");
      const hover = byId("asset-chart-hover");
      const hoverValue = byId("asset-chart-hover-value");
      const hoverTime = byId("asset-chart-hover-time");
      const xaxis = byId("asset-chart-xaxis");
      xaxis.replaceChildren();
      chart.replaceChildren();
      // 컨테이너 실제 폭을 viewBox width로 사용 (창 크기 따라 자동 조절)
      const wrapRect = chart.parentElement.getBoundingClientRect();
      const vbWidth = Math.max(320, Math.round(wrapRect.width || 600));
      const cs = window.getComputedStyle(chart);
      const cssH = parseFloat(cs.height) || 140;
      const vbHeight = Math.max(120, Math.round(cssH));
      chart.setAttribute("viewBox", "0 0 " + vbWidth + " " + vbHeight);
      chart.setAttribute("preserveAspectRatio", "xMidYMid meet");

      const svgDefs = svgCreate("defs");
      svgDefs.innerHTML = '<linearGradient id="chart-fill-gradient" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#ef4444" stop-opacity="0.25"></stop><stop offset="100%" stop-color="#ef4444" stop-opacity="0"></stop></linearGradient>';
      chart.append(svgDefs);

      // 해상도별 데이터 소스 분기:
      // 1일/7일 = 장중 3분 데이터 (history, intraday)
      // 1개월/전체 = 일봉 (daily)
      const useDaily = ["1m", "all"].includes(state.assetPeriod);
      const rawHistory = useDaily
        ? (isRecord(state.data) && Array.isArray(state.data.daily) ? state.data.daily : [])
        : (isRecord(state.data) ? state.data.history : []);
      const points = assetPoints(rawHistory);
      let filtered = getPeriodWindow(state.assetPeriod, points);
      
      // 1개월/전체 기간은 일별 집계 (하나의 점 = 하루의 마지막 값)
      // 1일/7일은 인트라데이 데이터 모두 표시
      if (["1m", "all"].includes(state.assetPeriod)) {
        filtered = aggregateDaily(filtered);
      }
      
      // 병합: 급변하지 않은 연속 데이터는 하나의 세그먼트로 합치기
      const runs = [];
      filtered.forEach((point) => {
        if (!runs.length) { runs.push(point); return; }
        const last = runs[runs.length - 1];
        const prev = last.v || 1;
        const relChange = Math.abs(point.v - last.v) / prev;
        const absChange = Math.abs(point.v - last.v);
        if (absChange > 10000 || relChange > 0.0002) runs.push(point);
        else runs[runs.length - 1] = point;
      });
      if (runs.length === 1) {
        const only = runs[0];
        runs.unshift({ ...only, t: only.t - 60000, v: only.v });
      }

      chart.hidden = runs.length < 2;
      empty.hidden = runs.length >= 2;
      change.hidden = runs.length < 2;
      hover.hidden = runs.length < 2;
      xaxis.hidden = runs.length < 2;
      if (runs.length < 2) return;

      const width = vbWidth;
      const height = vbHeight;
      const padLeft = 12;
      const padRight = 12;
      const padTop = 10;
      const padBottom = 26;
      const plotW = width - padLeft - padRight;
      const plotH = height - padTop - padBottom;

      // 투자 원금 기준선 = 총자산 - (실현+평가 합계) (사용자 공식)
      const metrics = isRecord(state.data) ? state.data.metrics : {};
      const totalAsset = finiteNumber(metrics.account_total_asset_krw);
      const totalPnl = finiteNumber(metrics.total_pnl_krw);
      const principal = (totalAsset !== null && totalPnl !== null) ? totalAsset - totalPnl : null;

      const min = Math.min(...runs.map((p) => p.v));
      const max = Math.max(...runs.map((p) => p.v));
      const range = max - min || 1;
      // 여백 추가: min/max에 패딩
      const padRange = range * 0.06;
      const minVal = min - padRange;
      const maxVal = max + padRange;
      const paddedRange = maxVal - minVal || 1;

      const toX = (point, index) => padLeft + index / (runs.length - 1) * plotW;
      const toY = (v) => height - padBottom - (v - minVal) / paddedRange * plotH;
      const xs = runs.map((_, i) => toX(runs[i], i));
      const ys = runs.map((p) => toY(p.v));

      const first = runs[0];
      const last = runs[runs.length - 1];
      // 전체 탭은 첫/마지막 차이 대신 투자원금(총자산 기준값) 대비 현재값 변화
      const isAllPeriod = state.assetPeriod === "all";
      const baseV = (isAllPeriod && principal !== null) ? principal : first.v;
      const baseLabel = isAllPeriod ? "투자원금" : periodLabel(state.assetPeriod);
      const difference = last.v - baseV;
      const rate = baseV ? difference / baseV : 0;
      const tone = pnlClass(difference);

      // 변화 카드
      const changeText = (difference > 0 ? "+" : "") + formatKrw(difference) + "원 (" + formatPct(rate) + ")";
      change.className = "asset-change" + (tone ? " " + tone : "");
      change.innerHTML = "<span class=\"asset-change-period\">" + baseLabel + "</span> " + changeText;
      chart.className.baseVal = "asset-chart" + (tone ? " " + tone : "");
      chart.setAttribute("aria-label", "총자산 " + periodLabel(state.assetPeriod) + " 변동 " + changeText);

      // 가격축 (좌측) - 4개의 가치
      const priceTicks = [
        { label: formatKrw(maxVal), y: toY(maxVal) },
        { label: formatKrw(maxVal - range * 0.33), y: toY(maxVal - range * 0.33) },
        { label: formatKrw(maxVal - range * 0.66), y: toY(maxVal - range * 0.66) },
        { label: formatKrw(minVal), y: toY(minVal) }
      ];
      priceTicks.forEach((tick) => {
        // 그리드 라인
        chart.append(svgCreate("line", { x1: padLeft, x2: width - padRight, y1: tick.y, y2: tick.y, class: "chart-grid" }));
      });

      // 투자 원금 수평 기준선
      if (principal !== null) {
        const principalY = toY(principal);
        chart.append(svgCreate("line", { x1: padLeft, x2: width - padRight, y1: principalY, y2: principalY, class: "chart-principal" }));
      }

      // 시간축 (하단) - 5개의 시간 레이블 (HTML로 분리해 고정 폰트 유지)
      const timeCount = runs.length;
      const timeIndexes = [...new Set([0, Math.floor((timeCount - 1) * 0.25), Math.floor((timeCount - 1) * 0.5), Math.floor((timeCount - 1) * 0.75), timeCount - 1])];
      timeIndexes.forEach((index) => {
        chart.append(svgCreate("line", { x1: xs[index], x2: xs[index], y1: height - padBottom, y2: height - padBottom + 4, class: "chart-tick" }));
        const d = new Date(runs[index].t);
        let timeStr;
        const isIntraday = (last.t - first.t) < 86400000 * 2;
        if (isIntraday) {
          timeStr = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
        } else if ((last.t - first.t) < 86400000 * 30) {
          timeStr = d.toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" });
        } else if ((last.t - first.t) < 86400000 * 365) {
          timeStr = d.toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" });
        } else {
          timeStr = d.toLocaleDateString("ko-KR", { year: "2-digit", month: "2-digit" });
        }
        const label = create("span", "asset-chart-xlabel", timeStr);
        label.style.left = (xs[index] / width * 100) + "%";
        xaxis.append(label);
      });

      // 투자 원금 기준선 y값 (이미 위에서 principalY 계산됨)
      const principalY = toY(principal);

      // 면적 경로 (전체)
      const areaPath = "M " + xs[0] + " " + (height - padBottom) + " L " + runs.map((_, i) => xs[i] + " " + ys[i]).join(" L ") + " L " + xs[xs.length - 1] + " " + (height - padBottom) + " Z";
      const linePoints = runs.map((_, i) => xs[i] + "," + ys[i]).join(" ");

      // 1일 탭: 토스 스타일 (단일 톤, 클립 분할 없음). 색/해치는 dashboard.css 한 곳에서 정의.
      const isTossDayStyle = state.assetPeriod === "1d";
      if (isTossDayStyle) {
        const toneCls = tone === "up" ? "up" : (tone === "down" ? "down" : "");
        const areaDay = svgCreate("path", { d: areaPath, class: "chart-area chart-area-" + toneCls });
        chart.append(areaDay);
        const hatchDay = svgCreate("path", { d: areaPath, class: "chart-hatch-" + toneCls });
        chart.append(hatchDay);
        const lineDay = svgCreate("polyline", { points: linePoints, class: "chart-line chart-line-" + toneCls });
        chart.append(lineDay);
      } else {
      // 상/하 클립 영역 정의 (기준선 기준 분할 색상)
      const clipTop = "clip-principal-top-" + state.assetPeriod;
      const clipBottom = "clip-principal-bottom-" + state.assetPeriod;
      const defsClip = svgCreate("defs");
      defsClip.innerHTML =
        '<clipPath id="' + clipTop + '"><rect x="0" y="0" width="' + width + '" height="' + principalY + '"></rect></clipPath>' +
        '<clipPath id="' + clipBottom + '"><rect x="0" y="' + principalY + '" width="' + width + '" height="' + (height - principalY) + '"></rect></clipPath>';
      chart.append(defsClip);

      // 위 영역 (붉은색) + 해치
      const areaTop = svgCreate("path", { d: areaPath, class: "chart-area chart-area-up" });
      areaTop.setAttribute("clip-path", "url(#" + clipTop + ")");
      chart.append(areaTop);
      const hatchTop = svgCreate("path", { d: areaPath, class: "chart-hatch-up" });
      hatchTop.setAttribute("clip-path", "url(#" + clipTop + ")");
      chart.append(hatchTop);

      // 아래 영역 (파란색) + 해치
      const areaBottom = svgCreate("path", { d: areaPath, class: "chart-area chart-area-down" });
      areaBottom.setAttribute("clip-path", "url(#" + clipBottom + ")");
      chart.append(areaBottom);
      const hatchBottom = svgCreate("path", { d: areaPath, class: "chart-hatch-down" });
      hatchBottom.setAttribute("clip-path", "url(#" + clipBottom + ")");
      chart.append(hatchBottom);

      // 라인 (위/아래 분할)
      const lineTop = svgCreate("polyline", { points: linePoints, class: "chart-line chart-line-up" });
      lineTop.setAttribute("clip-path", "url(#" + clipTop + ")");
      chart.append(lineTop);
      const lineBottom = svgCreate("polyline", { points: linePoints, class: "chart-line chart-line-down" });
      lineBottom.setAttribute("clip-path", "url(#" + clipBottom + ")");
      chart.append(lineBottom);
      }

      // 호버 카드 (클릭 시 표시)
      chart.addEventListener("mousemove", (evt) => {
        const rect = chart.getBoundingClientRect();
        const x = evt.clientX - rect.left;
        const y = evt.clientY - rect.top;
        const clampedX = Math.max(0, Math.min(1, x / rect.width));
        const index = Math.round(clampedX * (runs.length - 1));
        const point = runs[Math.max(0, Math.min(runs.length - 1, index))];
        hoverValue.textContent = formatKrw(point.v) + "원";
        const pd = new Date(point.t);
        let timeText;
        const isIntradayChart = (last.t - first.t) < 86400000 * 2;
        if (isIntradayChart) {
          timeText = pd.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
        } else {
          timeText = pd.toLocaleString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
        }
        hoverTime.textContent = timeText;
        hover.style.left = (x + 8) + "px";
        hover.style.top = (y - 10) + "px";
        hover.hidden = false;
      });

      chart.addEventListener("mouseleave", () => { hover.hidden = true; });
    }

    function renderAssets(data) {
      const metrics = isRecord(data.metrics) ? data.metrics : {};
      setText("asset-total", formatKrw(metrics.account_total_asset_krw) + "원");
      setPnl("profit-loss", metrics.account_profit_loss_krw, formatKrw(metrics.account_profit_loss_krw) + "원");
      setPnl("profit-loss-rate", metrics.account_profit_loss_rate, formatPct(metrics.account_profit_loss_rate));
      const operating = metrics.current_operating_capital_krw ?? metrics.operating_evaluated_krw;
      const buyingPower = metrics.broker_buying_power_krw ?? metrics.operating_cash_krw;
      setText("operating-capital", formatKrw(operating) + "원");
      setText("initial-capital", "초기 " + formatKrw(metrics.initial_operating_capital_krw) + "원");
      setText("buying-power", formatKrw(buyingPower) + "원");
      if (metrics.total_pnl_krw != null) {
        setPnl("total-pnl", metrics.total_pnl_krw, formatKrw(metrics.total_pnl_krw) + "원");
        setPnl("total-pnl-rate", metrics.total_pnl_rate, formatPct(metrics.total_pnl_rate / 100));
      }
      renderChart();
    }

    let candleChart = null;
    let quoteState = { active: "069500", interval: "3m" };
    const SYM_NAMES = { "069500": "KODEX 200", "315930": "KODEX Top5PlusTR" };

    async function renderQuotes() {
      try {
        const q = await fetchJson("/toss/dashboard_data_api.php?table=quotes_data");
        if (!q || !q.symbols) return;
        // tabs
        const tabs = byId("quote-tabs");
        tabs.replaceChildren();
        for (const sym of Object.keys(q.symbols)) {
          const b = create("button", "quote-tab" + (sym === quoteState.active ? " active" : ""), (SYM_NAMES[sym] || sym));
          b.onclick = () => { quoteState.active = sym; renderQuotes(); };
          tabs.append(b);
        }
        const rec = q.symbols[quoteState.active] || {};
        setText("quote-sym-name", (SYM_NAMES[quoteState.active] || quoteState.active) + " (" + quoteState.active + ")");
        setText("quote-last", rec.last != null ? formatKrw(rec.last) + "원" : "—");
        // interval toggle
        const sub = byId("quote-sub");
        sub.replaceChildren();
        for (const iv of ["3m", "1d"]) {
          const b = create("button", "quote-iv" + (iv === quoteState.interval ? " active" : ""), iv === "3m" ? "분봉 3m" : "일봉 1d");
          b.onclick = () => { quoteState.interval = iv; renderQuotes(); };
          sub.append(b);
        }
        // list (all symbols latest)
        const list = byId("quote-list");
        list.replaceChildren();
        for (const [sym, r] of Object.entries(q.symbols)) {
          const row = create("div", "quote-row" + (sym === quoteState.active ? " active" : ""));
          row.append(create("span", "quote-row-name", SYM_NAMES[sym] || sym));
          row.append(create("span", "quote-row-last", r.last != null ? formatKrw(r.last) + "원" : "—"));
          row.onclick = () => { quoteState.active = sym; renderQuotes(); };
          list.append(row);
        }
        setText("quote-updated", "시세 갱신: " + displayTime(q.generated_at));
        drawCandle(rec, quoteState.interval);
      } catch (e) {
        setText("quote-updated", "시세 로드 실패");
      }
    }

    function drawCandle(rec, interval) {
      const candles = interval === "1d" ? (rec.candles_1d || []) : (rec.candles_3m || []);
      const cv = byId("candleChart");
      if (!cv || !candles.length) return;
      const parent = cv.parentElement;
      const W = parent.clientWidth || 480, H = 260;
      cv.width = W; cv.height = H;
      const ctx = cv.getContext("2d");
      ctx.clearRect(0, 0, W, H);
      const pad = 8;
      const highs = Math.max(...candles.map(c => c.high));
      const lows = Math.min(...candles.map(c => c.low));
      const range = (highs - lows) || 1;
      const cw = (W - pad * 2) / candles.length;
      const y = v => pad + (1 - (v - lows) / range) * (H - pad * 2);
      for (let i = 0; i < candles.length; i++) {
        const c = candles[i];
        const x = pad + i * cw + cw / 2;
        const up = c.close >= c.open;
        ctx.strokeStyle = up ? "#3fb950" : "#f85149";
        ctx.fillStyle = up ? "#3fb950" : "#f85149";
        ctx.beginPath(); ctx.moveTo(x, y(c.high)); ctx.lineTo(x, y(c.low)); ctx.stroke();
        const yo = y(c.open), yc = y(c.close);
        const top = Math.min(yo, yc), bh = Math.max(1, Math.abs(yo - yc));
        ctx.fillRect(x - cw * 0.3, top, cw * 0.6, bh);
      }
    }

    function renderItems(targetId, values, emptyText) {
      const target = byId(targetId);
      target.replaceChildren();
      const items = asArray(values).slice(0, 8);
      if (!items.length) {
        target.append(create("div", "empty", emptyText));
        return;
      }
      const list = create("ul", "briefing-items");
      items.forEach((item) => list.append(create("li", "", describeValue(item))));
      target.append(list);
    }

    function renderMacro(briefing) {
      const macro = isRecord(briefing.macro) ? briefing.macro : {};
      const evidence = isRecord(briefing.evidence) ? briefing.evidence : {};
      const sections = asArray(macro.sections).length ? asArray(macro.sections) : asArray(evidence.macro_sections);
      const target = byId("briefing-macro");
      target.replaceChildren();
      if (!sections.length) {
        target.append(create("div", "empty", "표시 가능한 근거 없음"));
        return;
      }
      const list = create("ul", "briefing-items");
      sections.slice(0, 8).forEach((entry, index) => {
        const section = isRecord(entry) ? entry : {};
        const item = create("li");
        const title = create("b", "", boundedText(section.title || "섹션 " + (index + 1), 60));
        item.append(title, document.createTextNode(" — " + boundedText(section.body ?? entry, 500)));
        list.append(item);
      });
      target.append(list);
    }

    function proposalAction(proposal) {
      const side = typeof proposal.side === "string" ? proposal.side.toLowerCase() : "";
      if (side === "buy") return "매수";
      if (side === "sell") return "매도";
      if (side === "weight" || side === "rebalance" || proposal.weight_change !== undefined) return "비중 조정";
      return boundedText(proposal.side || "제안", 24);
    }

    function renderNews(briefing) {
      const target = byId("briefing-news");
      target.replaceChildren();
      const news = isRecord(briefing.news) ? briefing.news : {};
      const perPosition = isRecord(news.per_position) ? news.per_position : {};
      const risks = asArray(news.global_risks).filter(isRecord);
      const calendar = asArray(news.calendar).filter(isRecord);
      if (!Object.keys(perPosition).length && !risks.length && !calendar.length) {
        target.append(create("div", "empty", "수집된 뉴스 없음"));
        return;
      }
      if (Object.keys(perPosition).length) {
        const h = create("h4", "", "보유 종목 뉴스");
        target.append(h);
        const list = create("ul", "briefing-items");
        Object.values(perPosition).forEach((p) => {
          if (!isRecord(p)) return;
          const name = p.name || "종목";
          const items = asArray(p.news).filter(isRecord).slice(0, 3);
          if (!items.length) return;
          const li = create("li");
          li.append(create("b", "", boundedText(name, 40) + ": "));
          li.append(create("span", "", items.map((it) => boundedText(it.title || "", 120)).join(" / ")));
          list.append(li);
        });
        target.append(list);
      }
      if (risks.length) {
        target.append(create("h4", "", "글로벌 리스크"));
        target.append(renderNewsList(risks, 5));
      }
      if (calendar.length) {
        target.append(create("h4", "", "경제 일정"));
        target.append(renderNewsList(calendar, 5));
      }
    }

    function renderNewsList(items, limit) {
      const list = create("ul", "briefing-items");
      items.slice(0, limit).forEach((it) => {
        const li = create("li");
        li.append(create("span", "", boundedText(it.title || "", 200)));
        list.append(li);
      });
      return list;
    }

    function renderProposals(briefing) {
      const target = byId("briefing-proposals");
      target.replaceChildren();
      const proposals = asArray(briefing.execution_proposals).filter(isRecord).slice(0, 12);
      if (!proposals.length) {
        target.append(create("div", "empty", "제안 없음"));
        return;
      }
      proposals.forEach((proposal) => {
        const card = create("article", "briefing-proposal");
        const head = create("div", "briefing-proposal-head");
        head.append(
          create("b", "", boundedText(proposal.symbol, 30) + " · " + proposalAction(proposal)),
          create("span", "briefing-proposal-status", boundedText(proposal.status || "-", 30))
        );
        const meta = create("div", "briefing-proposal-meta");
        if (proposal.weight_change !== undefined) meta.append(create("span", "", "비중 " + boundedText(proposal.weight_change, 30)));
        if (proposal.label) meta.append(create("span", "", boundedText(proposal.label, 160)));
        if (proposal.basis) meta.append(create("span", "muted", "근거: " + boundedText(proposal.basis, 360)));
        card.append(head, meta);
        target.append(card);
      });
    }

    function selectedBriefing() {
      return state.briefingHistory.find((item) => item.generated_at === state.selectedBriefingAt) || state.briefingHistory[0] || null;
    }

    function renderBriefingDetails(data) {
      const briefing = selectedBriefing();
      const hasBriefing = Boolean(briefing);
      // 브리핑 패널 표시: AI 브리핑 있거나, 뉴스 브리핑 데이터가 있으면 보이기
      const hasNews = isRecord(data?.news_briefing) && Object.keys(data.news_briefing).length > 0;
      byId("briefing-body").hidden = !hasBriefing && !hasNews;
      byId("briefing-empty").hidden = hasBriefing || hasNews;
      if (!hasBriefing) {
        // AI 브리핑이 없어도 뉴스 브리핑은 렌더링
        renderNewsBriefing(data?.news_briefing);
        return;
      }
      setText("briefing-date", boundedText(briefing.operating_date || briefing.generated_at, 30));
      setText("briefing-status", boundedText(briefing.status || briefing.state, 48));
      setText("briefing-summary", boundedText(briefing.summary, 1200));
      renderMacro(briefing);
      renderNews(briefing);
      renderItems("briefing-red-team", briefing.red_team, "표시된 위험 플래그 없음");
      renderItems("briefing-actions", briefing.action_labels, "행동 라벨 없음");
      renderProposals(briefing);
      renderNewsBriefing(data.news_briefing);
    }

    function renderNewsBriefing(news) {
      const positionsTarget = byId("briefing-news-positions");
      const globalList = byId("briefing-global-risks-list");
      const calendarList = byId("briefing-calendar-list");
      [positionsTarget, byId("briefing-news-global"), byId("briefing-news-calendar")].forEach((el) => {
        if (el) el.hidden = false;
      });

      // 종목별 뉴스
      if (positionsTarget) positionsTarget.replaceChildren();
      const perPosition = isRecord(news) ? news.per_position : {};
      if (positionsTarget && isRecord(perPosition) && Object.keys(perPosition).length > 0) {
        Object.entries(perPosition).forEach(([symbol, entry]) => {
          if (!isRecord(entry)) return;
          const block = create("div", "news-position-block");
          block.append(create("b", "news-position-symbol", boundedText(entry.name || symbol, 40)));
          const list = create("ul", "news-position-list");
          asArray(entry.news).slice(0, 5).forEach((item) => {
            if (!isRecord(item)) return;
            const li = create("li", "news-item");
            li.append(
              create("a", "news-link", boundedText(item.title || "", 200)),
              create("span", "news-meta", boundedText(item.published_at || "", 20))
            );
            li.querySelector(".news-link").addEventListener("click", () => openNewsUrl(item.url));
            list.append(li);
          });
          block.append(list);
          positionsTarget.append(block);
        });
      } else if (positionsTarget) {
        positionsTarget.append(create("div", "empty", "종목별 뉴스 없음"));
      }

      // 글로벌 리스크
      if (globalList) globalList.replaceChildren();
      const risks = isRecord(news) ? asArray(news.global_risks) : [];
      if (globalList) {
        if (risks.length === 0) {
          globalList.append(create("li", "empty", "글로벌 리스크 없음"));
        } else {
          risks.slice(0, 5).forEach((item) => {
            if (!isRecord(item)) return;
            const li = create("li", "news-item");
            li.append(
              create("a", "news-link", boundedText(item.title || "", 200)),
              create("span", "news-meta", boundedText(item.published_at || "", 20))
            );
            li.querySelector(".news-link").addEventListener("click", () => openNewsUrl(item.url));
            globalList.append(li);
          });
        }
      }

      // 경제 캘린더
      if (calendarList) calendarList.replaceChildren();
      const events = isRecord(news) ? asArray(news.calendar) : [];
      if (calendarList) {
        if (events.length === 0) {
          calendarList.append(create("li", "empty", "이번 주 경제 일정 없음"));
        } else {
          events.slice(0, 10).forEach((item) => {
            if (!isRecord(item)) return;
            const li = create("li", "news-item");
            li.append(
              create("a", "news-link", boundedText(item.title || "", 200)),
              create("span", "news-meta", boundedText(item.published_at || "", 20))
            );
            li.querySelector(".news-link").addEventListener("click", () => openNewsUrl(item.url));
            calendarList.append(li);
          });
        }
      }
    }

    function openNewsUrl(url) {
      if (url && typeof url === "string" && url.startsWith("http")) {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    }

    function renderBriefings(data, storedHistory) {
      const latest = isRecord(data.ai_briefing) && typeof data.ai_briefing.generated_at === "string" ? data.ai_briefing : null;
      const candidates = [latest, ...asArray(storedHistory)].filter((item) => isRecord(item) && typeof item.generated_at === "string");
      state.briefingHistory = candidates.filter((item, index, items) => items.findIndex((candidate) => candidate.generated_at === item.generated_at) === index);
      if (!state.briefingHistory.some((item) => item.generated_at === state.selectedBriefingAt)) {
        state.selectedBriefingAt = state.briefingHistory[0]?.generated_at || null;
      }
      const target = byId("briefing-history");
      target.replaceChildren();
      byId("briefing-history-empty").hidden = state.briefingHistory.length > 0;
      state.briefingHistory.forEach((item) => {
        const button = create("button", "briefing-history-item");
        button.type = "button";
        button.setAttribute("role", "listitem");
        const selected = item.generated_at === state.selectedBriefingAt;
        button.classList.toggle("is-selected", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        button.append(create("b", "", boundedText(item.generated_at, 24)), create("span", "", boundedText(item.summary, 100)));
        button.addEventListener("click", () => {
          state.selectedBriefingAt = item.generated_at;
          renderBriefings(state.data, state.briefingHistory);
        });
        target.append(button);
      });
      renderBriefingDetails(state.data);
    }

    function appendPositionName(cell, position) {
      cell.append(create("b", "", boundedText(position.name || position.symbol, 80)));
      if (position.symbol) cell.append(create("span", "ticker", boundedText(position.symbol, 30)));
    }

    function addCell(row, value, className = "") {
      const cell = create("td", className, value);
      row.append(cell);
      return cell;
    }

    function renderPositions(data) {
      const positions = asArray(data.positions).filter((position) => isRecord(position) && position.bucket === "jarvis_operation");
      setText("positions-title", "운용 포지션 (" + positions.length + ")");
      const body = byId("positions-body");
      body.replaceChildren();
      byId("positions-table-wrap").hidden = positions.length === 0;
      byId("positions-empty").hidden = positions.length > 0;
      positions.forEach((position) => {
        const row = create("tr");
        appendPositionName(addCell(row, ""), position);
        addCell(row, formatQty(position.quantity));
        addCell(row, formatKrw(position.purchase_price_krw));
        addCell(row, formatPct(position.pnl_rate), pnlClass(position.pnl_rate));
        addCell(row, formatPct(position.daily_rate), pnlClass(position.daily_rate));
        body.append(row);
      });

      const protectedPositions = asArray(data.protected_positions).filter(isRecord);
      byId("protected-card").hidden = protectedPositions.length === 0;
      setText("protected-title", "운용 제외 (보호) (" + protectedPositions.length + ")");
      const protectedBody = byId("protected-body");
      protectedBody.replaceChildren();
      protectedPositions.forEach((position) => {
        const row = create("tr");
        appendPositionName(addCell(row, ""), position);
        addCell(row, formatQty(position.quantity));
        addCell(row, formatKrw(position.purchase_price_krw));
        addCell(row, formatPct(position.pnl_rate), pnlClass(position.pnl_rate));
        addCell(row, formatPct(position.daily_rate), pnlClass(position.daily_rate));
        protectedBody.append(row);
      });
    }

    function renderActions(data) {
      const autoStatus = isRecord(data.auto_trading_status) ? data.auto_trading_status : {};
      const plan = isRecord(data.daily_trade_plan) ? data.daily_trade_plan : {};
      const actions = asArray(autoStatus.actions).slice(-20).reverse();
      const results = asArray(autoStatus.order_results).slice(-10).reverse();
      
      // 종목 코드 → 이름 매핑 (full_positions 기반)
      const nameBySymbol = {};
      const nameByIsin = {};
      asArray(data.full_positions).forEach((p) => {
        if (p.symbol && p.name) {
          nameBySymbol[p.symbol] = p.name;
          nameByIsin[p.stock_code] = p.name;
        }
      });
      asArray(data.positions).forEach((p) => {
        if (p.symbol && p.name) {
          nameBySymbol[p.symbol] = p.name;
          nameByIsin[p.stock_code] = p.name;
        }
      });
      
      if (!actions.length && !results.length) {
        byId("actions-card").hidden = true;
        return;
      }

      byId("actions-card").hidden = false;
      const list = byId("actions-list");
      list.replaceChildren();
      byId("actions-empty").hidden = true;

      const actionItems = [];
      
      actions.forEach((action) => {
        if (isRecord(action)) {
          const resolvedName = action.name || nameBySymbol[action.symbol] || nameByIsin[action.symbol] || "";
          actionItems.push({
            type: action.action || "ACTION",
            symbol: action.symbol || "",
            name: resolvedName,
            reason: action.reason || "",
            pnlRate: action.pnl_rate,
            time: null,
            isOrder: false
          });
        }
      });

      results.forEach((result) => {
        if (isRecord(result)) {
          const resolvedName = result.name || nameBySymbol[result.symbol] || nameByIsin[result.symbol] || "";
          actionItems.push({
            type: result.status || "ORDER",
            symbol: result.symbol || "",
            name: resolvedName,
            reason: result.reason || "",
            pnlRate: result.pnl_rate,
            time: result.at ? displayTime(result.at) : null,
            isOrder: true
          });
        }
      });

      actionItems.forEach((item) => {
        const el = create("div", "action-item");
        let side = item.type.toLowerCase();
        if (side.includes("buy") || side.includes("매수")) {
          el.classList.add("is-buy");
        } else if (side.includes("sell") || side.includes("매도")) {
          el.classList.add("is-sell");
        } else {
          el.classList.add("is-wait");
        }

        const icon = create("div", "action-icon");
        icon.textContent = side.includes("buy") || side.includes("매수") ? "↑" : side.includes("sell") || side.includes("매도") ? "↓" : "•";
        el.append(icon);

        const content = create("div", "action-content");
        
        const header = create("div", "action-header");
        const symbol = create("span", "action-symbol", item.symbol ? item.symbol + (item.name ? " · " + item.name : "") : "");
        const type = create("span", "action-type", item.type.replace(/_/g, " "));
        // action type 한글 표시
        const typeMap = {
          "BUY_SIGNAL": "매수 신호",
          "SELL_SIGNAL": "매도 신호",
          "SELL_WAIT_MARKET": "매도 시장 대기",
          "SELL_SKIPPED_EXCLUDED_SYMBOL": "매도 제외",
          "SELL_BLOCKED_NO_PRICE": "매도 차단",
          "SELL_BLOCKED_DAILY_LIMIT": "매도 차단 (일일 한도)",
          "KEEP_RIDE_TREND": "추세 유지",
          "DEFENSIVE_STOP_WATCH": "방어적 손절 감시",
          "KR_BUY_WAIT_MARKET": "국내 매수 시장 대기",
          "KR_BUY_SKIPPED": "국내 매수 스킵",
          "US_BUY_WAIT_MARKET": "미국 매수 시장 대기",
          "US_BUY_WAIT_QUOTE": "미국 매수 호가 대기",
          "US_BUY_WAIT_DIP": "미국 매수 DIP 대기",
          "US_BUY_WAIT_REBOUND": "미국 매수 반등 대기"
        };
        type.textContent = typeMap[item.type] || item.type.replace(/_/g, " ");
        header.append(symbol, type);
        
        const body = create("div", "action-body");
        const reasonMap = {
          // sell actions
          "symbol_in_operation_exclusions_partial_quantity_not_honored": "운용 제외 종목 (일부 수량)",
          "loss_threshold_hit_but_intraday_not_falling": "손절 임계치 도달 but 당일 하락 없음",
          "regular_market_closed": "시장 장외",
          "next_session_uptrend_no_losscut": "다음 세션 상승추세 — 손절 유예",
          "next_session_still_downtrend_partial": "다음 세션 하락추세 — 부분 매도",
          "partial_stop_loss": "부분 손절 매도",
          "missing_current_price_krw": "현재가 없음",
          // buy actions
          "no_chasing_or_unknown_change_rate": "추격 금지 rule — 스킵",
          "kr_regular_market_closed": "한국시장 장외",
          "us_regular_market_closed": "미국시장 장외",
          "daily_change_rate_unavailable": "변동률 조회 불가",
          "not_low_enough_for_dip_buy": "DIP 기준 미달 — 스킵",
          "no_rebound_from_session_low": "세가 저가 반등 없음",
          "session_low_unavailable": "세가 저가 정보 없음",
          "overseas_core_etf_daily_buy": "해외 코어 ETF 정기 매수",
          "overseas_core_etf_dip_buy": "해외 코어 ETF DIP 매수",
          // general
          "spendable_cash_below_minimum": "현금 부족",
          "bucket_mismatch": "버킷 불일치",
          "human_confirmation_required": "인간 확인 필요",
          "order_placed": "주문 실행됨",
          "order_failed": "주문 실패",
          "order_cancelled": "주문 취소됨"
        };
        const reasonText = reasonMap[item.reason] || item.reason || "";
        body.textContent = reasonText ? item.symbol + " - " + reasonText : item.symbol;
        
        content.append(header, body);
        
        if (item.time) {
          const timeEl = create("div", "action-time", item.time);
          content.append(timeEl);
        }

        if (item.pnlRate !== null && item.pnlRate !== undefined) {
          const pnlEl = create("span", "action-pnl " + pnlClass(item.pnlRate));
          pnlEl.textContent = formatPct(item.pnlRate);
          content.append(pnlEl);
        }

        el.append(content);
        list.append(el);
      });
    }

    function renderDashboard(data, storedHistory) {
      state.data = data;
      setText("screen-updated", new Date().toLocaleTimeString("ko-KR"));
      setText("data-generated", displayTime(data.generated_at));
      renderAssets(data);
      renderRisk(data);
      renderBriefings(data, storedHistory);
      renderPositions(data);
      renderActions(data);
      renderQuotes();
    }

    async function loadDashboard() {
      try {
        const [data, briefingHistory, assetApi, dailyApi] = await Promise.all([
          fetchJson("/toss/dashboard_data_api.php?table=dashboard_data"),
          fetchJson("/toss/ai-daily-briefing-history.json").catch(() => []),
          fetchJson("/toss/asset_history_api.php?period=" + encodeURIComponent(state.assetPeriod) + "&t=" + Date.now()).catch(() => null),
          fetchJson("/toss/asset_history_api.php?period=1m&t=" + Date.now()).catch(() => null)
        ]);
        if (!isRecord(data)) throw new Error("대시보드 데이터 형식이 올바르지 않습니다.");
        if (isRecord(assetApi)) {
          if (Array.isArray(assetApi.history) && assetApi.history.length > (asArray(data.history).length || 0)) {
            data.history = assetApi.history;
          }
          if (Array.isArray(assetApi.daily) && assetApi.daily.length) {
            data.daily = assetApi.daily;
          }
        }
        if (isRecord(dailyApi) && Array.isArray(dailyApi.daily) && dailyApi.daily.length) {
          data.daily = dailyApi.daily;
        }
        renderDashboard(data, briefingHistory);
        showNotice("");
      } catch (error) {
        showNotice("데이터를 불러올 수 없습니다: " + boundedText(error instanceof Error ? error.message : error, 240), true);
      }
    }

    function parseControl(value) {
      return isRecord(value) ? {
        enabled: value.enabled === true,
        updated_at: typeof value.updated_at === "string" ? value.updated_at : null
      } : { enabled: false, updated_at: null };
    }

    function renderControl(errorMessage = "") {
      const card = byId("control-card");
      const button = byId("trade-switch");
      const error = byId("control-error");
      const enabled = state.control?.enabled === true;
      card.className = "control-card " + (state.control ? (enabled ? "is-enabled" : "is-disabled") : "is-pending") + (errorMessage ? " has-error" : "");
      setText("control-detail", state.control ? (enabled ? "허용" : "차단") : "확인 중…");
      setText("control-updated", state.control?.updated_at ? "제어 상태 기준 " + displayTime(state.control.updated_at) : "");
      error.hidden = !errorMessage;
      error.textContent = errorMessage ? "오류: " + errorMessage : "";
      button.disabled = !state.control || state.controlBusy;
      button.className = "action-button trade-switch " + (enabled ? "on" : "off");
      button.setAttribute("aria-checked", enabled ? "true" : "false");
      setText("trade-switch-label", state.controlBusy ? "처리 중" : enabled ? "ON" : "OFF");
    }

    async function loadControl() {
      try {
        state.control = parseControl(await fetchJson("/toss/control.php"));
        renderControl();
      } catch (error) {
        renderControl(boundedText(error instanceof Error ? error.message : error, 180));
      }
    }

    async function toggleTrade() {
      if (!state.control || state.controlBusy) return;
      state.controlBusy = true;
      renderControl();
      let postError = "";
      try {
        const payload = await fetchJson("/toss/control.php", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: !state.control.enabled })
        });
        state.control = parseControl(payload);
      } catch (error) {
        postError = boundedText(error instanceof Error ? error.message : error, 180);
      } finally {
        try {
          state.control = parseControl(await fetchJson("/toss/control.php"));
        } catch (error) {
          if (!postError) postError = boundedText(error instanceof Error ? error.message : error, 180);
        }
        state.controlBusy = false;
        renderControl(postError);
      }
    }

    async function refreshAll() {
      const button = byId("refresh-button");
      button.disabled = true;
      await Promise.allSettled([loadDashboard(), loadControl()]);
      button.disabled = false;
    }

    async function refreshBriefing() {
      const button = byId("briefing-refresh-button");
      button.disabled = true;
      button.textContent = "갱신 중…";
      try {
        await fetchJson("/toss/generate-briefing.php");
        await loadDashboard();
      } catch (error) {
        showNotice("브리핑 갱신 실패: " + boundedText(error instanceof Error ? error.message : error, 240), true);
      } finally {
        button.disabled = false;
        button.textContent = "브리핑 갱신";
      }
    }

    async function loadAssetSeries(period) {
      try {
        const assetApi = await fetchJson("/toss/asset_history_api.php?period=" + encodeURIComponent(period) + "&t=" + Date.now());
        if (isRecord(assetApi)) {
          if (Array.isArray(assetApi.history) && assetApi.history.length) state.data.history = assetApi.history;
          if (Array.isArray(assetApi.daily) && assetApi.daily.length) state.data.daily = assetApi.daily;
        }
      } catch (e) {
        // 실패해도 기존 데이터로 렌더
      }
      renderChart();
    }

    function setAssetPeriod(period) {
      state.assetPeriod = period;
      const tabs = ["1d", "7d", "1m", "all"];
      tabs.forEach((tab) => {
        const el = byId("period-" + tab);
        el.classList.toggle("is-selected", tab === period);
        el.setAttribute("aria-pressed", tab === period ? "true" : "false");
      });
      loadAssetSeries(period);
    }

    byId("refresh-button").addEventListener("click", refreshAll);
    byId("briefing-refresh-button").addEventListener("click", refreshBriefing);
    byId("reauth-button").addEventListener("click", () => window.open("https://auth.cert.toss.im", "_blank", "noopener,noreferrer"));
    byId("trade-switch").addEventListener("click", toggleTrade);
    byId("period-1d").addEventListener("click", () => setAssetPeriod("1d"));
    byId("period-7d").addEventListener("click", () => setAssetPeriod("7d"));
    byId("period-1m").addEventListener("click", () => setAssetPeriod("1m"));
    byId("period-all").addEventListener("click", () => setAssetPeriod("all"));

    const topStocksButton = byId("top-stocks-button");
    const topStocksOverlay = document.createElement("div");
    topStocksOverlay.id = "top-stocks-modal-overlay";
    topStocksOverlay.style.cssText = "position:fixed;inset:0;z-index:1000;display:none;align-items:center;justify-content:center;padding:16px;background:rgba(0,0,0,.72);";
    topStocksOverlay.innerHTML = `
      <section role="dialog" aria-modal="true" aria-labelledby="top-stocks-title" style="background:var(--surface);border:1px solid var(--border-strong);border-radius:12px;max-width:900px;width:min(900px,96vw);max-height:82vh;overflow:auto;padding:20px;position:relative;">
        <button type="button" id="top-stocks-modal-close" aria-label="닫기" style="position:absolute;top:10px;right:12px;border:0;background:transparent;color:var(--muted);font-size:24px;cursor:pointer;">×</button>
        <h2 id="top-stocks-title" style="margin:0 0 14px;">매수 후보 종목</h2>
        <div id="top-stocks-summary" class="muted">불러오는 중…</div>
        <div style="overflow:auto;margin-top:12px;"><table class="pos-table"><thead><tr><th>순위</th><th>코드</th><th>종목명</th><th>현재가(원)</th><th>상태</th></tr></thead><tbody id="top-stocks-modal-body"></tbody></table></div>
        <div id="top-stocks-modal-empty" class="empty" hidden>후보 종목이 없습니다.</div>
      </section>`;
    document.body.append(topStocksOverlay);

    function closeTopStocksModal() {
      topStocksOverlay.style.display = "none";
    }

    async function openTopStocksModal() {
      topStocksOverlay.style.display = "flex";
      const summary = byId("top-stocks-summary");
      const body = byId("top-stocks-modal-body");
      const empty = byId("top-stocks-modal-empty");
      body.replaceChildren();
      empty.hidden = true;
      summary.textContent = "불러오는 중…";
      try {
        const data = state.data || await fetchJson("/toss/dashboard-data.json");
        const candidates = asArray(data.kr_screen_candidates).filter(isRecord);
        const cash = Number(data.metrics?.operating_cash_krw ?? 0) || 0;
        summary.textContent = `전체 ${candidates.length}종목 · 주문가능 현금 ${Math.round(cash).toLocaleString("ko-KR")}원`;
        candidates.slice(0, 20).forEach((candidate, index) => {
          const row = document.createElement("tr");
          [index + 1, candidate.code || "-", candidate.name || "-", formatKrw(candidate.price), Number(candidate.price) <= cash ? "매수 가능" : "현금 초과"].forEach((value) => {
            const cell = document.createElement("td");
            cell.textContent = String(value);
            row.append(cell);
          });
          body.append(row);
        });
        empty.hidden = candidates.length > 0;
      } catch (error) {
        summary.textContent = "후보 종목을 불러오지 못했습니다.";
        empty.hidden = false;
      }
    }

    topStocksButton.addEventListener("click", openTopStocksModal);
    byId("top-stocks-modal-close").addEventListener("click", closeTopStocksModal);
    topStocksOverlay.addEventListener("click", (event) => { if (event.target === topStocksOverlay) closeTopStocksModal(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeTopStocksModal(); });

    refreshAll();

    // 시세 패널 주기 갱신 (quotes-data.json은 fetch-quotes.py 크론이 1분마다 갱신)
    setInterval(() => { renderQuotes(); }, 60000);

    // 자동 갱신 제거: 새로고침 버튼(수동)만으로 갱신. 백엔드는 3분 간격 크론이 갱신.
  })();
  </script>
</body>
</html>