# 코드 분석 보고서

**분석 일자:** 2026-04-16  
**분석 파일:** `config.py`, `main.py`, `scraper.py`, `sheets.py`, `telegram.py`

---

## 요약

| 등급 | 건수 | 주요 내용 |
|------|------|----------|
| Medium | 5 | 코드 안정성, 가독성, 리팩토링 |
| Low | 3 | 최적화, 스타일 개선 |

---

## Medium (계획적 개선)

### #9 — Browser context 명시적 close 없음 (리소스 누수 가능성)

**파일:** `scraper.py:31-85`

**문제:**  
`browser.new_context()`로 생성한 context가 `finally`에서 명시적으로 닫히지 않음.  
현재는 `browser.close()`로 암묵적 정리되나, 코드 변경 시 리소스 누수 위험.

**개선 코드:**
```python
browser = await p.chromium.launch(headless=True)
try:
    context = await browser.new_context(...)
    try:
        page = await context.new_page()
        ...
    finally:
        await context.close()
finally:
    await browser.close()
```

---

### #10 — `config.py`에서 잘못된 환경변수 값으로 crash 가능

**파일:** `config.py:9`

**문제:**  
`int(os.getenv("MAX_EXPIRATIONS", "0"))`에서 환경변수가 정수가 아닌 경우 (예: `MAX_EXPIRATIONS=all`) 모듈 import 시점에 `ValueError` 발생.

**개선 코드:**
```python
try:
    MAX_EXPIRATIONS = int(os.getenv("MAX_EXPIRATIONS", "0"))
except ValueError:
    MAX_EXPIRATIONS = 0
    print("WARNING: MAX_EXPIRATIONS must be an integer; defaulting to 0 (all expirations)")
```

---

### #11 — async 함수 내 `sys.exit(1)` 호출

**파일:** `main.py:96, 101`

**문제:**  
`sys.exit(1)`은 `SystemExit`을 발생시키며, async 함수 내에서 호출 시 이벤트 루프가 비정상 종료될 수 있음.

**개선 코드:**
```python
# run() 내부:
if not config.SPREADSHEET_ID:
    raise ValueError(".env 파일에 SPREADSHEET_ID가 설정되지 않았습니다.")

creds_path = Path(config.GOOGLE_CREDENTIALS_PATH)
if not creds_path.exists():
    raise FileNotFoundError(f"서비스 계정 파일을 찾을 수 없습니다: {creds_path}")

# __main__ 블록:
if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (ValueError, FileNotFoundError) as e:
        logger.critical(str(e))
        sys.exit(1)
```

---

### #12 — `telegram.py`에서 매직 인덱스 번호 사용

**파일:** `telegram.py:81-96`

**문제:**  
`key_idx=0`, `r[1]`, `r[2]` 등 숫자 인덱스를 직접 사용 → 리스트 구조 변경 시 전체 수정 필요.

**개선 코드:**
```python
from typing import NamedTuple

class ChangeRow(NamedTuple):
    call_oi_diff: int | None
    strike: float
    put_oi_diff: int | None

# 사용 시:
lines.append(f"  ▲ 최대증가  Strike: <b>{call_top_inc.strike:g}</b>  |  {fmt(call_top_inc.call_oi_diff)}")
```

---

### #13 — 만기일 감지 실패 시 로그 없이 빈 문자열 반환

**파일:** `scraper.py:284-303`

**문제:**  
`except Exception: return ""`로 모든 오류를 무시 → 감지 실패 시 원인 파악 불가.

**개선 코드:**
```python
async def _detect_expiration(page) -> str:
    try:
        val = await page.evaluate(""" ... """)
        return val.strip()
    except Exception as e:
        logger.warning(f"만기일 감지 실패 (DOM fallback): {e}")
        return ""
```

---

## Low (여유 있을 때)

### #14 — 로그 파일 무한 누적

**파일:** `main.py:23-27`

**문제:**  
날짜별 로그 파일(`run_YYYYMMDD.log`)이 계속 쌓이며 자동 정리 없음.

**개선 코드:**
```python
from logging.handlers import TimedRotatingFileHandler

TimedRotatingFileHandler(
    LOG_DIR / "run.log",
    when="midnight",
    backupCount=7,      # 7일치만 보관
    encoding="utf-8",
)
```

---

### #15 — 내부 함수가 매 호출마다 재생성

**파일:** `telegram.py:58-69`

**문제:**  
`format_top_movers` 내부에 `closest_in_top5`, `fmt` 함수가 정의되어 호출마다 함수 객체가 새로 생성됨.

**개선 방향:**  
클로저 의존성이 없는 경우 모듈 레벨 함수로 분리.

---

### #16 — `_extract_from_json`에서 입력 딕셔너리 직접 변경

**파일:** `scraper.py:122-127`

**문제:**  
`r["expiration"] = key`로 입력 딕셔너리를 직접 변경 → 공유 참조가 있을 경우 예기치 않은 부작용 발생 가능.

**개선 코드:**
```python
combined.extend(
    {**r, "expiration": key} if not r.get("expiration") else r
    for r in rows
)
```

---

## 잘 된 점

- **모듈 분리 구조:** `config`, `scraper`, `sheets`, `telegram`, `main` 각 파일이 단일 책임을 명확히 가짐
- **스크래퍼 이중 폴백 전략:** 네트워크 인터셉트 → DOM 파싱 순서의 프로덕션 수준 접근법
- **Playwright async 올바른 사용:** `page.on("response", ...)` 네트워크 인터셉트, `finally`에서 browser close
- **시트 관리 설계:** 어제/오늘 2장만 유지하고 Strike 기준으로 diff 계산하는 구조가 깔끔함
- **`format_top_movers` 입력 검증:** 처리 전 행 형식 검증 및 폴백 메시지 처리
