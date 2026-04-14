import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import config
from scraper import scrape_option_chain
from sheets import write_to_sheet
from telegram import format_top_movers, send_message

# ── 로깅 설정 ────────────────────────────────────────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


async def collect_ticker(ticker: str, creds_path: str) -> None:
    url = config.build_url(ticker)
    logger.info(f"[{ticker}] 수집 시작  |  URL: {url}")

    # ── 크롤링 ───────────────────────────────────────────────────────────────
    try:
        rows = await scrape_option_chain(url)
    except Exception as e:
        logger.error(f"[{ticker}] 크롤링 실패: {e}", exc_info=True)
        return

    if not rows:
        logger.error(f"[{ticker}] 수집된 데이터가 없습니다. 사이트 구조가 변경되었을 수 있습니다.")
        return

    logger.info(f"[{ticker}] 크롤링 완료: 총 {len(rows)}개 행")

    # 만기일 필터 (MAX_EXPIRATIONS > 0 이면 가장 가까운 N개만)
    if config.MAX_EXPIRATIONS > 0:
        expirations = sorted({r["expiration"] for r in rows if r["expiration"]})
        keep = set(expirations[: config.MAX_EXPIRATIONS])
        rows = [r for r in rows if r["expiration"] in keep or not r["expiration"]]
        logger.info(f"[{ticker}] 만기일 필터 적용: {list(keep)} → {len(rows)}행")

    # ── 구글 시트 기록 ────────────────────────────────────────────────────────
    try:
        written, change_rows = write_to_sheet(
            credentials_path=creds_path,
            spreadsheet_id=config.SPREADSHEET_ID,
            rows=rows,
            ticker=ticker,
            total_tickers=len(config.TICKERS),
        )
        logger.info(f"[{ticker}] 완료: {written}행 기록")
    except Exception as e:
        logger.error(f"[{ticker}] 구글 시트 기록 실패: {e}", exc_info=True)
        return

    # ── 텔레그램 알림 ─────────────────────────────────────────────────────────
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID and change_rows:
        message = format_top_movers(ticker, change_rows)
        send_message(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, message)


async def run():
    started_at = datetime.now()
    logger.info(f"=== 수집 시작: {started_at.strftime('%Y-%m-%d %H:%M:%S')} ===")
    logger.info(f"대상 티커: {config.TICKERS}")

    if not config.SPREADSHEET_ID:
        logger.error(".env 파일에 SPREADSHEET_ID가 설정되지 않았습니다.")
        sys.exit(1)

    creds_path = Path(config.GOOGLE_CREDENTIALS_PATH)
    if not creds_path.exists():
        logger.error(f"서비스 계정 파일을 찾을 수 없습니다: {creds_path}")
        sys.exit(1)

    for ticker in config.TICKERS:
        await collect_ticker(ticker, str(creds_path))

    logger.info(f"=== 전체 완료 ===")




if __name__ == "__main__":
    asyncio.run(run())
