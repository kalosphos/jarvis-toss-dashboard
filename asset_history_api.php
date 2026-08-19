<?php
declare(strict_types=1);
require_once __DIR__ . '/db_config.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$period = $_GET['period'] ?? 'all';
$valid = ['1d','7d','1m','6m','1y','all'];
if (!in_array($period, $valid, true)) {
    $period = 'all';
}

$useDaily = in_array($period, ['1m','6m','1y','all'], true);

try {
    $pdo = new PDO(
        'mysql:host=' . JARVIS_DB_HOST . ';port=' . JARVIS_DB_PORT . ';dbname=' . JARVIS_DB_NAME . ';charset=utf8mb4',
        JARVIS_DB_USER, JARVIS_DB_PASS,
        [PDO::ATTR_TIMEOUT => 5, PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );

    if ($useDaily) {
        // 일봉: asset_daily 전체 (프론트에서 기간 필터)
        $stmt = $pdo->query('SELECT trade_date, payload FROM asset_daily ORDER BY trade_date ASC');
        $out = [];
        while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
            $rec = json_decode($row['payload'], true);
            if (is_array($rec)) {
                $rec['trade_date'] = $row['trade_date'];  // 프론트 파싱용
                $out[] = $rec;
            }
        }
        echo json_encode(['daily' => $out, 'history' => []], JSON_UNESCAPED_UNICODE);
    } else {
        // 장중 3분: resolution='intraday', 기간 필터는 프론트에서
        $stmt = $pdo->query("SELECT generated_at, payload FROM asset_history WHERE resolution='intraday' ORDER BY generated_at ASC");
        $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
        $out = [];
        foreach ($rows as $row) {
            $rec = json_decode($row['payload'], true);
            if (!is_array($rec)) continue;
            // DATETIME(공백 구분, 타임존 없음) → ISO 8601(KST)로 변환 (프론트 Date.parse 호환)
            $ga = $row['generated_at'];
            if (preg_match('/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/', $ga)) {
                $ga = str_replace(' ', 'T', $ga) . '+09:00';
            }
            $rec['generated_at'] = $ga;
            $out[] = $rec;
        }
        echo json_encode(['history' => $out, 'daily' => []], JSON_UNESCAPED_UNICODE);
    }
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()], JSON_UNESCAPED_UNICODE);
}
