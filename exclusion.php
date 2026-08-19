<?php
declare(strict_types=1);

$GLOBALS['DASHBOARD_GATE_LIB'] = true;
require_once __DIR__ . '/toss-auth.php';

// 쿠키 기반 접근 제어: 유효한 toss_session 쿠키가 없으면 401
// (PHP-FPM 요청일 때만 실행, CLI self-test는 bypass)
if (PHP_SAPI !== 'cli') {
    $username = validateSessionCookie();
    if ($username === null) {
        http_response_code(401);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['error' => 'Unauthorized'], JSON_UNESCAPED_UNICODE);
        exit;
    }
}

const EXCLUSION_FILE = __DIR__ . '/.control/exclusions.json';

function public_state(array $state): array
{
    return [
        'symbols'    => $state['symbols'],
        'updated_at' => $state['updated_at'],
    ];
}

function normalize_symbol(mixed $symbol): ?string
{
    if (!is_string($symbol) || preg_match('/^[A-Z0-9]{1,12}$/i', $symbol) !== 1) {
        return null;
    }

    return strtoupper($symbol);
}

function parse_request_body(mixed $body): ?array
{
    if (!is_array($body)
        || count($body) !== 2
        || !array_key_exists('action', $body)
        || !array_key_exists('symbol', $body)
        || !is_string($body['action'])
        || !in_array($body['action'], ['add', 'remove'], true)) {
        return null;
    }

    $symbol = normalize_symbol($body['symbol']);
    return $symbol === null ? null : ['action' => $body['action'], 'symbol' => $symbol];
}

function read_control(string $path): array
{
    if (!is_file($path)) {
        return ['symbols' => [], 'updated_at' => null];
    }

    $raw   = file_get_contents($path);
    $state = $raw === false ? null : json_decode($raw, true);
    if (!is_array($state) || !isset($state['symbols']) || !is_array($state['symbols'])) {
        return ['symbols' => [], 'updated_at' => null];
    }

    $symbols = [];
    foreach ($state['symbols'] as $symbol) {
        $normalized = normalize_symbol($symbol);
        if ($normalized === null) {
            return ['symbols' => [], 'updated_at' => null];
        }
        $symbols[] = $normalized;
    }
    $symbols = array_values(array_unique($symbols));
    sort($symbols, SORT_STRING);

    return [
        'symbols'    => $symbols,
        'updated_at' => isset($state['updated_at']) && is_string($state['updated_at']) ? $state['updated_at'] : null,
    ];
}

function write_control(string $path, array $symbols): array
{
    $directory = dirname($path);
    $createdDirectory = false;
    if (!is_dir($directory)) {
        if (!mkdir($directory, 0777, true)) {
            throw new RuntimeException('cannot create control directory');
        }
        $createdDirectory = true;
    }

    if ($createdDirectory) {
        if (!@chmod($directory, 0777) && !is_writable($directory)) {
            throw new RuntimeException('cannot prepare control directory');
        }
    } elseif (!is_writable($directory)) {
        throw new RuntimeException('control directory is not writable');
    }

    $normalizedSymbols = [];
    foreach ($symbols as $symbol) {
        $normalized = normalize_symbol($symbol);
        if ($normalized === null) {
            throw new RuntimeException('invalid exclusion symbol');
        }
        $normalizedSymbols[] = $normalized;
    }
    $symbols = array_values(array_unique($normalizedSymbols));
    sort($symbols, SORT_STRING);
    $state = ['symbols' => $symbols, 'updated_at' => gmdate('c')];
    $json  = json_encode($state, JSON_UNESCAPED_SLASHES);
    if ($json === false) {
        throw new RuntimeException('cannot encode exclusion state');
    }

    $temporary = tempnam($directory, '.exclusions.');
    if ($temporary === false) {
        throw new RuntimeException('cannot create temporary exclusion file');
    }

    try {
        if (is_writable($temporary)) {
            @chmod($temporary, 0644);
        }
        if (file_put_contents($temporary, $json . "\n", LOCK_EX) === false) {
            throw new RuntimeException('cannot write temporary exclusion state');
        }
        if (!rename($temporary, $path)) {
            throw new RuntimeException('cannot replace exclusion state');
        }
        if (is_writable($path)) {
            @chmod($path, 0644);
        }
    } finally {
        if (is_file($temporary)) {
            @unlink($temporary);
        }
    }

    return $state;
}

function same_origin_request(): bool
{
    if (isset($_SERVER['HTTP_SEC_FETCH_SITE']) && $_SERVER['HTTP_SEC_FETCH_SITE'] !== 'same-origin') {
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
    $sourceHost   = strtolower((string) ($sourceParts['host'] ?? ''));
    $expectedHost = strtolower((string) ($expectedParts['host'] ?? ''));
    $sourcePort   = (int) ($sourceParts['port'] ?? ($sourceScheme === 'https' ? 443 : 80));
    $expectedPort = isset($expectedParts['port']) ? (int) $expectedParts['port'] : null;

    return ($sourceScheme === 'http' || $sourceScheme === 'https')
        && $sourceHost !== ''
        && hash_equals($expectedHost, $sourceHost)
        && ($expectedPort === null || $sourcePort === $expectedPort);
}

function respond(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
}

function self_test(): int
{
    $directory    = sys_get_temp_dir() . '/dashboard-exclusion-selftest-' . bin2hex(random_bytes(8));
    $path         = $directory . '/created/exclusions.json';
    $corruptPath  = $directory . '/corrupt/exclusions.json';
    try {
        if (!mkdir($directory, 0700) || !mkdir(dirname($corruptPath), 0700)) {
            throw new RuntimeException('temporary directory setup failed');
        }
        if (read_control($path) !== ['symbols' => [], 'updated_at' => null]) {
            throw new RuntimeException('missing state must be empty');
        }
        file_put_contents($corruptPath, "{broken\n");
        if (read_control($corruptPath) !== ['symbols' => [], 'updated_at' => null]) {
            throw new RuntimeException('corrupt state must be empty');
        }

        $state = write_control($path, ['msft', 'AAPL', 'MSFT']);
        if ($state['symbols'] !== ['AAPL', 'MSFT'] || read_control($path)['symbols'] !== ['AAPL', 'MSFT']) {
            throw new RuntimeException('add round-trip failed');
        }
        $state = write_control($path, array_values(array_diff(read_control($path)['symbols'], ['MSFT'])));
        if ($state['symbols'] !== ['AAPL'] || read_control($path)['symbols'] !== ['AAPL']) {
            throw new RuntimeException('remove round-trip failed');
        }
        if (parse_request_body(['action' => 'replace', 'symbol' => 'AAPL']) !== null) {
            throw new RuntimeException('invalid action was accepted');
        }
        if (parse_request_body(['action' => 'add', 'symbol' => 'BAD-SYMBOL']) !== null) {
            throw new RuntimeException('invalid symbol was accepted');
        }

        $_SERVER = ['HTTP_SEC_FETCH_SITE' => 'same-origin', 'HTTP_HOST' => 'dashboard.example.test', 'HTTP_ORIGIN' => 'https://dashboard.example.test'];
        if (!same_origin_request()) {
            throw new RuntimeException('same-origin request was rejected');
        }
        $_SERVER['HTTP_ORIGIN'] = 'https://attacker.example.test';
        if (same_origin_request()) {
            throw new RuntimeException('cross-origin request was accepted');
        }
        fwrite(STDOUT, "exclusion.php self-test: OK\n");
        return 0;
    } catch (Throwable $error) {
        fwrite(STDERR, "exclusion.php self-test: FAILED: " . $error->getMessage() . "\n");
        return 1;
    } finally {
        foreach ([$path, $corruptPath] as $statePath) {
            if (is_file($statePath)) {
                @unlink($statePath);
            }
        }
        foreach ([dirname($path), dirname($corruptPath), $directory] as $stateDirectory) {
            if (is_dir($stateDirectory)) {
                @chmod($stateDirectory, 0700);
                @rmdir($stateDirectory);
            }
        }
    }
}

if (PHP_SAPI === 'cli') {
    if ($argc === 2 && $argv[1] === '--self-test') {
        exit(self_test());
    }
    fwrite(STDERR, "Usage: php exclusion.php --self-test\n");
    exit(2);
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';
try {
    if ($method === 'GET') {
        respond(200, public_state(read_control(EXCLUSION_FILE)));
        exit;
    }
    if ($method !== 'POST') {
        header('Allow: GET, POST');
        respond(405, ['error' => 'method not allowed']);
        exit;
    }
    if (!same_origin_request()) {
        respond(403, ['error' => 'same-origin request required']);
        exit;
    }
    $contentType = strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '')[0]));
    if ($contentType !== 'application/json') {
        respond(415, ['error' => 'application/json required']);
        exit;
    }
    if ((int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > 1024) {
        respond(413, ['error' => 'request body too large']);
        exit;
    }

    $raw       = file_get_contents('php://input', false, null, 0, 1025);
    $request   = parse_request_body($raw === false ? null : json_decode($raw, true));
    if ($request === null) {
        respond(400, ['error' => 'JSON body must be {"action":"add"|"remove","symbol":"A-Z0-9"}']);
        exit;
    }

    $state   = read_control(EXCLUSION_FILE);
    $symbols = $state['symbols'];
    if ($request['action'] === 'add' && !in_array($request['symbol'], $symbols, true)) {
        $symbols[] = $request['symbol'];
    }
    if ($request['action'] === 'remove') {
        $symbols = array_values(array_filter($symbols, static fn (string $item): bool => $item !== $request['symbol']));
    }
    respond(200, public_state(write_control(EXCLUSION_FILE, $symbols)));
} catch (Throwable $error) {
    error_log('dashboard exclusion error: ' . $error->getMessage());
    respond(500, ['error' => 'exclusion state unavailable']);
}
