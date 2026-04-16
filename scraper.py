import asyncio
import logging
from playwright.async_api import async_playwright, Response

logger = logging.getLogger(__name__)


async def scrape_option_chain(url: str) -> list[dict]:
    """
    Playwright로 옵션 체인 페이지를 크롤링합니다.
    네트워크 인터셉트로 API 응답을 우선 수집하고,
    실패 시 DOM 파싱으로 fallback합니다.

    반환 형식:
    [
        {
            "expiration": "2025-04-18",
            "strike": 450.0,
            "call_volume": 1234,
            "call_oi": 5678,
            "put_volume": 910,
            "put_oi": 1112,
        },
        ...
    ]
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            # ── 1. 네트워크 인터셉트로 API 응답 수집 ────────────────────────────
            captured: list[dict] = []

            async def on_response(response: Response):
                url_lower = response.url.lower()
                if response.status != 200:
                    return
                # JSON 형식이면서 option 관련 엔드포인트 수집
                if "option" in url_lower or "chain" in url_lower:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        try:
                            body = await response.json()
                            captured.append({"url": response.url, "data": body})
                            logger.debug(f"API 응답 캡처: {response.url}")
                        except Exception:
                            pass

            page.on("response", on_response)

            logger.info(f"페이지 로딩 중: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            # 데이터 렌더링 대기 (테이블 또는 특정 셀 등장 기다림)
            try:
                await page.wait_for_selector("table", timeout=20_000)
            except Exception:
                logger.warning("table 요소를 찾지 못했습니다. 5초 추가 대기.")
                await asyncio.sleep(5)

            await page.wait_for_load_state("networkidle", timeout=30_000)

            # ── 2. API 응답에서 데이터 파싱 시도 ────────────────────────────────
            if captured:
                result = _parse_api_responses(captured)
                if result:
                    logger.info(f"API 인터셉트 성공: {len(result)}개 행 수집")
                    return result
                logger.warning("API 응답 파싱 실패 — DOM 파싱으로 전환")

            # ── 3. DOM 파싱 fallback ─────────────────────────────────────────────
            result = await _parse_dom(page)
            logger.info(f"DOM 파싱 완료: {len(result)}개 행 수집")
            return result
        finally:
            await browser.close()


# ── API 응답 파싱 ────────────────────────────────────────────────────────────

def _parse_api_responses(captured: list[dict]) -> list[dict]:
    """캡처된 API 응답들에서 옵션 데이터를 추출합니다."""
    for item in captured:
        data = item["data"]
        rows = _extract_from_json(data)
        if rows:
            return rows
    return []


def _extract_from_json(data) -> list[dict]:
    """JSON 구조에서 재귀적으로 옵션 데이터 목록을 찾습니다."""
    if isinstance(data, list) and data:
        # 첫 번째 항목에 strike 관련 키가 있으면 파싱 시도
        first = data[0]
        if isinstance(first, dict):
            rows = _parse_row_list(data)
            if rows:
                return rows

    if isinstance(data, dict):
        # 중첩된 데이터 구조 탐색
        for key in ("data", "options", "chain", "calls", "result", "rows"):
            if key in data:
                rows = _extract_from_json(data[key])
                if rows:
                    return rows
        # 만기별로 분리된 구조: {"2025-04-18": [...], ...}
        combined = []
        for key, val in data.items():
            if isinstance(val, list):
                rows = _extract_from_json(val)
                if rows:
                    # expiration 키 추가
                    for r in rows:
                        if not r.get("expiration"):
                            r["expiration"] = key
                    combined.extend(rows)
        return combined

    return []


def _parse_row_list(rows: list[dict]) -> list[dict]:
    """행 목록에서 strike/volume/OI 컬럼을 찾아 표준 형식으로 변환합니다."""
    result = []
    for row in rows:
        d_lower = {k.lower(): v for k, v in row.items()}
        strike = _find_key(row, ("strike", "strikePrice", "strike_price", "Strike"), d_lower)
        if strike is None:
            continue

        expiration = _find_key(row, ("expiration", "expiry", "expirationDate", "exp", "date"), d_lower)

        # Calls
        call_vol = _find_nested(row, "call", ("volume", "vol", "Volume"), d_lower)
        call_oi  = _find_nested(row, "call", ("openInterest", "open_interest", "oi", "OI"), d_lower)

        # Puts
        put_vol  = _find_nested(row, "put",  ("volume", "vol", "Volume"), d_lower)
        put_oi   = _find_nested(row, "put",  ("openInterest", "open_interest", "oi", "OI"), d_lower)

        # flat 구조 fallback
        if call_vol is None:
            call_vol = _find_key(row, ("callVolume", "call_volume", "cVolume", "c_volume"), d_lower)
        if call_oi is None:
            call_oi  = _find_key(row, ("callOI", "call_oi", "callOpenInterest"), d_lower)
        if put_vol is None:
            put_vol  = _find_key(row, ("putVolume", "put_volume", "pVolume", "p_volume"), d_lower)
        if put_oi is None:
            put_oi   = _find_key(row, ("putOI", "put_oi", "putOpenInterest"), d_lower)

        result.append({
            "expiration": str(expiration) if expiration is not None else "",
            "strike":     float(strike),
            "call_volume": _to_int(call_vol),
            "call_oi":    _to_int(call_oi),
            "put_volume": _to_int(put_vol),
            "put_oi":     _to_int(put_oi),
        })
    return result


def _find_key(d: dict, keys: tuple, d_lower: dict | None = None):
    for k in keys:
        if k in d:
            return d[k]
    # 대소문자 무시 검색
    if d_lower is None:
        d_lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in d_lower:
            return d_lower[k.lower()]
    return None


def _find_nested(d: dict, prefix: str, keys: tuple, d_lower: dict | None = None):
    """call.volume, put.oi 등 중첩 키 탐색."""
    if d_lower is None:
        d_lower = {k.lower(): v for k, v in d.items()}
    for k, v in d_lower.items():
        if prefix in k and isinstance(v, dict):
            result = _find_key(v, keys)
            if result is not None:
                return result
    return None


def _to_int(val) -> int | None:
    if val is None:
        return None
    s = str(val).replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


# ── DOM 파싱 ─────────────────────────────────────────────────────────────────

async def _parse_dom(page) -> list[dict]:
    """
    테이블 DOM을 파싱해 옵션 데이터를 추출합니다.

    실제 페이지 구조 (thead 마지막 행 기준):
      0: Call Last Price | 1: Call Bid | 2: Call Ask | 3: Call Volume | 4: Call OI
      5: Strike
      6: Put Last Price  | 7: Put Bid  | 8: Put Ask  | 9: Put Volume  | 10: Put OI

    Strike 위치를 기준으로 나머지 인덱스를 동적으로 계산합니다.
    """
    rows = await page.evaluate("""
    () => {
        const tables = document.querySelectorAll('table');
        if (!tables.length) return [];

        // 가장 행이 많은 테이블 선택
        let target = tables[0];
        tables.forEach(t => {
            if (t.rows.length > target.rows.length) target = t;
        });

        // thead의 마지막 행에서 헤더 읽기 (2행 헤더 대응)
        const theadRows = target.querySelectorAll('thead tr');
        const lastHeaderRow = theadRows[theadRows.length - 1];
        const headers = [...lastHeaderRow.querySelectorAll('th, td')]
            .map(th => th.innerText.trim().toLowerCase());

        // Strike 위치 탐지
        const strikeIdx = headers.findIndex(h => h === 'strike' || h.includes('strike'));
        if (strikeIdx === -1) return [];

        // Strike 기준 상대 위치로 각 컬럼 인덱스 계산
        // Calls: [Last Price, Bid, Ask, Volume, OI] → Volume = strike-2, OI = strike-1
        // Puts:  [Last Price, Bid, Ask, Volume, OI] → Volume = strike+4, OI = strike+5
        const cVolIdx = strikeIdx - 2;
        const cOIIdx  = strikeIdx - 1;
        const pVolIdx = strikeIdx + 4;
        const pOIIdx  = strikeIdx + 5;

        const result = [];
        const bodyRows = target.querySelectorAll('tbody tr');
        bodyRows.forEach(tr => {
            const cells = tr.querySelectorAll('td');
            const get = (i) => {
                if (i < 0 || i >= cells.length) return null;
                return cells[i].innerText.trim().replace(/,/g, '');
            };

            const strikeVal = get(strikeIdx);
            if (!strikeVal || isNaN(parseFloat(strikeVal))) return;

            const toInt = (v) => {
                if (!v || v === '-') return null;
                const n = parseInt(v);
                return isNaN(n) ? null : n;
            };

            result.push({
                strike:      parseFloat(strikeVal),
                call_volume: toInt(get(cVolIdx)),
                call_oi:     toInt(get(cOIIdx)),
                put_volume:  toInt(get(pVolIdx)),
                put_oi:      toInt(get(pOIIdx)),
            });
        });
        return result;
    }
    """)

    # expiration은 DOM에서 별도로 감지 (페이지 제목, select 등)
    expiration = await _detect_expiration(page)
    for r in rows:
        r.setdefault("expiration", expiration)

    return rows


async def _detect_expiration(page) -> str:
    """현재 선택된 만기일을 페이지에서 감지합니다."""
    try:
        # select, 드롭다운, 텍스트 등 다양한 위치 시도
        val = await page.evaluate("""
        () => {
            const sel = document.querySelector('select[name*="expir"], select[id*="expir"]');
            if (sel) return sel.value || sel.options[sel.selectedIndex]?.text || '';

            const spans = [...document.querySelectorAll('span, div, button')];
            for (const el of spans) {
                const t = el.innerText.trim();
                if (/\\d{4}-\\d{2}-\\d{2}/.test(t)) return t.match(/\\d{4}-\\d{2}-\\d{2}/)[0];
            }
            return '';
        }
        """)
        return val.strip()
    except Exception:
        return ""
