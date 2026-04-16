# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

미국 주식 옵션 체인 데이터를 매일 수집 → Google Sheets 저장 → 전일 대비 OI(미결제약정) 변동사항을 Telegram으로 알림 발송하는 자동화 도구.

## 실행 방법

```bash
# 가상환경 활성화 후 실행
.venv\Scripts\activate
python main.py

# 또는 Windows 배치 파일로 실행
run.bat
```

## 환경 설정

`.env` 파일에 아래 변수 설정 필요 (`.env.example` 참고):

| 변수 | 필수 | 설명 |
|------|------|------|
| `SPREADSHEET_ID` | O | Google Sheets 문서 ID |
| `GOOGLE_CREDENTIALS_PATH` | O | 서비스 계정 JSON 경로 (기본: `credentials/service_account.json`) |
| `TICKERS` | X | 수집 티커, 쉼표 구분 (기본: `QQQ,SPY`) |
| `MAX_EXPIRATIONS` | X | 가장 가까운 N개 만기일만 수집 (기본: `0` = 전체) |
| `TELEGRAM_BOT_TOKEN` | X | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | X | 텔레그램 채팅방 ID |

## 아키텍처 및 데이터 흐름

```
optioncharts.io
  (Playwright 크롤링)
  1순위: 네트워크 API 인터셉트 → JSON 파싱
  2순위: DOM 테이블 파싱 (fallback)
        ↓
  만기일 필터 (MAX_EXPIRATIONS)
        ↓
  Google Sheets
  ├── {TICKER}_YYYY-MM-DD 시트 (최대 2개 유지: 오늘 + 어제)
  │     재실행 시 clear() 후 재기록
  └── 변동사항 / 변동사항_{TICKER} 시트
        이전 날짜 시트 vs 오늘 시트 → Strike 기준 Call OI / Put OI 증감 계산
        ↓
  yfinance로 현재 종가 조회
        ↓
  Telegram 알림 (change_rows 있을 때만)
  └── Top 5 Call OI 증감 / Top 5 Put OI 증감 (ATM 기준 정렬)
```

## 파일별 역할

- **`main.py`** — 진입점. 로깅 초기화, 티커별 `collect_ticker()` 병렬 실행 (`asyncio.gather`)
- **`config.py`** — `.env` 로드, `build_url(ticker)` 제공
- **`scraper.py`** — Playwright 크롤링. `scrape_option_chain(url)` → `list[dict]` 반환
- **`sheets.py`** — `write_to_sheet()`: 데이터 시트 기록 + 변동사항 비교. 2장 유지 정책 및 `prev_ws` 관리 포함
- **`telegram.py`** — `format_top_movers()` + `send_message()`. HTML 포맷 알림

## 주요 설계 결정 사항

- **시트 2개 유지**: 오늘 + 어제만 보관. `prev_sheets[:-1]` 삭제 후 가장 최근 이전 시트(`prev_ws`)를 보존
- **재실행 안전성**: 오늘 시트가 이미 존재하면 `clear()` 후 재기록. `prev_ws`는 삭제하지 않으므로 재실행 시에도 전일 대비 비교 정상 동작
- **변동사항 시트 이름**: 티커가 1개면 `변동사항`, 2개 이상이면 `변동사항_{TICKER}` (`sheets.py:_change_sheet_name`)
- **첫 실행 또는 공통 Strike 없는 경우**: `change_rows`가 빈 리스트 → Telegram 미발송 (정상 동작)
- **2단계 크롤링**: 사이트 구조 변경에 대비해 API 인터셉트 실패 시 DOM 파싱으로 자동 전환

## 알려진 버그

- **[sheets.py:186-187](sheets.py#L186) `col.get(..., -1)`**: 컬럼 없을 때 `-1` 인덱스로 마지막 열 참조하는 버그