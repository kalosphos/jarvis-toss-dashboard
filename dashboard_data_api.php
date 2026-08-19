<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$table = $_GET['table'] ?? 'dashboard_data';
if (!in_array($table, ['dashboard_data', 'quotes_data'], true)) {
    $table = 'dashboard_data';
}

$sqlitePath = __DIR__ . '/jarvis.sqlite';

try {
    if (!is_file($sqlitePath)) {
        throw new RuntimeException('SQLite not found: ' . $sqlitePath);
    }
    $pdo = new PDO('sqlite:' . $sqlitePath, null, null, [
        PDO::ATTR_TIMEOUT => 5,
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    ]);
    $pdo->exec('PRAGMA busy_timeout=5000');
    $stmt = $pdo->query("SELECT payload FROM {$table} ORDER BY generated_at DESC LIMIT 1");
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if (!$row) {
        http_response_code(404);
        echo json_encode(['error' => 'no data'], JSON_UNESCAPED_UNICODE);
        exit;
    }
    echo $row['payload'];
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()], JSON_UNESCAPED_UNICODE);
}
