<?php
/**
 * toss-auth.php — 세션 쿠키 기반 인증 프록시 (NAS /toss/)
 *
 * NAS 원본(248줄)의 Basic Auth 로그인·로그아웃·세션 확인 라우트를 보존하고,
 * WebAuthn(Face ID/Touch ID) 로그인 라우트 4개를 추가한 통합본이다.
 *
 * 라우트:
 *   POST /toss/toss-auth.php                              → Basic Auth 로그인 (기존 유지)
 *   GET  /toss/toss-auth.php?action=webauthn-register-options&username=xxx
 *                                                         → WebAuthn 등록 옵션 (JSON)
 *   POST /toss/toss-auth.php?action=webauthn-register-verify
 *                                                         → WebAuthn 등록 검증 (JSON 본문)
 *   GET  /toss/toss-auth.php?action=webauthn-auth-options → WebAuthn 인증 옵션 (JSON)
 *   POST /toss/toss-auth.php?action=webauthn-auth-verify  → WebAuthn 인증 검증 + 세션 쿠키 (JSON 본문)
 *
 * WebAuthn 헬퍼: /toss/webauthn.php (같은 디렉토리, require_once로 로드)
 */

declare(strict_types=1);

// ─── Cookie configuration ────────────────────────────────────────
const COOKIE_NAME       = 'toss_session';
const COOKIE_LIFETIME   = 2592000; // 30 days
const COOKIE_PATH       = '/toss';
const COOKIE_DOMAIN     = '';
const COOKIE_SECURE     = false; // Allow HTTP for local network
const COOKIE_HTTPONLY   = true;
const COOKIE_SAMESITE   = 'Lax';

// Session key storage path (same-directory .control, user-writable)
const SESSION_KEY_PATH  = __DIR__ . '/.control/session_key.dat';

/**
 * Generate or load 256-bit session signing key
 */
function getSessionKey(): string {
    if (file_exists(SESSION_KEY_PATH)) {
        $key = file_get_contents(SESSION_KEY_PATH);
        if ($key && strlen($key) >= 32) {
            return $key;
        }
    }

    // Generate new key
    $key = random_bytes(32);

    // Store in SMB mount
    $dir = dirname(SESSION_KEY_PATH);
    if (!is_dir($dir)) {
        mkdir($dir, 0700, true);
    }

    file_put_contents(SESSION_KEY_PATH, $key, LOCK_EX);
    chmod(SESSION_KEY_PATH, 0600);

    return $key;
}

/**
 * Create signed session cookie
 */
function createSessionCookie(string $username): bool {
    $key = getSessionKey();
    $payload = base64_encode(json_encode([
        'u' => $username,
        'i' => time(),
        'e' => time() + COOKIE_LIFETIME,
    ]));

    // HMAC-SHA256 signature
    $signature = hash_hmac('sha256', $payload, $key);
    $signed = $payload . '.' . $signature;

    return setcookie(COOKIE_NAME, $signed, [
        'expires'  => time() + COOKIE_LIFETIME,
        'path'     => COOKIE_PATH,
        'domain'   => COOKIE_DOMAIN,
        'secure'   => COOKIE_SECURE,
        'httponly' => COOKIE_HTTPONLY,
        'samesite' => COOKIE_SAMESITE,
    ]);
}

/**
 * Validate session cookie
 */
function validateSessionCookie(): ?string {
    if (!isset($_COOKIE[COOKIE_NAME])) {
        return null;
    }

    $signed = $_COOKIE[COOKIE_NAME];
    $parts = explode('.', $signed, 2);

    if (count($parts) !== 2) {
        return null;
    }

    [$payload, $signature] = $parts;

    // Verify signature
    $expected = hash_hmac('sha256', $payload, getSessionKey());
    if (!hash_equals($expected, $signature)) {
        return null;
    }

    // Decode payload
    $data = json_decode(base64_decode($payload), true);
    if (!$data || !isset($data['u'], $data['i'], $data['e'])) {
        return null;
    }

    // Check expiry
    if ($data['e'] < time()) {
        return null;
    }

    return $data['u'];
}

/**
 * Delete session cookie
 */
function deleteSessionCookie(): void {
    setcookie(COOKIE_NAME, '', [
        'expires'  => time() - 3600,
        'path'     => COOKIE_PATH,
        'domain'   => COOKIE_DOMAIN,
        'secure'   => COOKIE_SECURE,
        'httponly' => COOKIE_HTTPONLY,
        'samesite' => COOKIE_SAMESITE,
    ]);
}

/**
 * Handle Basic Auth login request
 */
function handleLogin(): void {
    header('Content-Type: application/json; charset=utf-8');

    // Require POST
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        http_response_code(405);
        echo json_encode(['error' => 'Method not allowed']);
        return;
    }

    // Get credentials from headers (Basic Auth)
    $authHeader = $_SERVER['HTTP_AUTHORIZATION'] ?? '';

    if (!preg_match('/Basic\\s+(.+)$/i', $authHeader, $matches)) {
        http_response_code(401);
        header('WWW-Authenticate: Basic realm="toss"');
        echo json_encode(['error' => 'Unauthorized']);
        return;
    }

    // Decode credentials
    $decoded = base64_decode($matches[1]);
    if (!$decoded || strpos($decoded, ':') === false) {
        http_response_code(401);
        header('WWW-Authenticate: Basic realm="toss"');
        echo json_encode(['error' => 'Invalid credentials']);
        return;
    }

    [$username, $password] = explode(':', $decoded, 2);

    if (empty($username) || empty($password)) {
        http_response_code(401);
        header('WWW-Authenticate: Basic realm="toss"');
        echo json_encode(['error' => 'Empty credentials']);
        return;
    }

    // Issue session cookie (credentials verified by nginx Basic Auth)
    if (!createSessionCookie($username)) {
        http_response_code(500);
        echo json_encode(['error' => 'Failed to create session']);
        return;
    }

    echo json_encode([
        'success'  => true,
        'username' => $username,
        'expires'  => date('Y-m-d H:i:s', time() + COOKIE_LIFETIME),
        'message'  => 'Login successful. Cookie valid for 30 days.',
    ]);
}

/**
 * Handle logout request
 */
function handleLogout(): void {
    header('Content-Type: application/json; charset=utf-8');

    deleteSessionCookie();

    echo json_encode([
        'success' => true,
        'message' => 'Logged out. Cookie deleted.',
    ]);
}

/**
 * Handle session check request
 */
function handleCheck(): void {
    header('Content-Type: application/json; charset=utf-8');

    $username = validateSessionCookie();

    if ($username) {
        echo json_encode([
            'authenticated' => true,
            'username'      => $username,
        ]);
    } else {
        http_response_code(401);
        echo json_encode([
            'authenticated' => false,
        ]);
    }
}

// ─── WebAuthn 헬퍼 로드 ──────────────────────────────────────────
//
// 같은 디렉토리에 webauthn.php가 있을 때만 로드한다.
// (NAS 배포에서는 /var/services/web/toss/webauthn.php)
//
if (basename($_SERVER['SCRIPT_FILENAME'] ?? '') === 'toss-auth.php') {
    $webauthnHelper = __DIR__ . '/webauthn.php';
    if (file_exists($webauthnHelper)) {
        require_once $webauthnHelper;
    }
}
// ─────────────────────────────────────────────────────────────────

// ─── WebAuthn 라우트 핸들러 ──────────────────────────────────────

function handleWebAuthnRegisterOptions(): void {
    header('Content-Type: application/json; charset=utf-8');

    if (!function_exists('webauthn_get_register_options')) {
        http_response_code(500);
        echo json_encode(['error' => 'WebAuthn 헬퍼를 로드하지 못했습니다.']);
        return;
    }

    $username = $_GET['username'] ?? $_POST['username'] ?? '';
    if ($username === '') {
        http_response_code(400);
        echo json_encode(['error' => 'username이 필요합니다.']);
        return;
    }

    try {
        $opts = webauthn_get_register_options($username);
        echo json_encode($opts);
    } catch (Exception $e) {
        http_response_code(500);
        echo json_encode(['error' => 'WebAuthn 등록 옵션 생성 실패: ' . $e->getMessage()]);
    }
}

function handleWebAuthnRegisterVerify(): void {
    header('Content-Type: application/json; charset=utf-8');

    if (!function_exists('webauthn_verify_registration')) {
        http_response_code(500);
        echo json_encode(['error' => 'WebAuthn 헬퍼를 로드하지 못했습니다.']);
        return;
    }

    $input = json_decode(file_get_contents('php://input'), true);
    if (!is_array($input)) {
        http_response_code(400);
        echo json_encode(['error' => '요청 본문이 유효하지 않습니다.']);
        return;
    }

    $username = $_POST['username'] ?? $input['username'] ?? '';
    if ($username === '') {
        http_response_code(400);
        echo json_encode(['error' => 'username이 필요합니다.']);
        return;
    }

    $result = webauthn_verify_registration($input, $username);
    if ($result['ok']) {
        echo json_encode([
            'ok'          => true,
            'credentialId' => $result['credentialId'],
            'username'    => $result['username'],
        ]);
    } else {
        http_response_code(400);
        echo json_encode($result);
    }
}

function handleWebAuthnAuthOptions(): void {
    header('Content-Type: application/json; charset=utf-8');

    if (!function_exists('webauthn_get_auth_options')) {
        http_response_code(500);
        echo json_encode(['error' => 'WebAuthn 헬퍼를 로드하지 못했습니다.']);
        return;
    }

    try {
        $opts = webauthn_get_auth_options();
        if (isset($opts['error'])) {
            http_response_code(404);
            echo json_encode($opts);
            return;
        }
        echo json_encode($opts);
    } catch (Exception $e) {
        http_response_code(500);
        echo json_encode(['error' => 'WebAuthn 인증 옵션 생성 실패: ' . $e->getMessage()]);
    }
}

function handleWebAuthnAuthVerify(): void {
    header('Content-Type: application/json; charset=utf-8');

    if (!function_exists('webauthn_verify_authentication')) {
        http_response_code(500);
        echo json_encode(['error' => 'WebAuthn 헬퍼를 로드하지 못했습니다.']);
        return;
    }

    $input = json_decode(file_get_contents('php://input'), true);
    if (!is_array($input) || empty($input)) {
        http_response_code(400);
        echo json_encode(['error' => '요청 본문이 없습니다.']);
        return;
    }

    $result = webauthn_verify_authentication($input);
    if ($result['ok']) {
        if (!function_exists('webauthn_create_session_cookie')
            || !webauthn_create_session_cookie($result['username'])) {
            http_response_code(500);
            echo json_encode(['error' => '세션 쿠키 발급 실패']);
            return;
        }
        echo json_encode([
            'ok'          => true,
            'username'    => $result['username'],
            'redirectUrl' => '/toss/',
        ]);
    } else {
        http_response_code(401);
        echo json_encode($result);
    }
}
// ─────────────────────────────────────────────────────────────────

/**
 * Main dispatcher
 */
function dispatch(): void {
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH);

    // WebAuthn 라우트: action 쿼리 파라미터로 구분
    if (str_contains($path, 'toss-auth.php')) {
        $action = $_GET['action'] ?? '';

        if ($action === 'webauthn-register-options') {
            handleWebAuthnRegisterOptions();
            return;
        }
        if ($action === 'webauthn-register-verify') {
            handleWebAuthnRegisterVerify();
            return;
        }
        if ($action === 'webauthn-auth-options') {
            handleWebAuthnAuthOptions();
            return;
        }
        if ($action === 'webauthn-auth-verify') {
            handleWebAuthnAuthVerify();
            return;
        }
    }

    // 기존 라우트
    if ($path === '/toss/toss-auth.php' || $path === '/toss/toss-auth.php/') {
        handleLogin();
    } elseif ($path === '/toss/logout.php' || $path === '/toss/logout.php/') {
        handleLogout();
    } elseif ($path === '/toss/auth-check.php' || $path === '/toss/auth-check.php/') {
        handleCheck();
    } else {
        // Default: return auth status
        $username = validateSessionCookie();
        header('Content-Type: application/json; charset=utf-8');

        if ($username) {
            echo json_encode([
                'authenticated' => true,
                'username'      => $username,
            ]);
        } else {
            http_response_code(401);
            echo json_encode([
                'authenticated' => false,
            ]);
        }
    }
}

// Execute (skip when included as aGate library by index.php/data.php)
if (PHP_SAPI !== 'cli' && (PHP_SAPI === 'fpm-fcgi' || PHP_SAPI === 'cgi-fcgi' || PHP_SAPI === 'cli-server') && (!isset($GLOBALS['DASHBOARD_GATE_LIB']) || !$GLOBALS['DASHBOARD_GATE_LIB'])) {
    dispatch();
}
