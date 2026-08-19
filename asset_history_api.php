<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$period = $_GET['period'] ?? 'all';
$valid = ['1d','7d','1m','all'];
if (!in_array($period, $valid, true)) {
    $period = 'all';
}

$useDaily = in_array($period, ['1m','6m','1y','all'], true);

// 데이터 소스: NAS SQLite (대시보드 직접 서빙). MariaDB는 백업용.
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

    if ($useDaily) {
        $stmt = $pdo->query('SELECT trade_date, payload FROM asset_daily ORDER BY trade_date ASC');
        $out = [];
        while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
            $rec = json_decode($row['payload'], true);
            if (is_array($rec)) {
                $rec['trade_date'] = $row['trade_date'];
                $out[] = $rec;
            }
        }
        echo json_encode(['daily' => $out, 'history' => []], JSON_UNESCAPED_UNICODE);
    } else {
        $stmt = $pdo->query("SELECT generated_at, payload FROM asset_history WHERE resolution='intraday' ORDER BY generated_at ASC");
        $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
        $out = [];
        foreach ($rows as $row) {
            $rec = json_decode($row['payload'], true);
            if (!is_array($rec)) continue;
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
