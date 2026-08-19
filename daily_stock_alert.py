name: 매일 아침 증시 브리핑 카카오톡 전송

on:
  schedule:
    # UTC 22:30 = 한국시간(KST) 07:30
    - cron: "37 22 * * *"
  workflow_dispatch: {}  # 수동 실행 버튼(테스트용)

jobs:
  send-alert:
    runs-on: ubuntu-latest
    steps:
      - name: 저장소 체크아웃
        uses: actions/checkout@v4

      - name: 파이썬 설정
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: 의존성 설치
        run: pip install -r 파일/requirements.txt

      - name: 증시 브리핑 전송
        env:
          KAKAO_REST_API_KEY: ${{ secrets.KAKAO_REST_API_KEY }}
          KAKAO_REFRESH_TOKEN: ${{ secrets.KAKAO_REFRESH_TOKEN }}
          GH_TOKEN: ${{ secrets.GH_PAT }}
          GH_REPO: ${{ github.repository }}
        run: python 파일/daily_stock_alert.py
