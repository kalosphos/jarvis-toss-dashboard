<?php
/**
 * WebAuthn Face ID / Touch ID 로그인 헬퍼 — ES384(P-384) 기반
 *
 * NAS PHP 8.1 + OpenSSL 3.0.9 환경에서 동작 확인됨
 *   ES256는 보안레벨 제한으로 불가, ES384는 정상 동작
 *
 * 단독 실행:
 *   GET  /toss/webauthn.php?action=register-options&username=xxx
 *   POST /toss/webauthn.php?action=register-verify   (JSON 본문 = credential response)
 *   GET  /toss/webauthn.php?action=auth-options
 *   POST /toss/webauthn.php?action=auth-verify       (JSON 본문 = credential response)
 *
 * toss-auth.php에서 include 후 webauthn_dispatch() 호출도 가능.
 *
 * 저장 위치:
 *   /web/toss/.control/webauthn-credentials.json  (등록된 자격증명)
 *   /web/toss/.control/webauthn-challenge.dat     (발급된 챌린지, 인증 후 삭제)
 */

declare(strict_types=1);

// ─── WebAuthn 설정 ───────────────────────────────────────────────
define('WEBAUTHN_RPID', 'kwangho79.synology.me');
define('WEBAUTHN_RP_NAME', '자비스 대시보드');
define('WEBAUTHN_ALG', -35); // COSE ES384 (P-384)

define('WEBAUTHN_CREDENTIALS_FILE', __DIR__ . '/.control/webauthn-credentials.json');
define('WEBAUTHN_CHALLENGE_FILE', __DIR__ . '/.control/webauthn-challenge.dat');
define('WEBAUTHN_ORIGIN', 'https://kwangho79.synology.me');
// ─────────────────────────────────────────────────────────────────

// ─── 세션 쿠키 발급 ──────────────────────────────────────────────
if (!function_exists('webauthn_create_session_cookie')) {
    function webauthn_create_session_cookie(string $username): bool {
        if (function_exists('createSessionCookie')) {
            return createSessionCookie($username);
        }
        // 폴백: toss-auth.php와 동일한 hmac 세션 쿠키 방식
        $key = random_bytes(32);
        $payload = base64_encode(json_encode([
            'u' => $username,
            'i' => time(),
            'e' => time() + 2592000,
        ]));
        $sig = hash_hmac('sha256', $payload, $key);
        $cookie_val = $payload . '.' . $sig;
        return setcookie('toss_session', $cookie_val, [
            'expires' => time() + 2592000,
            'path' => '/toss',
            'secure' => false,
            'httponly' => true,
            'samesite' => 'Lax',
        ]);
    }
}
// ─────────────────────────────────────────────────────────────────

// ─── 자격증명 저장/로드 ──────────────────────────────────────────
function webauthn_load_credentials(): array {
    if (!file_exists(WEBAUTHN_CREDENTIALS_FILE)) {
        return ['credentials' => []];
    }
    $s = file_get_contents(WEBAUTHN_CREDENTIALS_FILE);
    if ($s === false) return ['credentials' => []];
    $data = json_decode($s, true);
    if (!is_array($data)) return ['credentials' => []];
    return $data;
}

function webauthn_save_credentials(array $data): void {
    $dir = dirname(WEBAUTHN_CREDENTIALS_FILE);
    if (!is_dir($dir)) {
        if (!mkdir($dir, 0700, true)) {
            throw new RuntimeException('webauthn 자격증명 디렉토리 생성 실패: ' . $dir);
        }
    }
    if (file_put_contents(WEBAUTHN_CREDENTIALS_FILE, json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), LOCK_EX) === false) {
        throw new RuntimeException('webauthn 자격증명 저장 실패: ' . WEBAUTHN_CREDENTIALS_FILE);
    }
}
// ─────────────────────────────────────────────────────────────────

// ─── 챌린지 저장/로드/삭제 ──────────────────────────────────────
function webauthn_save_challenge(string $challenge): void {
    $dir = dirname(WEBAUTHN_CHALLENGE_FILE);
    if (!is_dir($dir)) {
        if (!mkdir($dir, 0700, true)) {
            throw new RuntimeException('webauthn 챌린지 디렉토리 생성 실패: ' . $dir);
        }
    }
    if (file_put_contents(WEBAUTHN_CHALLENGE_FILE, $challenge, LOCK_EX) === false) {
        throw new RuntimeException('webauthn 챌린지 저장 실패: ' . WEBAUTHN_CHALLENGE_FILE);
    }
}

function webauthn_load_challenge(): ?string {
    if (!file_exists(WEBAUTHN_CHALLENGE_FILE)) return null;
    $s = file_get_contents(WEBAUTHN_CHALLENGE_FILE);
    return $s === false ? null : $s;
}

function webauthn_clear_challenge(): void {
    if (file_exists(WEBAUTHN_CHALLENGE_FILE)) unlink(WEBAUTHN_CHALLENGE_FILE);
}
// ─────────────────────────────────────────────────────────────────

// ─── base64url 인코딩/디코딩 ────────────────────────────────────
function base64url_encode(string $data): string {
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}

function base64url_decode(string $data): string {
    $r = strlen($data) % 4;
    if ($r) $data .= str_repeat('=', 4 - $r);
    return base64_decode(strtr($data, '-_', '+/'));
}
// ─────────────────────────────────────────────────────────────────

// ─── 최소한의 CBOR 디코더 (WebAuthn attestationObject / COSE 키용) ──
//
// 파스칼 방식: 한 번에 하나의 CBOR 값을 읽어서 반환.
// 지원 major: 0(uint), 1(nint), 2(bstr), 3(text), 4(array), 5(map), 6(tag-스킵)
//
function cbor_read(string $data, int &$o): mixed {
    if ($o >= strlen($data)) {
        throw new RuntimeException('cbor: 범위 초과 (초기 바이트)');
    }
    $b0 = ord($data[$o++]);
    $major = ($b0 >> 5) & 7;
    $info = $b0 & 0x1f;

    switch ($major) {
        case 0: // unsigned integer
            return cbor_uint($info, $data, $o);
        case 1: // negative integer
            return -1 - cbor_uint($info, $data, $o);
        case 2: // byte string
            return cbor_bytes($info, $data, $o);
        case 3: // utf8 text string
            return cbor_text($info, $data, $o);
        case 4: // array
            return cbor_array($info, $data, $o);
        case 5: // map
            return cbor_map($info, $data, $o);
        case 6: // tag — 내부 값만 읽고 반환
            cbor_skip_tag_info($info, $data, $o);
            return cbor_read($data, $o);
        default:
            throw new RuntimeException('cbor: 미지원 major=' . $major);
    }
}

function cbor_uint(int $info, string $data, int &$o): int {
    if ($info < 24) return $info;
    if ($info === 24) {
        if ($o >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (uint extra)');
        return ord($data[$o++]);
    }
    if ($info === 25) {
        if ($o + 1 >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (uint 2bytes)');
        $v = ord($data[$o]) << 8 | ord($data[$o + 1]);
        $o += 2;
        return $v;
    }
    if ($info === 26) {
        if ($o + 3 >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (uint 4bytes)');
        $v = ord($data[$o]) << 24 | ord($data[$o + 1]) << 16 | ord($data[$o + 2]) << 8 | ord($data[$o + 3]);
        $o += 4;
        return $v;
    }
    throw new RuntimeException('cbor: 미지원 uint 크기 (info=' . $info . ')');
}

function cbor_bytes(int $info, string $data, int &$o): string {
    $len = cbor_len($info, $data, $o);
    if ($o + $len > strlen($data)) throw new RuntimeException('cbor: 범위 초과 (bstr 본문)');
    $result = substr($data, $o, $len);
    $o += $len;
    return $result;
}

function cbor_text(int $info, string $data, int &$o): string {
    $len = cbor_len($info, $data, $o);
    if ($o + $len > strlen($data)) throw new RuntimeException('cbor: 범위 초과 (text 본문)');
    $result = substr($data, $o, $len);
    $o += $len;
    return $result;
}

function cbor_array(int $info, string $data, int &$o): array {
    $count = cbor_len($info, $data, $o);
    $arr = [];
    for ($i = 0; $i < $count; $i++) {
        $arr[] = cbor_read($data, $o);
    }
    return $arr;
}

function cbor_map(int $info, string $data, int &$o): array {
    $count = cbor_len($info, $data, $o);
    $map = [];
    for ($i = 0; $i < $count; $i++) {
        $key = cbor_read($data, $o);
        $val = cbor_read($data, $o);
        $map[$key] = $val;
    }
    return $map;
}

function cbor_len(int $info, string $data, int &$o): int {
    if ($info < 24) return $info;
    if ($info === 24) {
        if ($o >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (len extra)');
        return ord($data[$o++]);
    }
    if ($info === 25) {
        if ($o + 1 >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (len 2bytes)');
        $v = ord($data[$o]) << 8 | ord($data[$o + 1]);
        $o += 2;
        return $v;
    }
    if ($info === 26) {
        if ($o + 3 >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (len 4bytes)');
        $v = ord($data[$o]) << 24 | ord($data[$o + 1]) << 16 | ord($data[$o + 2]) << 8 | ord($data[$o + 3]);
        $o += 4;
        return $v;
    }
    throw new RuntimeException('cbor: 미지원 길이 인코딩 (info=' . $info . ')');
}

function cbor_skip_tag_info(int $info, string $data, int &$o): void {
    if ($info < 24) {
        // 태그 번호는 $info 자체. 추가 바이트 없음.
        return;
    }
    if ($info === 24) {
        if ($o >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (tag extra)');
        $o++;
        return;
    }
    if ($info === 25) {
        if ($o + 1 >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (tag 2bytes)');
        $o += 2;
        return;
    }
    if ($info === 26) {
        if ($o + 3 >= strlen($data)) throw new RuntimeException('cbor: 범위 초과 (tag 4bytes)');
        $o += 4;
        return;
    }
    throw new RuntimeException('cbor: 미지원 태그 길이 (info=' . $info . ')');
}

function cbor_decode(string $data): mixed {
    $o = 0;
    return cbor_read($data, $o);
}
// ─────────────────────────────────────────────────────────────────

// ─── COSE EC2 공개키 → PEM (ES384 / P-384 전용) ────────────────
function cose_ec2_to_pem(string $cose_pubkey): string {
    $keymap = cbor_decode($cose_pubkey);

    // kty = 2 (EC2) 확인
    if (($keymap[3] ?? null) !== 2) {
        throw new RuntimeException('COSE 키가 EC2가 아님 (kty=' . var_export($keymap[3] ?? null, true) . ')');
    }

    $x = $keymap[-2] ?? null;
    $y = $keymap[-3] ?? null;
    if (!is_string($x) || !is_string($y)) {
        throw new RuntimeException('COSE EC2에 x/y가 없음 (x=' . var_export($x, true) . ', y=' . var_export($y, true) . ')');
    }

    // 비압축 점: 0x04 || x || y
    $point = "\x04" . $x . $y;

    // SubjectPublicKeyInfo DER
    // AlgorithmIdentifier SEQUENCE {
    //   OBJECT IDENTIFIER id-ecPublicKey (1.2.840.10045.2.1),
    //   OBJECT IDENTIFIER secp384r1 (1.3.132.0.34)
    // }
    // BIT STRING (unused bits=0) { point }
    $ecPubkeyOid  = '1.2.840.10045.2.1';
    $secp384r1Oid = '1.3.132.0.34';

    $oidSeq = der_sequence(der_oid($ecPubkeyOid) . der_oid($secp384r1Oid));
    $bitstr = der_bitstring($point);
    $spki   = der_sequence($oidSeq . $bitstr);

    return pem_encode('PUBLIC KEY', $spki);
}
// ─────────────────────────────────────────────────────────────────

// ─── DER 인코딩 헬퍼 ────────────────────────────────────────────
function der_oid(string $oid): string {
    $parts = explode('.', $oid);
    if (count($parts) < 2) throw new RuntimeException('DER OID 오류: ' . $oid);
    $first = (int)$parts[0] * 40 + (int)$parts[1];
    $out = chr(0x06) . der_length($first);
    for ($i = 2; $i < count($parts); $i++) {
        $out .= der_base128((int)$parts[$i]);
    }
    return $out;
}

function der_base128(int $v): string {
    if ($v === 0) return "\x00";
    $bytes = [];
    while ($v > 0) {
        $bytes[] = $v & 0x7f;
        $v >>= 7;
    }
    $bytes = array_reverse($bytes);
    for ($i = 0; $i < count($bytes) - 1; $i++) {
        $bytes[$i] |= 0x80;
    }
    $s = '';
    foreach ($bytes as $b) $s .= chr($b);
    return $s;
}

function der_length(int $len): string {
    if ($len < 0x80) return chr($len);
    if ($len < 0x100) return "\x81" . chr($len);
    if ($len < 0x10000) return "\x82" . chr($len >> 8) . chr($len & 0xff);
    if ($len < 0x100000000) {
        return "\x84"
             . chr($len >> 24)
             . chr(($len >> 16) & 0xff)
             . chr(($len >> 8) & 0xff)
             . chr($len & 0xff);
    }
    throw new RuntimeException('DER 길이 인코딩 불가 (너무 큼): ' . $len);
}

function der_sequence(string $content): string {
    return "\x30" . der_length(strlen($content)) . $content;
}

function der_bitstring(string $data): string {
    // unused bits = 0
    return "\x03" . der_length("\x00" . $data) . "\x00" . $data;
}

function pemEncode(string $type, string $der): string {
    $b64 = chunk_split(base64_encode($der), 64, "\n");
    return "-----BEGIN " . $type . "-----\n" . $b64 . "-----END " . $type . "-----\n";
}
// ─────────────────────────────────────────────────────────────────

// ─── WebAuthn 등록 옵션 생성 ───────────────────────────────────
function webauthn_get_register_options(string $username): array {
    $challenge = random_bytes(32);
    webauthn_save_challenge(base64url_encode($challenge));

    $user_id = hash('sha256', $username, true);

    return [
        'challenge' => base64url_encode($challenge),
        'rp' => [
            'name' => WEBAUTHN_RP_NAME,
            'id'   => WEBAUTHN_RPID,
        ],
        'user' => [
            'id'            => base64url_encode($user_id),
            'name'          => $username,
            'displayName'   => $username,
        ],
        'pubKeyCredParams' => [
            [
                'type' => 'public-key',
                'alg'  => WEBAUTHN_ALG, // ES384
            ],
        ],
        'authenticatorSelection' => [
            'authenticatorAttachment' => 'platform',
            'userVerification'        => 'required',
        ],
        'attestation' => 'none',
        'timeout' => 60000,
    ];
}
// ─────────────────────────────────────────────────────────────────

// ─── WebAuthn 인증 옵션 생성 ───────────────────────────────────
function webauthn_get_auth_options(): array {
    $credentials = webauthn_load_credentials();
    $allowed = [];
    foreach ($credentials['credentials'] ?? [] as $cred) {
        $allowed[] = [
            'type' => 'public-key',
            'id'   => $cred['credentialId'],
        ];
    }
    if (empty($allowed)) {
        return ['error' => '[WebAuthn] 등록된 Face ID/Touch ID 자격이 없습니다. 먼저 등록하세요.'];
    }

    $challenge = random_bytes(32);
    webauthn_save_challenge(base64url_encode($challenge));

    return [
        'challenge'          => base64url_encode($challenge),
        'rpId'               => WEBAUTHN_RPID,
        'allowCredentials'   => $allowed,
        'userVerification'   => 'required',
        'timeout'            => 60000,
    ];
}
// ─────────────────────────────────────────────────────────────────

// ─── WebAuthn 등록 검증 ────────────────────────────────────────
function webauthn_verify_registration(array $body, string $username): array {
    if (empty($body['response'])) {
        return ['ok' => false, 'error' => '요청에 response가 없습니다.'];
    }

    $resp = $body['response'];

    foreach (['clientDataJSON', 'attestationObject'] as $f) {
        if (empty($resp[$f])) {
            return ['ok' => false, 'error' => $f . ' 누락 (WebAuthn 등록)'];
        }
    }

    $cd = json_decode(base64url_decode($resp['clientDataJSON']), true);
    if (!is_array($cd)) {
        return ['ok' => false, 'error' => 'clientDataJSON 파싱 실패'];
    }

    $saved = webauthn_load_challenge();
    if ($saved === null || ($cd['challenge'] ?? '') !== $saved) {
        return ['ok' => false, 'error' => '챌린지 불일치/만료 (WebAuthn 등록)'];
    }

    if (($cd['origin'] ?? '') !== WEBAUTHN_ORIGIN) {
        return ['ok' => false, 'error' => 'origin 불일치: ' . ($cd['origin'] ?? 'null')];
    }

    try {
        $attObj = cbor_decode(base64url_decode($resp['attestationObject']));
    } catch (Exception $e) {
        return ['ok' => false, 'error' => 'attestationObject CBOR 파싱 실패: ' . $e->getMessage()];
    }
    if (!is_array($attObj) || !isset($attObj['authData'])) {
        return ['ok' => false, 'error' => 'attestationObject에 authData 없음 (key=authData)'];
    }

    $authData = $attObj['authData'];
    if (!is_string($authData)) {
        return ['ok' => false, 'error' => 'authData가 문자열이 아님'];
    }

    // authData:
    //   rpIdHash(32) | flags(1) | signCount(4) | credIdLen(1) | credId(credIdLen) | COSE PublicKey
    if (!is_string($authData) || strlen($authData) < 38) {
        return ['ok' => false, 'error' => 'authData 형식 오류 (최소 38바이트 문자열 필요, 실제=' . (is_string($authData) ? strlen($authData) : gettype($authData)) . ')'];
    }

    // AT (Attested credential data) 플래그 확인 (bit 6, 0x40) — 등록 응답이면 필수
    $flags = ord($authData[32]);
    if (($flags & 0x40) === 0) {
        return ['ok' => false, 'error' => 'authData에 AT 플래그 미설정 — 등록 응답 아님 (flags=0x' . dechex($flags) . ')'];
    }

    $signCount  = ord($authData[33]) << 24
                | ord($authData[34]) << 16
                | ord($authData[35]) << 8
                | ord($authData[36]);

    $credIdLen   = ord($authData[37]);
    if ($credIdLen === 0) {
        return ['ok' => false, 'error' => 'authData에 credentialId가 없음 (credIdLen=0)'];
    }
    if ($credIdLen > 256) {
        return ['ok' => false, 'error' => 'authData credentialId 길이 비정상 (credIdLen=' . $credIdLen . ')'];
    }
    if (38 + $credIdLen > strlen($authData)) {
        return ['ok' => false, 'error' => 'authData credentialId 길이 불일치 (credIdLen=' . $credIdLen . ', 잔여=' . (strlen($authData) - 38) . '바이트)'];
    }

    $credentialId = substr($authData, 38, $credIdLen);
    $cosePubkey   = substr($authData, 38 + $credIdLen);

    try {
        $pemPublicKey = cose_ec2_to_pem($cosePubkey);
    } catch (Exception $e) {
        return ['ok' => false, 'error' => 'COSE 공개키 → PEM 변환 실패: ' . $e->getMessage()];
    }

    // 중복 등록 방지
    $credentials = webauthn_load_credentials();
    if (isset($credentials['credentials'][$credentialId])) {
        return ['ok' => false, 'error' => '이미 등록된 Face ID/Touch ID 자격입니다.'];
    }

    $credentials['credentials'][$credentialId] = [
        'credentialId' => $credentialId,
        'publicKeyPem' => $pemPublicKey,
        'username'     => $username,
        'signCount'    => $signCount,
        'createdAt'    => time(),
    ];
    webauthn_save_credentials($credentials);
    webauthn_clear_challenge();

    return [
        'ok'          => true,
        'credentialId' => $credentialId,
        'username'    => $username,
        'message'     => 'Face ID/Touch ID 등록 완료',
    ];
}

// ─── WebAuthn 인증 검증 ────────────────────────────────────────
function webauthn_verify_authentication(array $body): array {
    if (empty($body['response'])) {
        return ['ok' => false, 'error' => '요청에 response가 없습니다.'];
    }

    $resp = $body['response'];

    foreach (['clientDataJSON', 'authenticatorData', 'signature'] as $f) {
        if (empty($resp[$f])) {
            return ['ok' => false, 'error' => $f . ' 누락 (WebAuthn 인증)'];
        }
    }

    $cd = json_decode(base64url_decode($resp['clientDataJSON']), true);
    if (!is_array($cd)) {
        return ['ok' => false, 'error' => 'clientDataJSON 파싱 실패'];
    }

    $saved = webauthn_load_challenge();
    if ($saved === null || ($cd['challenge'] ?? '') !== $saved) {
        return ['ok' => false, 'error' => '챌린지 불일치/만료 (WebAuthn 인증)'];
    }

    if (($cd['origin'] ?? '') !== WEBAUTHN_ORIGIN) {
        return ['ok' => false, 'error' => 'origin 불일치: ' . ($cd['origin'] ?? 'null')];
    }

    $credentialId = $resp['id'] ?? '';
    if (empty($credentialId)) {
        return ['ok' => false, 'error' => 'credentialId 누락'];
    }

    $credentials = webauthn_load_credentials();
    if (!isset($credentials['credentials'][$credentialId])) {
        return ['ok' => false, 'error' => '등록되지 않은 자격입니다.'];
    }

    $pemPublicKey = $credentials['credentials'][$credentialId]['publicKeyPem'];
    $signCount = $credentials['credentials'][$credentialId]['signCount'] ?? 0;

    // 인증 검증 실행
    $authData = base64url_decode($resp['authenticatorData']);
    $signature = base64url_decode($resp['signature']);

    // PEM 공개키를 OpenSSL에서 사용할 수 있는 형식으로 로드
    $pubkey = openssl_pkey_get_public($pemPublicKey);
    if ($pubkey === false) {
        return ['ok' => false, 'error' => '공개키 로드 실패: ' . openssl_error_string()];
    }

    // 인증이 유효한지 확인
    $dataToVerify = $authData . $cd['challenge'];
    $result = openssl_verify($dataToVerify, $signature, $pubkey, OPENSSL_ALGO_SHA384);

    if ($result !== 1) {
        return ['ok' => false, 'error' => '서명 검증 실패'];
    }

    // signCount 업데이트
    $newSignCount = max($signCount, ord($authData[33]) << 24 | ord($authData[34]) << 16 | ord($authData[35]) << 8 | ord($authData[36])) + 1;
    $credentials['credentials'][$credentialId]['signCount'] = $newSignCount;
    webauthn_save_credentials($credentials);
    webauthn_clear_challenge();

    $username = $credentials['credentials'][$credentialId]['username'];

    return [
        'ok'          => true,
        'credentialId' => $credentialId,
        'username'    => $username,
        'message'     => 'Face ID/Touch ID 인증 완료',
    ];
}

// ─── WebAuthn 디스패치 ──────────────────────────────────────────
function webauthn_dispatch(): void {
    $action = $_GET['action'] ?? $_POST['action'] ?? '';

    switch ($action) {
        case 'register-options':
            $username = $_GET['username'] ?? '';
            if (empty($username)) {
                header('Content-Type: application/json');
                echo json_encode(['error' => 'username이 필요합니다.']);
                return;
            }
            header('Content-Type: application/json');
            echo json_encode(webauthn_get_register_options($username));
            break;

        case 'register-verify':
            $username = $_GET['username'] ?? '';
            if (empty($username)) {
                header('Content-Type: application/json');
                echo json_encode(['error' => 'username이 필요합니다.']);
                return;
            }
            $body = json_decode(file_get_contents('php://input'), true) ?? [];
            header('Content-Type: application/json');
            echo json_encode(webauthn_verify_registration($body, $username));
            break;

        case 'auth-options':
            header('Content-Type: application/json');
            echo json_encode(webauthn_get_auth_options());
            break;

        case 'auth-verify':
            $body = json_decode(file_get_contents('php://input'), true) ?? [];
            header('Content-Type: application/json');
            echo json_encode(webauthn_verify_authentication($body));
            break;

        default:
            header('Content-Type: application/json');
            echo json_encode(['error' => '알 수 없는 action입니다.']);
            break;
    }
}

// 단독 실행 시 디스패치
if (basename($_SERVER['SCRIPT_NAME'] ?? '') === 'webauthn.php') {
    webauthn_dispatch();
}
