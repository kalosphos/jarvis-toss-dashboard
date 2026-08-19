<?php
header("Content-Type: application/json");
header("Cache-Control: no-store, no-cache, must-revalidate");

// toss-auth.php와 동일한 세션 검증 로직 사용
require_once __DIR__ . "/toss-auth.php";

// 세션이 유효하면 true, 아니면 false
if (isset($_COOKIE["toss_session"]) && !empty($_COOKIE["toss_session"])) {
    http_response_code(200);
    echo json_encode(["authenticated" => true]);
} else {
    http_response_code(200);
    echo json_encode(["authenticated" => false]);
}
