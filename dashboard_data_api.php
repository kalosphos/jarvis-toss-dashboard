<?php
declare(strict_types=1);
require_once __DIR__ . '/db_config.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$table = $_GET['table'] ?? 'dashboard_data';
if (!in_array($table, ['dashboard_data', 'quotes_data'], true)) {
    $table = 'dashboard_data';
}

try {
    $pdo = new PDO(
        'mysql:host=' . JARVIS_DB_HOST . ';port=' . JARVIS_DB_PORT . ';dbname=' . JARVIS_DB_NAME . ';charset=utf8mb4',
        JARVIS_DB_USER, JARVIS_DB_PASS,
        [PDO::ATTR_TIMEOUT => 5, PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );
    // 최신 1행
    $stmt = $pdo->query("SELECT payload FROM {$table} ORDER BY generated_at DESC LIMIT 1");
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!$row) {
        http_response_code(404);
        echo json_encode(['error' => 'no data'], JSON_UNESCAPED_UNICODE);
        exit;
    }
    // payload가 이미 JSON이므로 그대로 출력 (json_decode→encode 하지 않음, 제어문자 보존)
    echo $row['payload'];
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()], JSON_UNESCAPED_UNICODE);
}
