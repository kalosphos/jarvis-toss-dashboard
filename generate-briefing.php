<?php
declare(strict_types=1);

/**
 * 브리핑 재생성 진입점
 *
 * 인증된 사용자의 요청으로만 jarvis_daily_briefing.py를 실행해
 * ai-daily-briefing.json + dashboard-data.json의 ai_briefing을 갱신한다.
 *
 * GET  /toss/generate-briefing.php  ->  실행 후 결과 JSON 반환
 * POST 같은 경로                       ->  GET과 동일하게 처리
 *
 * 실행 실패 시 500 + error, 성공 시 200 + generated_at/summary
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

// 동일 출처 확인(control.php와 동일 정책)
function same_origin_request(): bool
{
    if (isset($_SERVER['HTTP_SEC_FETCH_SITE'])
        && $_SERVER['HTTP_SEC_FETCH_SITE'] !== 'same-origin') {
        return false;
    }

    $source = $_SERVER['HTTP_ORIGIN'] ?? $_SERVER['HTTP_REFERER'] ?? '';
    $hostHeader = $_SERVER['HTTP_HOST'] ?? '';
    if ($source === '' || $hostHeader === '') {
        return false;
    }

    $sourceParts = parse_url($source);
    $expectedParts = parse_url('//' . $hostHeader);
    if (!is_array($sourceParts) || !is_array($expectedParts)) {
        return false;
    }

    $sourceScheme = strtolower((string) ($sourceParts['scheme'] ?? ''));
    $sourceHost = strtolower((string) ($sourceParts['host'] ?? ''));
    $expectedHost = strtolower((string) ($expectedParts['host'] ?? ''));
    $sourcePort = (int) ($sourceParts['port'] ?? ($sourceScheme === 'https' ? 443 : 80));
    $expectedPort = isset($expectedParts['port']) ? (int) ($expectedParts['port']) : null;

    return ($sourceScheme === 'http' || $sourceScheme === 'https')
        && $sourceHost !== ''
        && hash_equals($expectedHost, $sourceHost)
        && ($expectedPort === null || $sourcePort === $expectedPort);
}

if (!same_origin_request()) {
    http_response_code(403);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'same-origin request required'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 실행 환경
$root = __DIR__;
$script = $root . '/jarvis_daily_briefing.py';
if (!is_file($script)) {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'briefing generator not found'], JSON_UNESCAPED_UNICODE);
    exit;
}

// Python으로 직접 실행 (NAS 독립 실행, Mac mount 불필요)
$env = $_ENV;
$env['JARVIS_TOSS_ROOT'] = $root;
putenv('JARVIS_TOSS_ROOT=' . $root);

$cmd = ['python3', $script];
$proc = null;
$stdout = '';
$stderr = '';
try {
    $proc = proc_open(
        $cmd,
        [
            1 => ['pipe', 'w'],
            2 => ['pipe', 'w'],
        ],
        $pipes,
        $root,
        $env
    );
    if (!is_resource($proc)) {
        throw new RuntimeException('proc_open failed');
    }
    $stdout = stream_get_contents($pipes[1] ?? null);
    $stderr = stream_get_contents($pipes[2] ?? null);
    $exit = proc_close($proc);
} catch (Throwable $e) {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'briefing generation failed', 'detail' => $e->getMessage()], JSON_UNESCAPED_UNICODE);
    exit;
}

if ($exit !== 0) {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode([
        'error' => 'briefing generation failed',
        'exit_code' => $exit,
        'stdout' => trim($stdout),
        'stderr' => trim($stderr),
    ], JSON_UNESCAPED_UNICODE);
    exit;
}

// 표준출력 마지막 줄에서 JSON 파싱 시도
$lines = array_filter(explode("\n", trim($stdout)), fn($l) => $l !== '');
$result = ['generated_at' => null, 'summary' => null, 'raw' => trim($stdout)];
foreach (array_reverse($lines) as $line) {
    $line = trim($line);
    if ($line === '') {
        continue;
    }
    try {
        $parsed = json_decode($line, true, 512, JSON_THROW_ON_ERROR);
        if (is_array($parsed)) {
            $result['generated_at'] = $parsed['generated_at'] ?? $result['generated_at'];
            $result['summary'] = $parsed['summary'] ?? $parsed['macro_summary'] ?? $result['summary'];
            break;
        }
    } catch (Throwable $e) {
        // 파싱 실패하면 다음 줄 시도
        continue;
    }
}

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
echo json_encode($result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
