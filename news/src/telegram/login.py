"""One-time interactive Telegram login (phone + OTP).

Usage:
    python -m src.telegram.login

Connects with Telethon, prompts for phone number and OTP code, and
saves the session file to ``data/telegram_session/news_stream.session``.
Subsequent runs of ``refresher.py`` reuse this session without prompts.

Reads TELEGRAM_API_ID / TELEGRAM_API_HASH from ``information/.env``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent

SESSION_DIR = _PROJECT_ROOT / "data" / "telegram_session"
SESSION_PATH = str(SESSION_DIR / "news_stream")


def main() -> None:
    load_dotenv(_REPO_ROOT / ".env")
    load_dotenv(_PROJECT_ROOT / ".env", override=True)

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        print(
            "ERROR: Set TELEGRAM_API_ID and TELEGRAM_API_HASH in "
            f"{_PROJECT_ROOT / '.env'}"
        )
        sys.exit(1)

    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(SESSION_PATH, int(api_id), api_hash)
    client.start()
    print("Login successful — session saved to", SESSION_PATH + ".session")
    client.disconnect()


if __name__ == "__main__":
    main()
