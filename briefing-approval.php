<?php
declare(strict_types=1);

// nginx Basic Auth protects this endpoint; PHP deliberately does not handle secrets.
const BRIEFING_FILE = __DIR__ . '/ai-daily-briefing.json';
const APPROVAL_FILE = __DIR__ . '/.control/briefing-approval.json';
const MAX_BODY_BYTES = 4096;
const MAX_PROPOSALS = 20;

function respond(int $status, array $body): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
}

function same_origin_request(): bool {
    if (isset($_SERVER['HTTP_SEC_FETCH_SITE']) && $_SERVER['HTTP_SEC_FETCH_SITE'] !== 'same-origin') return false;
    $source = $_SERVER['HTTP_ORIGIN'] ?? $_SERVER['HTTP_REFERER'] ?? '';
    $host = $_SERVER['HTTP_HOST'] ?? '';
    if ($source === '' || $host === '') return false;
    $sourceParts = parse_url($source);
    $hostParts = parse_url('//' . $host);
    if (!is_array($sourceParts) || !is_array($hostParts)) return false;
    $scheme = strtolower((string)($sourceParts['scheme'] ?? ''));
    $sourceHost = strtolower((string)($sourceParts['host'] ?? ''));
    $expectedHost = strtolower((string)($hostParts['host'] ?? ''));
    $sourcePort = (int)($sourceParts['port'] ?? ($scheme === 'https' ? 443 : 80));
    $expectedPort = isset($hostParts['port']) ? (int)$hostParts['port'] : null;
    return ($scheme === 'http' || $scheme === 'https') && $sourceHost !== ''
        && hash_equals($expectedHost, $sourceHost)
        && ($expectedPort === null || $expectedPort === $sourcePort);
}

function kst_date(): string { return (new DateTimeImmutable('now', new DateTimeZone('Asia/Seoul')))->format('Y-m-d'); }

function briefing_snapshot(string $path): array {
    $raw = @file_get_contents($path);
    $briefing = $raw === false ? null : json_decode($raw, true);
    if (!is_array($briefing) || !is_string($briefing['operating_date'] ?? null)
        || $briefing['operating_date'] !== kst_date() || !is_array($briefing['execution_proposals'] ?? null)) {
        throw new RuntimeException('fresh same-day briefing unavailable');
    }
    $proposals = [];
    foreach ($briefing['execution_proposals'] as $proposal) {
        if (!is_array($proposal) || array_keys($proposal) !== ['id','operating_date','action','side','symbol','weight_change','basis','status']) continue;
        if (!is_string($proposal['id']) || !preg_match('/^[a-f0-9]{64}$/', $proposal['id'])
            || $proposal['operating_date'] !== $briefing['operating_date']
            || !in_array($proposal['action'], ['BUY_SIGNAL','SELL_SIGNAL'], true)
            || !in_array($proposal['side'], ['buy','sell'], true)
            || $proposal['side'] !== ($proposal['action'] === 'BUY_SIGNAL' ? 'buy' : 'sell')
            || !is_string($proposal['symbol']) || !preg_match('/^[A-Z0-9.-]{1,32}$/', $proposal['symbol'])
            || $proposal['weight_change'] !== ($proposal['side'] === 'buy' ? 'increase' : 'decrease')
            || !is_string($proposal['basis']) || !is_string($proposal['status']) || $proposal['status'] !== 'requires_human_approval') continue;
        $canonical = json_encode(['operating_date'=>$proposal['operating_date'], 'action'=>$proposal['action'], 'side'=>$proposal['side'], 'symbol'=>$proposal['symbol'], 'weight_change'=>$proposal['weight_change'], 'basis'=>$proposal['basis'], 'status'=>$proposal['status']], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($canonical === false || !hash_equals(hash('sha256', $canonical), $proposal['id'])) continue;
        $proposals[$proposal['id']] = $proposal;
    }
    return ['operating_date' => $briefing['operating_date'], 'sha256' => hash('sha256', $raw), 'proposals' => $proposals];
}

function public_state(string $approvalPath, string $briefingPath): array {
    try { $snapshot = briefing_snapshot($briefingPath); } catch (Throwable $e) {
        return ['approved' => false, 'operating_date' => null, 'briefing_sha256' => null, 'proposal_ids' => [], 'updated_at' => null];
    }
    $raw = @file_get_contents($approvalPath);
    $state = $raw === false ? null : json_decode($raw, true);
    if (!is_array($state) || !is_array($state['approved_proposal_ids'] ?? null) || !is_string($state['operating_date'] ?? null)
        || !is_string($state['briefing_sha256'] ?? null) || !is_string($state['updated_at'] ?? null)
        || $state['operating_date'] !== $snapshot['operating_date'] || !hash_equals($snapshot['sha256'], $state['briefing_sha256'])) {
        return ['approved' => false, 'operating_date' => $snapshot['operating_date'], 'briefing_sha256' => $snapshot['sha256'], 'proposal_ids' => [], 'updated_at' => null];
    }
    $ids = $state['approved_proposal_ids'];
    $valid = count($ids) <= MAX_PROPOSALS && count($ids) === count(array_unique($ids));
    foreach ($ids as $id) $valid = $valid && is_string($id) && preg_match('/^[a-f0-9]{64}$/', $id) && isset($snapshot['proposals'][$id]);
    return [
        'approved' => $valid && count($ids) > 0,
        'operating_date' => $snapshot['operating_date'],
        'briefing_sha256' => $snapshot['sha256'],
        'proposal_ids' => $valid ? $ids : [],
        'updated_at' => $valid ? $state['updated_at'] : null,
    ];
}

function write_approval(string $path, array $snapshot, array $ids): array {
    if (count($ids) > MAX_PROPOSALS || count($ids) !== count(array_unique($ids))) throw new RuntimeException('invalid proposal ids');
    foreach ($ids as $id) if (!is_string($id) || !preg_match('/^[a-f0-9]{64}$/', $id) || !isset($snapshot['proposals'][$id])) throw new RuntimeException('proposal id not in current briefing');
    $directory = dirname($path);
    if (!is_dir($directory) && !mkdir($directory, 0777, true)) throw new RuntimeException('cannot create control directory');
    if (!is_writable($directory)) throw new RuntimeException('control directory is not writable');
    $state = ['operating_date' => $snapshot['operating_date'], 'briefing_sha256' => $snapshot['sha256'], 'approved_proposal_ids' => array_values($ids), 'updated_at' => gmdate('c')];
    $json = json_encode($state, JSON_UNESCAPED_SLASHES);
    if ($json === false) throw new RuntimeException('cannot encode approval state');
    $tmp = tempnam($directory, '.briefing-approval.');
    if ($tmp === false) throw new RuntimeException('cannot create temporary approval file');
    try {
        if (file_put_contents($tmp, $json . "\n", LOCK_EX) === false) throw new RuntimeException('cannot write temporary approval state');
        @chmod($tmp, 0644);
        if (!rename($tmp, $path)) throw new RuntimeException('cannot replace approval state');
        @chmod($path, 0644);
    } finally { if (is_file($tmp)) @unlink($tmp); }
    return $state;
}

function self_test(): int {
    $dir = sys_get_temp_dir() . '/briefing-approval-' . bin2hex(random_bytes(6));
    $briefing = $dir . '/ai-daily-briefing.json'; $approval = $dir . '/.control/briefing-approval.json';
    try {
        mkdir($dir, 0700); $date = kst_date();
        $p = ['id' => '', 'operating_date'=>$date, 'action'=>'BUY_SIGNAL', 'side'=>'buy', 'symbol'=>'005930', 'weight_change'=>'increase', 'basis'=>'existing_rule', 'status'=>'requires_human_approval'];
        $p['id'] = hash('sha256', json_encode(['operating_date'=>$p['operating_date'], 'action'=>$p['action'], 'side'=>$p['side'], 'symbol'=>$p['symbol'], 'weight_change'=>$p['weight_change'], 'basis'=>$p['basis'], 'status'=>$p['status']], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
        file_put_contents($briefing, json_encode(['operating_date'=>$date, 'execution_proposals'=>[$p]], JSON_UNESCAPED_SLASHES));
        if (public_state($approval, $briefing)['approved']) throw new RuntimeException('missing approval must be unapproved');
        $snap = briefing_snapshot($briefing); $state = write_approval($approval, $snap, [$p['id']]);
        $public = public_state($approval, $briefing);
        if (!$public['approved'] || $public['proposal_ids'] !== [$p['id']] || array_keys($public) !== ['approved','operating_date','briefing_sha256','proposal_ids','updated_at'] || !is_file($approval) || (fileperms($approval) & 0777) !== 0644) throw new RuntimeException('atomic approval round-trip failed');
        file_put_contents($briefing, json_encode(['operating_date'=>$date, 'execution_proposals'=>[]]));
        if (public_state($approval, $briefing)['approved']) throw new RuntimeException('tampered briefing accepted');
        $_SERVER=['HTTP_SEC_FETCH_SITE'=>'same-origin','HTTP_HOST'=>'dashboard.example.test','HTTP_ORIGIN'=>'https://dashboard.example.test'];
        if (!same_origin_request()) throw new RuntimeException('same-origin rejected');
        $_SERVER['HTTP_ORIGIN']='https://attacker.example.test'; if (same_origin_request()) throw new RuntimeException('cross-origin accepted');
        fwrite(STDOUT, "briefing-approval.php self-test: OK\n"); return 0;
    } catch (Throwable $e) { fwrite(STDERR, "briefing-approval.php self-test: FAILED: {$e->getMessage()}\n"); return 1;
    } finally { if (is_file($approval)) @unlink($approval); if (is_dir(dirname($approval))) @rmdir(dirname($approval)); if (is_file($briefing)) @unlink($briefing); if (is_dir($dir)) @rmdir($dir); }
}

if (PHP_SAPI === 'cli') { if ($argc === 2 && $argv[1] === '--self-test') exit(self_test()); fwrite(STDERR, "Usage: php briefing-approval.php --self-test\n"); exit(2); }
try {
    $method = $_SERVER['REQUEST_METHOD'] ?? '';
    if ($method === 'GET') { respond(200, public_state(APPROVAL_FILE, BRIEFING_FILE)); exit; }
    if ($method !== 'POST') { header('Allow: GET, POST'); respond(405,['error'=>'method not allowed']); exit; }
    if (!same_origin_request()) { respond(403,['error'=>'same-origin request required']); exit; }
    if (strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '')[0])) !== 'application/json') { respond(415,['error'=>'application/json required']); exit; }
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > MAX_BODY_BYTES) { respond(413,['error'=>'request body too large']); exit; }
    $raw = file_get_contents('php://input', false, null, 0, MAX_BODY_BYTES + 1); $body = $raw === false ? null : json_decode($raw, true);
    if (!is_array($body) || count($body) !== 2 || !array_key_exists('action', $body) || !array_key_exists('approved_proposal_ids', $body)
        || !is_string($body['action']) || !in_array($body['action'],['approve','revoke'],true) || !is_array($body['approved_proposal_ids'])) { respond(400,['error'=>'JSON body must be action plus approved_proposal_ids']); exit; }
    $ids = $body['action'] === 'revoke' ? [] : $body['approved_proposal_ids'];
    if ($body['action'] === 'revoke' && $body['approved_proposal_ids'] !== []) { respond(400,['error'=>'revoke requires an empty approved_proposal_ids array']); exit; }
    if ($body['action'] === 'approve' && $ids === []) { respond(400,['error'=>'approve requires current proposal ids']); exit; }
    $snapshot = briefing_snapshot(BRIEFING_FILE); write_approval(APPROVAL_FILE, $snapshot, $ids); respond(200, public_state(APPROVAL_FILE, BRIEFING_FILE));
} catch (Throwable $e) { error_log('briefing approval error: ' . $e->getMessage()); respond(500,['error'=>'briefing approval unavailable']); }
