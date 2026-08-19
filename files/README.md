# 매일 아침 증시 브리핑 카카오톡 전송

한국/미국 증시 + 환율 + 주요 뉴스를 매일 아침 자동으로 수집해서
카카오톡 '나에게 보내기'로 전송하는 GitHub Actions 자동화입니다.

## 폴더 구조

```
kakao-stock-alert/
├── .github/workflows/daily-stock-alert.yml   # 매일 자동 실행 워크플로우
├── scripts/
│   ├── get_kakao_token.py                    # 최초 1회 실행 (로컬)
│   └── daily_stock_alert.py                  # 매일 실행되는 본 스크립트
├── requirements.txt
└── README.md
```

## 설정 순서

### 1. 카카오 개발자센터 설정 (이미 안내받으신 4단계)
1. https://developers.kakao.com 에서 앱 등록 → REST API 키 확인
2. 카카오 로그인 활성화 + Redirect URI `http://localhost:5000/callback` 등록
3. 동의항목에서 '카카오톡 메시지 전송(talk_message)' 선택 동의로 설정

### 2. GitHub 저장소 만들기
1. GitHub에서 새 저장소 생성 (Private 추천, 예: `kakao-stock-alert`)
2. 이 폴더의 내용을 그대로 push

```bash
cd kakao-stock-alert
git init
git add .
git commit -m "init"
git remote add origin https://github.com/사용자명/kakao-stock-alert.git
git push -u origin main
```

### 3. refresh token 최초 발급 (로컬 PC에서 1회만)
```bash
pip install requests
python scripts/get_kakao_token.py
```
- `get_kakao_token.py` 상단의 `REST_API_KEY` 값을 본인 키로 수정 후 실행
- 안내되는 URL을 브라우저로 열고 로그인/동의 → redirect 주소의 `code` 값을 터미널에 입력
- 출력된 `REFRESH_TOKEN` 값을 복사해두세요

### 4. GitHub Personal Access Token(PAT) 발급
Actions가 refresh token 갱신 시 Secret을 자동으로 업데이트하려면 별도 PAT가 필요합니다.
1. GitHub 우측상단 프로필 → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. `repo` 권한 체크 후 생성
3. 생성된 토큰 값 복사

### 5. GitHub Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|---|---|
| `KAKAO_REST_API_KEY` | 카카오 개발자센터 REST API 키 |
| `KAKAO_REFRESH_TOKEN` | 3단계에서 발급받은 refresh token |
| `GH_PAT` | 4단계에서 발급받은 Personal Access Token |

### 6. 테스트 실행
저장소 → Actions 탭 → "매일 아침 증시 브리핑 카카오톡 전송" 선택 → **Run workflow** 버튼으로 수동 실행해서
카카오톡으로 메시지가 잘 오는지 확인하세요.

정상 작동하면 이후로는 매일 한국시간 오전 7시 30분에 자동으로 전송됩니다.
(전송 시간을 바꾸고 싶으면 `daily-stock-alert.yml`의 `cron: "30 22 * * *"` 값을 수정하세요.
UTC 기준이라 한국시간 - 9시간으로 계산하면 됩니다.)

## 주의사항

- 네이버 금융 페이지 구조가 바뀌면 코스피/코스닥/뉴스 파싱이 깨질 수 있습니다.
  이 경우 `daily_stock_alert.py`의 `get_kr_indices()` / `get_news_headlines()` 정규식을
  최신 페이지 구조에 맞게 수정해야 합니다.
- 카카오 refresh token은 최대 2개월 정도 미사용 시 만료됩니다. 매일 자동 실행되므로
  정상적으로는 계속 갱신되어 문제 없습니다.
- 스크립트는 GitHub Actions의 공용 서버에서 실행되므로 완전 무료입니다 (Public 저장소 기준
  무제한, Private 저장소는 월 2,000분 무료 한도 내).
