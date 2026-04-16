import logging
import re
import time
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

DATA_HEADERS = [
    "Call Volume",
    "Call Open Interest",
    "Strike",
    "Put Volume",
    "Put Open Interest",
]

CHANGE_HEADERS = ["Call Open Interest", "Strike", "Put Open Interest"]


def _change_sheet_name(ticker: str, total_tickers: int) -> str:
    if total_tickers > 1:
        return f"변동사항_{ticker}"
    return "변동사항"


def _retry(fn, retries=3, delay=5, backoff=2):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = delay * (backoff ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)


def get_client(credentials_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.Client(auth=creds)


def write_to_sheet(
    credentials_path: str,
    spreadsheet_id: str,
    rows: list[dict],
    ticker: str = "QQQ",
    total_tickers: int = 1,
) -> tuple[int, list[list]]:
    """
    1. 데이터 시트({TICKER}_YYYY-MM-DD)를 최대 2개 유지
       - 수집 전 기존 시트가 2개면 가장 오래된 시트 삭제
    2. 오늘 날짜 시트에 데이터 기록
    3. 이전 시트가 존재하면 '변동사항' 시트에 Call OI / Put OI 증감 기록

    반환: (기록된 행 수, 변동사항 행 목록[[call_oi_diff, strike, put_oi_diff], ...])
    """
    if not rows:
        logger.warning("추가할 데이터가 없습니다.")
        return 0, []

    client = get_client(credentials_path)
    spreadsheet = client.open_by_key(spreadsheet_id)

    # ── 1. 기존 데이터 시트 목록 조회 ────────────────────────────────────────
    pattern = re.compile(rf'^{re.escape(ticker)}_\d{{4}}-\d{{2}}-\d{{2}}$')
    all_ws = spreadsheet.worksheets()
    data_sheets = sorted(
        [ws for ws in all_ws if pattern.match(ws.title)],
        key=lambda ws: ws.title,   # 날짜 오름차순
    )

    # ── 2. 오늘 날짜 시트 이름 결정 ─────────────────────────────────────────
    sheet_name = f"{ticker}_{date.today().strftime('%Y-%m-%d')}"

    # ── 3. 오늘 시트를 제외한 이전 시트가 2개 초과이면 오래된 것부터 삭제 ────
    # 목표: 이전 시트 최대 1개 유지 → 오늘 시트 추가 시 총 2개 유지
    prev_sheets = [ws for ws in data_sheets if ws.title != sheet_name]
    for ws in prev_sheets[:-1]:  # 가장 최근 1개만 남기고 나머지 삭제
        spreadsheet.del_worksheet(ws)
        logger.info(f"오래된 시트 '{ws.title}' 삭제됨")

    # 비교에 사용할 이전 시트 (재실행 시에도 이전 날짜 시트가 있으면 비교)
    prev_ws = prev_sheets[-1] if prev_sheets else None

    try:
        new_ws = spreadsheet.worksheet(sheet_name)
        new_ws.clear()
    except gspread.WorksheetNotFound:
        new_ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(DATA_HEADERS))
        logger.info(f"워크시트 '{sheet_name}' 생성됨")

    new_ws.format("A:E", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    new_ws.append_row(DATA_HEADERS, value_input_option="RAW")

    new_rows = [
        [
            r.get("call_volume", ""),
            r.get("call_oi", ""),
            r.get("strike", ""),
            r.get("put_volume", ""),
            r.get("put_oi", ""),
        ]
        for r in rows
    ]
    _retry(lambda: new_ws.append_rows(new_rows, value_input_option="RAW"))
    logger.info(f"{len(new_rows)}행을 '{sheet_name}' 시트에 기록했습니다.")

    # ── 4. 이전 시트와 비교 → '변동사항' 시트 기록 ──────────────────────────
    change_rows: list[list] = []
    if prev_ws:
        change_rows = _write_changes(spreadsheet, prev_ws, new_ws, ticker, total_tickers)

    return len(new_rows), change_rows


def _write_changes(
    spreadsheet: gspread.Spreadsheet,
    prev_ws: gspread.Worksheet,
    new_ws: gspread.Worksheet,
    ticker: str = "QQQ",
    total_tickers: int = 1,
) -> list[list]:
    """
    두 시트의 동일 Strike 기준으로 Call OI / Put OI 증감을 계산해
    '변동사항' 시트에 기록합니다. (기존 내용 덮어쓰기)

    반환: [[call_oi_diff, strike, put_oi_diff], ...]
    """
    # 이전/최신 데이터를 Strike → row 딕셔너리로 변환
    prev_data = _sheet_to_dict(prev_ws)
    new_data  = _sheet_to_dict(new_ws)

    # 두 시트 모두에 존재하는 Strike만 비교, Strike 오름차순 정렬
    common_strikes = sorted(prev_data.keys() & new_data.keys())

    change_rows = []
    for strike in common_strikes:
        old = prev_data[strike]
        new = new_data[strike]

        call_oi_diff = _safe_int(new.get("call_oi")) - _safe_int(old.get("call_oi"))
        put_oi_diff  = _safe_int(new.get("put_oi"))  - _safe_int(old.get("put_oi"))

        change_rows.append([call_oi_diff, strike, put_oi_diff])

    # '변동사항' 시트 찾기 / 없으면 생성 후 덮어쓰기
    change_sheet = _change_sheet_name(ticker, total_tickers)
    try:
        cws = spreadsheet.worksheet(change_sheet)
        cws.clear()
    except gspread.WorksheetNotFound:
        cws = spreadsheet.add_worksheet(title=change_sheet, rows=1000, cols=len(CHANGE_HEADERS))
        logger.info(f"워크시트 '{change_sheet}' 생성됨")

    cws.format("A:C", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    cws.append_row(CHANGE_HEADERS, value_input_option="RAW")

    if change_rows:
        _retry(lambda: cws.append_rows(change_rows, value_input_option="RAW"))

    logger.info(
        f"'{change_sheet}' 시트에 {len(change_rows)}개 Strike 증감 기록 "
        f"({prev_ws.title} → {new_ws.title})"
    )
    return change_rows


def _sheet_to_dict(ws: gspread.Worksheet) -> dict[float, dict]:
    """
    워크시트 데이터를 Strike(float) → {call_oi, put_oi, ...} 딕셔너리로 변환합니다.
    첫 번째 행은 헤더로 간주합니다.
    """
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return {}

    header = [h.strip() for h in all_values[0]]
    col = {name: i for i, name in enumerate(header)}

    result = {}
    for row in all_values[1:]:
        try:
            strike = float(row[col["Strike"]].replace(",", ""))
        except (ValueError, KeyError, IndexError):
            continue

        call_oi_idx = col.get("Call Open Interest")
        put_oi_idx  = col.get("Put Open Interest")
        result[strike] = {
            "call_oi": row[call_oi_idx] if call_oi_idx is not None and call_oi_idx < len(row) else "",
            "put_oi":  row[put_oi_idx]  if put_oi_idx  is not None and put_oi_idx  < len(row) else "",
        }
    return result


def _safe_int(val) -> int:
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0
