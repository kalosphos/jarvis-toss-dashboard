# briefing-macro.json 스키마 (09시 운용 브리핑용 사용자 입력/자동집계 매크로 컨텍스트)

## 용도
- `jarvis_daily_briefing.py`가 이 파일을 읽어 `ai-daily-briefing.json`을 생성한다.
- 파일이 없거나 필드가 비면 해당 섹션은 "미입력"으로 표시된다.
- 모든 내용은 참고용이며, 실주문은 대시보드 거래권한 토글 게이트가 결정한다.

## 필드

### meta
- `generated_at` (ISO KST): 이 매크로 컨텍스트를 마지막으로 갱신한 시각
- `scope` (str): 기준 시점/범위 예: "2026-08-09 KST 기준"

### market_overview (str)
- 국내 증시 전반 분위기, KOSPI/KOSDAQ 톤, 주도 섹터 맥락
- 예: "KOSPI는 반도체·전력기기 중심 강세, KOSDAQ은 2차전지 약세 속 종목별 차별화"

### macro (str 또는 객체)
- 금리/환율/국채/정책 등 거시경제 요약
- 예: "원/달러 1,300원대 중후반, 미 금리 인하 기대 후퇴, 국내 국채금리 상승 압력"

### geopolitics (str)
- 세계정세/지정학 요약 (미국/중국/대만/우크라이나/중동 등)
- 증시 영향 가능한 이슈 중심

### news (배열)
최근 한국 주식 관련 뉴스/이슈. 각 항목:
- `date` (str): 보도/발생 시점
- `headline` (str): 한 줄 요약
- `sector` (str): 관련 섹터/테마
- `detail` (str): 내용
- `source` (str): 출처/매체
- `confidence` (str): 확인 수준 (확인/추정/보류)

### watchlist (배열) — 관심 후보군
"추천"이 아니라 "최근 재료/모멘텀 기준 관심 후보" 성격. 각 항목:
- `name` (str): 종목군/종목명
- `reason` (str): 재료/모멘텀/이유
- `strength` (str): 강·중·약 또는 단기/중기
- `caution` (str): 리스크/주의점
- `evidence` (str): 근거/출처 메모

### suggestions (배열, 선택)
참고용 제안. 없으면 스크립트 기본값을 쓴다.
- `label`, `detail`

### note (str, 선택)
참고용/실거래 무관 명시 등 추가 주의문

## 예시 구조를 보려면 jarvis_daily_briefing.py의 build_briefing() 주석을 참고
