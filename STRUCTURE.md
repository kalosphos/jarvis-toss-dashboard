# 자비스 주식운용 대시보드 — 운영 root 구조 (v3.1)

이 디렉터리는 NAS Web Station 가상 호스트(`/toss/`)의 운영 root입니다.
각 항목의 **용도**와 **nginx가 서빙하는지 여부**를 명시합니다.

## 운영 root (nginx가 서빙)

| 경로 | 용도 | 비고 |
|---|---|---|
| `index.html` | Next.js 빌드 결과물 (대시보드 정적 진입점) | nginx가 `/toss/`에서 정적으로 서빙 |
| `index.php` | 인증 게이트 (쿠키 검증 후 index.html readfile 또는 login.html redirect) | nginx가 `/toss/`에서 PHP-FPM으로 라우팅. 현재 nginx default index 룰이 `index.html`을 먼저 선택해 PHP 게이트가 무력화된 상태 → nginx conf의 `index index.php index.html;` 변경 권장 |
| `login.html` | 로그인 페이지 (WebAuthn + Basic Auth) | nginx location에 명시 |
| `404.html` | Next.js 정적 404 | nginx가 fallback |
| `_next/` | Next.js 정적 자산 (JS/CSS 청크) | nginx가 직접 서빙 |
| `_not-found/` | Next.js 정적 not-found | nginx가 직접 서빙 |
| `404/` | Next.js 정적 404 페이지 디렉터리 | nginx가 직접 서빙 |
| `favicon.ico`, `*.svg` | 정적 자산 | nginx가 직접 서빙 |
| `__next.*.txt` | Next.js 빌드 트리(text trick) | nginx가 직접 서빙 |
| `*.php` | 인증/런타임 PHP | nginx가 PHP-FPM으로 라우팅 |
| `.htaccess` | `/toss/` Apache 호환 폴더 가드 | Web Station이 호환 처리 |
| `control.htaccess` | `control/` 하위 차단 | Web Station 가드 |
| `private.htaccess` | `.private/` 하위 차단 | Web Station 가드 |
| `.control/` | 거래 제어 JSON (런타임) | nginx가 차단(`/toss/.control/` 404) |
| `.private/` | htpasswd (Basic Auth 자격 증명) | nginx가 차단(`/toss/.private/` 404) |
| `.location.webstation.conf.toss-dashboard` | Web Station 가상 호스트 nginx snippet | Web Station이 include |

## 운영 root (nginx가 서빙하지 않음 — 분리/격리)

| 경로 | 용도 | 비고 |
|---|---|---|
| `dashboard-src/` | Next.js 소스 + node_modules(352M). git 추적 대상. 빌드 시 `_dev/source/` 등 별도 디렉터리에 두고 빌드 후 운영 root에 산출물만 deploy 권장. 현 위치는 운영에 영향 없음(nginx가 `/toss/dashboard-src/`로 라우팅하지 않음) | nginx 영향 없음. 대량 이동은 SMB 부하 큼 |
| `_dev/misc/` | 운영에 직접 영향 없는 dev 잔재 (`bin/`, `__pycache__/`, `backups/`, `deploy/`, `.deploy-backup/`, `.backup-*/`) | 운영과 분리된 격리 위치 |
| `_dev/archive/` | 백업 잔재 (`*.bak-20260808*`, `login.html.bak-*`, `toss-auth.php.bak-*`, `auto_trading_manager.py.bak-*`) | 운영과 분리된 격리 위치 |
| `.git/` | git 추적 메타 | 운영 영향 없음 |
| `.gitignore` | git 추적 제외 규칙 | 운영 영향 없음 |
| `.sync-dashboard-src.sh` | 소스 동기 헬퍼 스크립트 | 운영 영향 없음 |
| `STRATEGY.md` (현재 파일) | 본 문서 | 운영 영향 없음 |

## 런타임 데이터 (nginx가 서빙 — JSON 라우팅)

| 경로 | 라우팅 | 비고 |
|---|---|---|
| `dashboard-data.json` | `/toss/*.json` → `data.php` (nginx conf `proxy_pass`) | 런타임 |
| `dashboard-history.json` | 동일 | �타임 |
| `auto-trading-status.json` | 동일 | 런타임 |
| `auto-execution-state.json` | 동일 | 런타임 |
| `ai-daily-briefing.json` | 동일 | 런타임 |
| `daily-trade-plan.json` | 동일 | 런타임 |
| `jarvis-atm-status.json` | 동일 | 런타임 |
| `BRIEFING_MACRO_SCHEMA.md` | (nginx 영향 없음) | 런타임 스키마 문서 |

## 진입 게이트 의도 (사용자 결정)

`/toss/` 접속 시:
1. nginx가 index 룰에 따라 진입점 선택
2. **현재**: nginx default가 `index.html`을 먼저 선택 → 정적 index.html 직접 서빙 (인증 게이트 우회)
3. **의도**: nginx가 `index.php`를 먼저 선택 → PHP 게이트 실행
   - 인증 쿠키 유효 → `index.html` readfile
   - 인증 쿠키 없음/만료 → `login.html` redirect

nginx conf 수정(권장):

```nginx
location ^~ /toss/ {
    index index.php index.html;
    # ... 기존 location ...
}
```

이는 Web Station UI의 가상 호스트 편집에서 적용. SMB 마운트로는 nginx conf 위치(`/etc/nginx/...`)에 접근할 수 없어 사용자가 Web Station에서 직접 수정해야 함.

## 빌드/배포 흐름

1. `/Users/jarvis/work/jarvis-dashboard-v2-css-release/` 에서 `next build`
2. `out/`의 정적 자산을 운영 root(`/Volumes/web/toss/`)에 deploy (인덱스 HTML/CSS/JS/JSON/SVG)
3. 인증/런타임 PHP는 deploy 시 미수정 (현 위치 보존)
4. `.build-version.json` sha 갱신

## 빌드 호환성 메모

`dashboard-src/dashboard-src/next.config.ts`의 `turbopack.root`는 `__dirname` (이전 `join(__dirname, '..')`은 부모 디렉터리까지 scan해 무한 hang). 빌드는 본 로컬(`/Users/jarvis/work/...`)에서 실행.

## 운영 URL (현재 200 검증)

- `https://kwangho79.synology.me/toss/` (nginx default → index.html, 인증 게이트 우회)
- `https://kwangho79.synology.me/toss/login.html` (공개)
- `https://kwangho79.synology.me/toss/toss-auth.php` (PHP 게이트, GET → 405, POST → 동작)
- `https://kwangho79.synology.me/toss/control.php` (401, 인증 필요)
- `https://kwangho79.synology.me/toss/dashboard-data.json` (data.php 라우팅)
- `https://kwangho79.synology.me/toss/_next/static/chunks/<hash>.css` (정적 자산)
