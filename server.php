<?php
/**
 * server.php - toss PHP 내장 서버용 entry point
 * 
 * php -S 127.0.0.1:8794 -t . server.php
 * 
 * /toss/ 이하 요청을 /Volumes/toss 기준으로 처리.
 * 정적 파일은 php 내장 서버가 그대로 처리하되,
 * PHP 스크립트는 여기서만 명시적으로 실행.
 */
declare(strict_types=1);

$uri = rawurldecode(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/');
// /toss/ prefix 제거 (대시보드가 /toss/ 아래 서빙되므로)
if (strpos($uri, '/toss') === 0) {
    $uri = substr($uri, 5); // '/toss' 제거
    if ($uri === '') {
        $uri = '/';
    }
}

$docRoot = '/Volumes/web/toss';

// 기본 문서
if ($uri === '/' || $uri === '') {
    $uri = '/index.html';
}

// 경로 탐색 방어
if (strpos($uri, '..') !== false) {
    http_response_code(403);
    echo json_encode(['error' => 'forbidden']);
    exit;
}

$filePath = $docRoot . $uri;

// 디렉토리 요청이면 index.html
if (is_dir($filePath)) {
    $index = $filePath . '/index.html';
    if (is_file($index)) {
        $filePath = $index;
    } else {
        http_response_code(403);
        echo 'directory listing forbidden';
        exit;
    }
}

// 파일 없음
if (!is_file($filePath)) {
    http_response_code(404);
    echo 'not found: ' . $uri;
    exit;
}

// PHP 스크립트는 여기서 실행 (setcookie 정상 동작을 위해 직접 실행)
if (substr($filePath, -4) === '.php') {
    // built-in 서버처럼 SCRIPT_FILENAME 및 관련 SERVER 변수를 설정
    $_SERVER['SCRIPT_FILENAME'] = $filePath;
    $_SERVER['SCRIPT_NAME'] = $uri;
    $_SERVER['PHP_SELF'] = $uri;
    // 원본 REQUEST_URI는 /toss/... 형태일 수 있으므로 유지
    // (toss-auth.php 등은 $_SERVER['REQUEST_URI']를 직접 볼 수 있음)

    // 출력 버퍼를 켜서 setcookie 호출 시 헤더 전송 충돌을 방지
    if (ob_get_level() === 0) {
        ob_start();
    }

    try {
        include $filePath;
    } catch (Throwable $e) {
        http_response_code(500);
        echo 'php error: ' . $e->getMessage();
    }

    // 버퍼에 남은 출력을 전송
    if (ob_get_level() > 0) {
        ob_end_flush();
    }
    exit;
}
$mime = match ($ext) {
    'html' => 'text/html',
    'css'  => 'text/css',
    'js'   => 'application/javascript',
    'json' => 'application/json',
    'ico'  => 'image/x-icon',
    'svg'  => 'image/svg+xml',
    'png'  => 'image/png',
    'jpg', 'jpeg' => 'image/jpeg',
    'gif'  => 'image/gif',
    default => 'application/octet-stream',
};
header('Content-Type: ' . $mime);
header('Cache-Control: no-store');
readfile($filePath);
