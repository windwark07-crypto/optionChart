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

    def closest_in_top5(rows, key_idx, descending=True):
        """
        key_idx 기준 상위 5개를 추린 뒤,
        close_price와 가장 가까운 Strike를 반환합니다.
        """
        filtered = [r for r in rows if r[key_idx] is not None]
        top5 = sorted(filtered, key=lambda r: r[key_idx], reverse=descending)[:5]
        if not top5:
            return None
        if close_price is not None:
            return min(top5, key=lambda r: abs(r[1] - close_price))
        return top5[0]

    today = date.today().strftime("%Y-%m-%d")

    lines = [
        f"📊 <b>[{ticker}] 옵션 OI 변동 알림</b>",
        f"📅 {today}",
    ]
    if close_price is not None:
        lines.append(f"💵 종가: <b>${close_price:,.2f}</b>")

    # Call OI
    call_top_inc = closest_in_top5(change_rows, key_idx=0, descending=True)
    call_top_dec = closest_in_top5(change_rows, key_idx=0, descending=False)
    lines += ["", "📈 <b>Call OI 변동</b>"]
    if call_top_inc:
        lines.append(f"  ▲ 최대증가  Strike: <b>{call_top_inc[1]:g}</b>  |  {fmt(call_top_inc[0])}")
    if call_top_dec:
        lines.append(f"  ▼ 최대감소  Strike: <b>{call_top_dec[1]:g}</b>  |  {fmt(call_top_dec[0])}")

    # Put OI
    put_top_inc = closest_in_top5(change_rows, key_idx=2, descending=True)
    put_top_dec = closest_in_top5(change_rows, key_idx=2, descending=False)
    lines += ["", "📉 <b>Put OI 변동</b>"]
    if put_top_inc:
        lines.append(f"  ▲ 최대증가  Strike: <b>{put_top_inc[1]:g}</b>  |  {fmt(put_top_inc[2])}")
    if put_top_dec:
        lines.append(f"  ▼ 최대감소  Strike: <b>{put_top_dec[1]:g}</b>  |  {fmt(put_top_dec[2])}")

    return "\n".join(lines)
