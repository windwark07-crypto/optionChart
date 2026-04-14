import logging
from datetime import date

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(token: str, chat_id: str, text: str) -> bool:
    """텔레그램 메시지를 전송합니다. 성공 여부를 반환합니다."""
    try:
        resp = requests.post(
            API_URL.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"텔레그램 메시지 전송 완료 (chat_id={chat_id})")
        return True
    except Exception as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return False


def format_top_movers(
    ticker: str,
    change_rows: list[list],
    close_price: float | None = None,
) -> str:
    """
    변동사항 행 목록에서 Call OI / Put OI 변동이 가장 큰 Strike를 찾아
    텔레그램 메시지 문자열로 반환합니다.

    change_rows: [[call_oi_diff, strike, put_oi_diff], ...]
    close_price: 해당 티커의 종가 (없으면 미표시)
    """
    if not change_rows:
        return f"[{ticker}] 비교할 데이터가 없습니다."

    def fmt(val):
        if val is None:
            return "N/A"
        sign = "+" if val > 0 else ""
        return f"{sign}{val:,}"

    today = date.today().strftime("%Y-%m-%d")

    lines = [
        f"📊 <b>[{ticker}] 옵션 OI 변동 알림</b>",
        f"📅 {today}",
    ]

    if close_price is not None:
        lines.append(f"💵 종가: <b>${close_price:,.2f}</b>")

        # 종가와 가장 근접한 Strike 선택
        atm = min(change_rows, key=lambda r: abs(r[1] - close_price))
        lines += [
            "",
            f"🎯 <b>ATM Strike: {atm[1]:g}</b>",
            f"  📈 Call OI 변동: {fmt(atm[0])}",
            f"  📉 Put OI 변동:  {fmt(atm[2])}",
        ]
    else:
        # 종가 없을 때 fallback: 변동 절댓값 최대 Strike
        top_call = max(change_rows, key=lambda r: abs(r[0]) if r[0] is not None else 0)
        top_put  = max(change_rows, key=lambda r: abs(r[2]) if r[2] is not None else 0)
        lines += [
            "",
            f"📈 <b>Call OI 최대 변동</b>",
            f"  Strike: <b>{top_call[1]:g}</b>  |  변동: {fmt(top_call[0])}",
            "",
            f"📉 <b>Put OI 최대 변동</b>",
            f"  Strike: <b>{top_put[1]:g}</b>  |  변동: {fmt(top_put[2])}",
        ]

    return "\n".join(lines)
