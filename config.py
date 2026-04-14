import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
TICKERS = [t.strip() for t in os.getenv("TICKERS", "QQQ,SPY").split(",") if t.strip()]
MAX_EXPIRATIONS = int(os.getenv("MAX_EXPIRATIONS", "0"))


def build_url(ticker: str) -> str:
    return f"https://optioncharts.io/options/{ticker}/option-chain"
