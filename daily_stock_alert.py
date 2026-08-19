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
    """네이버 실시간 API로 코스피/코스닥 조회, 실패 시 야후 파이낸스로 대체"""
    lines = []
    codes = {"코스피": "KOSPI", "코스닥": "KOSDAQ"}
    for name, code in codes.items():
        try:
            url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
            data = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).json()
            item = data["result"]["areas"][0]["datas"][0]
            now_val = item["nv"] / 100  # 소수점 2자리 기준으로 100배 되어 옴
            change_val = item["cv"] / 100
            change_rate = item["cr"] / 100
            falling = item.get("rf") == "2" or item.get("rf") == 2  # 하락 여부
            arrow = "▼" if falling else "▲"
            lines.append(f"{name}: {now_val:,.2f} ({arrow}{abs(change_val):,.2f}, {change_rate:+.2f}%)")
        except Exception:
            lines.append(_get_kr_index_fallback(name, code))
    return lines


def _get_kr_index_fallback(name, code):
    """네이버 API 실패 시 야후 파이낸스로 대체 조회"""
    import yfinance as yf

    ticker = "^KS11" if code == "KOSPI" else "^KQ11"
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        hist = hist.dropna(subset=["Close"])
        if len(hist) < 2:
            return f"{name}: 데이터 부족으로 조회 실패"
        last = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        change = last - prev
        pct = change / prev * 100
        arrow = "▲" if change >= 0 else "▼"
        return f"{name}: {last:,.2f} ({arrow}{abs(change):,.2f}, {pct:+.2f}%)"
    except Exception as e:
        return f"{name}: 조회 실패 ({e})"


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


def get_kr_top_movers(top_n=10):
    """시가총액 상위 종목들 중 상승률/하락률 상위 조회 (코스피+코스닥)"""
    items = []
    for sosok in ["0", "1"]:  # 0: 코스피, 1: 코스닥
        try:
            url = (
                "https://m.stock.naver.com/api/json/sise/siseListJson.nhn"
                f"?menu=market_sum&sosok={sosok}&pageSize=200&page=1"
            )
            data = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).json()
            for row in data:
                try:
                    items.append(
                        {
                            "name": row["nm"],
                            "price": float(row["nv"]),
                            "rate": float(row["cr"]),
                        }
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        except Exception:
            continue

    if not items:
        return ["급등/급락 종목 조회 실패"], ["급등/급락 종목 조회 실패"]

    gainers = sorted(items, key=lambda x: x["rate"], reverse=True)[:top_n]
    losers = sorted(items, key=lambda x: x["rate"])[:top_n]

    gainer_lines = [
        f"{i+1}. {s['name']} {s['price']:,.0f}원 (▲{s['rate']:.2f}%)" for i, s in enumerate(gainers)
    ]
    loser_lines = [
        f"{i+1}. {s['name']} {s['price']:,.0f}원 (▼{abs(s['rate']):.2f}%)" for i, s in enumerate(losers)
    ]
    return gainer_lines, loser_lines


def get_news_headlines(limit=5):
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
    """카카오톡 나에게 보내기는 텍스트 200자 제한이 있어 초과 시 자동으로 잘라서 전송"""
    if len(text) > 190:
        text = text[:187] + "..."
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
        return False
    print("카카오톡 전송 완료 (", len(text), "자)")
    return True


def chunk_lines(lines, max_len=190):
    """줄 목록을 200자 제한에 맞게 여러 묶음으로 분할"""
    chunks = []
    current = ""
    for line in lines:
        candidate = (current + "\n" + line) if current else line
        if len(candidate) > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def main():
    access_token, new_refresh_token = refresh_kakao_token()
    if new_refresh_token:
        update_github_secret(new_refresh_token)

    today = datetime.now().strftime("%Y년 %m월 %d일 (%a)")

    # 1. 지수 + 환율
    summary_lines = [f"📈 {today} 증시 브리핑\n", "[국내]"]
    summary_lines.extend(get_kr_indices())
    summary_lines.append("")
    summary_lines.append("[미국]")
    summary_lines.extend(get_us_indices())
    summary_lines.append("")
    summary_lines.append(get_usd_krw())

    # 2. 급등/급락 종목
    gainers, losers = get_kr_top_movers(top_n=10)
    gainer_lines = ["🔺 국내 상승률 TOP10"] + gainers
    loser_lines = ["🔻 국내 하락률 TOP10"] + losers

    # 3. 뉴스
    news_lines = ["[주요 뉴스]"] + [f"- {h}" for h in get_news_headlines()]

    all_messages = []
    all_messages.extend(chunk_lines(summary_lines))
    all_messages.extend(chunk_lines(gainer_lines))
    all_messages.extend(chunk_lines(loser_lines))
    all_messages.extend(chunk_lines(news_lines))

    for i, msg in enumerate(all_messages):
        print(f"--- 메시지 {i+1}/{len(all_messages)} ---")
        print(msg)
        ok = send_kakao_message(access_token, msg)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
