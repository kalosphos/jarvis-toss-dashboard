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

const CONTROL_FILE = __DIR__ . '/.control/trade-control.json';

function public_state(array $state): array
{
    return [
        'enabled'    => $state['enabled'],
        'updated_at' => $state['updated_at'],
    ];
}

function read_control(string $path): array
{
    if (!is_file($path)) {
        return ['enabled' => false, 'updated_at' => null];
    }

    $raw   = file_get_contents($path);
    $state = $raw === false ? null : json_decode($raw, true);
    if (!is_array($state)
        || !array_key_exists('enabled', $state)
        || !is_bool($state['enabled'])
        || (isset($state['updated_at']) && !is_string($state['updated_at']))) {
        throw new RuntimeException('invalid control state');
    }

    return [
        'enabled'    => $state['enabled'],
        'updated_at' => $state['updated_at'] ?? null,
    ];
}

function write_control(string $path, bool $enabled): array
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

    $state = [
        'enabled'    => $enabled,
        'updated_at' => gmdate('c'),
    ];
    $json = json_encode($state, JSON_UNESCAPED_SLASHES);
    if ($json === false) {
        throw new RuntimeException('cannot encode control state');
    }

    $temporary = tempnam($directory, '.trade-control.');
    if ($temporary === false) {
        throw new RuntimeException('cannot create temporary control file');
    }

    try {
        if (is_writable($temporary)) {
            @chmod($temporary, 0644);
        }
        if (file_put_contents($temporary, $json . "\n", LOCK_EX) === false) {
            throw new RuntimeException('cannot write temporary control state');
        }
        if (!rename($temporary, $path)) {
            throw new RuntimeException('cannot replace control state');
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
    $directory         = sys_get_temp_dir() . '/dashboard-control-selftest-' . bin2hex(random_bytes(8));
    $createdDirectory  = $directory . '/created';
    $existingDirectory = $directory . '/existing';
    $nonWritableDirectory = $directory . '/non-writable';
    $createdPath   = $createdDirectory . '/trade-control.json';
    $path          = $existingDirectory . '/trade-control.json';
    $nonWritablePath = $nonWritableDirectory . '/trade-control.json';
    try {
        if (!mkdir($directory, 0700)) {
            throw new RuntimeException('temporary directory setup failed');
        }
        if (read_control($createdPath)['enabled'] !== false) {
            throw new RuntimeException('missing state must default OFF');
        }
        write_control($createdPath, true);
        if (read_control($createdPath)['enabled'] !== true) {
            throw new RuntimeException('created-directory ON round-trip failed');
        }
        write_control($createdPath, false);
        if (read_control($createdPath)['enabled'] !== false) {
            throw new RuntimeException('OFF round-trip failed');
        }

        if (!mkdir($existingDirectory, 0755) || !chmod($existingDirectory, 0755)) {
            throw new RuntimeException('existing directory setup failed');
        }
        write_control($path, true);
        if (read_control($path)['enabled'] !== true) {
            throw new RuntimeException('existing-directory ON round-trip failed');
        }
        write_control($path, false);
        if (read_control($path)['enabled'] !== false) {
            throw new RuntimeException('existing-directory OFF round-trip failed');
        }
        if ((fileperms($existingDirectory) & 0777) !== 0755) {
            throw new RuntimeException('existing directory mode was changed');
        }
        if ((fileperms($path) & 0777) !== 0644 || (fileperms($createdPath) & 0777) !== 0644) {
            throw new RuntimeException('control state mode was not 0644');
        }

        if (!mkdir($nonWritableDirectory, 0555) || !chmod($nonWritableDirectory, 0555)) {
            throw new RuntimeException('non-writable directory setup failed');
        }
        if (!is_writable($nonWritableDirectory)) {
            try {
                write_control($nonWritablePath, true);
                throw new RuntimeException('non-writable directory was accepted');
            } catch (RuntimeException $error) {
                if ($error->getMessage() === 'non-writable directory was accepted') {
                    throw $error;
                }
            }
        }

        file_put_contents($path, "{broken\n");
        try {
            read_control($path);
            throw new RuntimeException('invalid JSON was accepted');
        } catch (RuntimeException $error) {
            if ($error->getMessage() === 'invalid JSON was accepted') {
                throw $error;
            }
        }

        $_SERVER = [
            'HTTP_SEC_FETCH_SITE' => 'same-origin',
            'HTTP_HOST'           => 'dashboard.example.test',
            'HTTP_ORIGIN'         => 'https://dashboard.example.test',
        ];
        if (!same_origin_request()) {
            throw new RuntimeException('HTTPS proxy scheme mismatch was rejected');
        }
        $_SERVER['HTTP_ORIGIN'] = 'https://attacker.example.test';
        if (same_origin_request()) {
            throw new RuntimeException('cross-host origin was accepted');
        }
        $_SERVER['HTTP_HOST']   = 'dashboard.example.test:8443';
        $_SERVER['HTTP_ORIGIN'] = 'https://dashboard.example.test:8443';
        if (!same_origin_request()) {
            throw new RuntimeException('matching explicit port was rejected');
        }
        $_SERVER['HTTP_ORIGIN'] = 'https://dashboard.example.test';
        if (same_origin_request()) {
            throw new RuntimeException('cross-port origin was accepted');
        }
        fwrite(STDOUT, "control.php self-test: OK\n");
        return 0;
    } catch (Throwable $error) {
        fwrite(STDERR, "control.php self-test: FAILED: " . $error->getMessage() . "\n");
        return 1;
    } finally {
        foreach ([$path, $createdPath, $nonWritablePath] as $controlPath) {
            if (is_file($controlPath)) {
                @unlink($controlPath);
            }
        }
        foreach ([$nonWritableDirectory, $existingDirectory, $createdDirectory, $directory] as $controlDirectory) {
            if (is_dir($controlDirectory)) {
                @chmod($controlDirectory, 0700);
                @rmdir($controlDirectory);
            }
        }
    }
}

if (PHP_SAPI === 'cli') {
    if ($argc === 2 && $argv[1] === '--self-test') {
        exit(self_test());
    }
    fwrite(STDERR, "Usage: php control.php --self-test\n");
    exit(2);
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';
try {
    if ($method === 'GET') {
        respond(200, public_state(read_control(CONTROL_FILE)));
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

    $raw  = file_get_contents('php://input', false, null, 0, 1025);
    $body = $raw === false ? null : json_decode($raw, true);
    if (!is_array($body)
        || array_keys($body) !== ['enabled']
        || !is_bool($body['enabled'])) {
        respond(400, ['error' => 'JSON body must be {"enabled": boolean}']);
        exit;
    }

    respond(200, public_state(write_control(CONTROL_FILE, $body['enabled'])));
} catch (Throwable $error) {
    error_log('dashboard control error: ' . $error->getMessage());
    respond(500, ['error' => 'control state unavailable']);
}
