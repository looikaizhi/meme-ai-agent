"""Authorize the Telegram user session used by GMGN discovery.

Run once in an interactive terminal:

    .venv/bin/python scripts/telegram_login.py

Telethon will ask for phone, login code, and possibly 2FA password. The saved
session file is reused by the non-interactive backend listener.
"""
from __future__ import annotations

import asyncio
import sys

from memedog.config import load_config
from memedog.discovery.gmgn_telegram import normalize_telegram_chat_ref


async def main() -> int:
    cfg = load_config()
    api_id = cfg.settings.telegram_api_id
    api_hash = cfg.settings.telegram_api_hash
    session = cfg.settings.telegram_session or "memedog_gmgn"

    if not api_id or not api_hash:
        print(
            "Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in .env",
            file=sys.stderr,
        )
        return 2

    try:
        from telethon import TelegramClient
    except ImportError:
        print(
            "Telethon is not installed. Run: .venv/bin/python -m pip install 'telethon>=1.36'",
            file=sys.stderr,
        )
        return 2

    client = TelegramClient(session, api_id, api_hash)
    await client.start()

    me = await client.get_me()
    username = getattr(me, "username", "") or getattr(me, "first_name", "") or "authorized"
    print(f"Telegram session authorized: {session} ({username})")

    chats = cfg.discovery.gmgn_chats or [cfg.discovery.gmgn_chat]
    for chat in chats:
        try:
            await client.get_entity(normalize_telegram_chat_ref(chat))
            print(f"GMGN chat reachable: {chat}")
        except Exception as exc:
            print(
                f"Warning: could not resolve GMGN chat {chat!r}: {exc}",
                file=sys.stderr,
            )

    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
