# 자비스 주식운용 대시보드 (toss)

NAS Web Station(`/toss/`)에서 운영되는 주식운용 대시보드의 **소스 코드** 저장소입니다.
인증 게이트(WebAuthn / 쿠키 기반 세션), 대시보드 UI, 운영 파이썬 스크립트, nginx snippet을 포함합니다.

> ⚠️ 이 저장소는 **공개용**입니다. 실제 DB 비밀번호·계좌/포지션 재무데이터·운영 상태 JSON(`.control/`, `dashboard-data.json` 등)은 `.gitignore`에서 제외되어 커밋되지 않습니다.

## 구성

| 경로 | 용도 |
|---|---|
| `index.php` | 인증 게이트 진입점 (쿠키 검증 → 대시보드 / 미인증 → login.html) |
| `login.html` | 로그인 페이지 (WebAuthn + Basic Auth) |
| `toss-auth.php`, `webauthn.php`, `auth-check.php`, `logout.php` | 인증/세션 로직 |
| `control.php`, `exclusion.php` | 운영 제어 엔드포인트 |
| `asset_history_api.php`, `dashboard_data_api.php`, `data.php` | DB/데이터 조회 API |
| `dashboard.css` | 대시보드 스타일 |
| `*.py` | 운영 스크립트 (자산 스냅샷, 자동매매 매니저, 뉴스 브리핑 등) |
| `.location.webstation.conf.toss-dashboard` | Web Station nginx snippet 예시 |

## 설치/배포

1. Web Station 가상 호스트(`/toss/`) 루트에 파일 배포
2. `db_config.example.php` 를 `db_config.php` 로 복사 후 실제 DB 접속 정보 입력
   (또는 환경변수 `JARVIS_DB_*` 주입)
3. `.control/`, `.private/` 디렉터리 생성 및 쓰기 권한 확인
4. nginx snippet(`.location.webstation.conf.toss-dashboard`)을 가상 호스트에 include

## 비밀 관리

- `db_config.php` 는 절대 커밋하지 마세요 (`.gitignore` 참조).
- 운영 시 비밀번호는 환경변수 또는 별도 보호 파일로 주입하세요.
