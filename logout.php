<?php
/**
 * Logout handler for /toss/
 * Clears session cookie and redirects to login
 */

header('Content-Type: application/json; charset=utf-8');

// Set cookie to expire in the past
setcookie('toss_session', '', [
    'expires' => time() - 3600,
    'path' => '/toss',
    'domain' => '',
    'secure' => false,
    'httponly' => true,
    'samesite' => 'Lax',
]);

echo json_encode([
    'success' => true,
    'message' => 'Logged out successfully.',
]);
