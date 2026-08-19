<?php
declare(strict_types=1);

/**
 * 대시보드 데이터 프록시
 *
 * toss_session 쿠키를 검증한 사용자에게만 데이터 JSON을 제공합니다.
 * GET 파라미터: f=파일명 (예: ?f=dashboard-data.json)
 *
 * nginx conf에서 /toss/*.json 요청을 이 파일로 내부 라우팅합니다.
 * 허용된 파일만 읽을 수 있고, 경로 탐색(path traversal)을 방어합니다.
 */

$GLOBALS['DASHBOARD_GATE_LIB'] = true;
require_once __DIR__ . '/toss-auth.php';

// 쿠키 검증
$username = validateSessionCookie();
if ($username === null) {
    http_response_code(401);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'Unauthorized'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 요청 파일명
$filename = $_GET['f'] ?? '';
if ($filename === '') {
    http_response_code(400);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => '파일명이 필요합니다. ?f=파일명'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 경로 탐색 방어: basename만 사용
$basename = basename($filename);
if ($basename !== $filename || strpos($filename, '.') === false) {
    http_response_code(400);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => '잘못된 파일명'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 허용된 데이터 파일 목록
$allowedFiles = [
    'dashboard-data.json',
    'auto-trading-status.json',
    'ai-daily-briefing.json',
    'daily-trade-plan.json',
    'dashboard-history.json',
    'jarvis-atm-status.json',
    'auto-execution-state.json',
];

if (!in_array($basename, $allowedFiles, true)) {
    http_response_code(404);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => '허용되지 않은 파일'], JSON_UNESCAPED_UNICODE);
    exit;
}

$filePath = __DIR__ . '/' . $basename;
if (!is_file($filePath)) {
    http_response_code(404);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => '파일을 찾을 수 없음'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 파일 읽기 → 출력
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
readfile($filePath);
exit;
