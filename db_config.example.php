<?php
// NAS MariaDB 연결 설정 — 예시 템플릿 (공개용)
//
// 운영 배포 시 이 파일을 db_config.php 로 복사하고 실제 값을 채우거나,
// 환경변수 JARVIS_DB_* 로 주입하세요.
// (실제 db_config.php 는 .gitignore 에서 제외되어 저장소에 올라가지 않습니다.)
if (basename(__FILE__) === basename($_SERVER['SCRIPT_FILENAME'] ?? '')) {
    http_response_code(403);
    exit;
}
define('JARVIS_DB_HOST', getenv('JARVIS_DB_HOST') ?: '127.0.0.1');
define('JARVIS_DB_PORT', getenv('JARVIS_DB_PORT') ?: '3306');
define('JARVIS_DB_USER', getenv('JARVIS_DB_USER') ?: 'root');
define('JARVIS_DB_PASS', getenv('JARVIS_DB_PASS') ?: 'CHANGE_ME');
define('JARVIS_DB_NAME', getenv('JARVIS_DB_NAME') ?: 'jarvis');
