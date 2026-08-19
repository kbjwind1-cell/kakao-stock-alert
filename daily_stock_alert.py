"""
매일 아침 실행되는 메인 스크립트
--------------------------------
1) refresh_token 으로 access_token 재발급 (+ 새 refresh_token으로 Secret 갱신)
2) 코스피/코스닥/다우/나스닥/S&P500/원달러 환율/증권 뉴스 헤드라인 수집
3) 카카오톡 '나에게 보내기' 로 메시지 전송

GitHub Actions 환경변수(Secrets)로 아래 값들이 필요합니다:
  KAKAO_REST_API_KEY   : 카카오 REST API 키
  KAKAO_REFRESH_TOKEN  : get_kakao_token.py 로 발급받은 refresh token
  GH_TOKEN             : Secrets를 갱신하기 위한 GitHub Personal Access Token
                          (repo 권한 필요, 'Contents' 또는 'Secrets' write)
  GH_REPO              : 예) "yourname/kakao-stock-alert"
"""

import os
import sys
import json
import base64
import requests
from datetime import datetime
from nacl import encoding, public  # PyNaCl - GitHub Secret 암호화용

KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]
GH_TOKEN = os.environ.get("GH_TOKEN")
GH_REPO = os.environ.get("GH_REPO")


# ---------- 1. 카카오 토큰 갱신 ----------
def refresh_kakao_token():
    res = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": KAKAO_REST_API_KEY,
            "refresh_token": KAKAO_REFRESH_TOKEN,
        },
    )
    res.raise_for_status()
    data = res.json()
    access_token = data["access_token"]
    new_refresh_token = data.get("refresh_token")  # 항상 갱신되진 않음
    return access_token, new_refresh_token


def update_github_secret(new_refresh_token: str):
    """refresh_token이 갱신된 경우, GitHub Actions Secret도 함께 업데이트"""
    if not new_refresh_token or not GH_TOKEN or not GH_REPO:
        return
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    # 저장소 공개키 조회
    key_res = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
        headers=headers,
    )
    key_res.raise_for_status()
    key_data = key_res.json()

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(new_refresh_token.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    requests.put(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/KAKAO_REFRESH_TOKEN",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
    ).raise_for_status()
    print("KAKAO_REFRESH_TOKEN Secret 갱신 완료")


# ---------- 2. 시세 수집 ----------
def get_us_indices():
    """야후 파이낸스로 미국 3대 지수 조회 (yfinance)"""
    import yfinance as yf

    tickers = {
        "다우존스": "^DJI",
        "나스닥": "^IXIC",
        "S&P500": "^GSPC",
    }
    lines = []
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            hist = hist.dropna(subset=["Close"])
            if len(hist) < 2:
                lines.append(f"{name}: 데이터 부족으로 조회 실패")
                continue
            last = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change = last - prev
            pct = change / prev * 100
            arrow = "▲" if change >= 0 else "▼"
            lines.append(f"{name}: {last:,.2f} ({arrow}{abs(change):,.2f}, {pct:+.2f}%)")
        except Exception as e:
            lines.append(f"{name}: 조회 실패 ({e})")
    return lines


def get_kr_indices():
    """야후 파이낸스로 코스피/코스닥 조회 (네이버 크롤링보다 안정적)"""
    import yfinance as yf

    tickers = {"코스피": "^KS11", "코스닥": "^KQ11"}
    lines = []
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            hist = hist.dropna(subset=["Close"])
            if len(hist) < 2:
                lines.append(f"{name}: 데이터 부족으로 조회 실패")
                continue
            last = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change = last - prev
            pct = change / prev * 100
            arrow = "▲" if change >= 0 else "▼"
            lines.append(f"{name}: {last:,.2f} ({arrow}{abs(change):,.2f}, {pct:+.2f}%)")
        except Exception as e:
            lines.append(f"{name}: 조회 실패 ({e})")
    return lines


def get_usd_krw():
    import yfinance as yf

    try:
        hist = yf.Ticker("KRW=X").history(period="5d")
        hist = hist.dropna(subset=["Close"])
        if len(hist) < 2:
            return "원/달러: 데이터 부족으로 조회 실패"
        last = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        change = last - prev
        arrow = "▲" if change >= 0 else "▼"
        return f"원/달러: {last:,.2f}원 ({arrow}{abs(change):,.2f})"
    except Exception as e:
        return f"원/달러: 조회 실패 ({e})"


def get_news_headlines(limit=3):
    """네이버 금융 주요뉴스 헤드라인 스크래핑"""
    import re

    try:
        url = "https://finance.naver.com/news/mainnews.naver"
        html = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).text
        titles = re.findall(r'class="articleSubject">\s*<a[^>]*>([^<]+)</a>', html)
        return titles[:limit] if titles else ["헤드라인 조회 실패"]
    except Exception as e:
        return [f"뉴스 조회 실패 ({e})"]


# ---------- 3. 카카오톡 전송 ----------
def send_kakao_message(access_token: str, text: str):
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": "https://finance.naver.com", "mobile_web_url": "https://finance.naver.com"},
    }
    res = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
    )
    if res.status_code != 200:
        print("카카오톡 전송 실패:", res.status_code, res.text)
        sys.exit(1)
    print("카카오톡 전송 완료")


def main():
    access_token, new_refresh_token = refresh_kakao_token()
    if new_refresh_token:
        update_github_secret(new_refresh_token)

    today = datetime.now().strftime("%Y년 %m월 %d일 (%a)")
    lines = [f"📈 {today} 증시 브리핑\n"]

    lines.append("[국내]")
    lines.extend(get_kr_indices())
    lines.append("")
    lines.append("[미국]")
    lines.extend(get_us_indices())
    lines.append("")
    lines.append(get_usd_krw())
    lines.append("")
    lines.append("[주요 뉴스]")
    for headline in get_news_headlines():
        lines.append(f"- {headline}")

    message = "\n".join(lines)
    print(message)
    send_kakao_message(access_token, message)


if __name__ == "__main__":
    main()
