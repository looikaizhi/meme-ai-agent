"""Inspect Telegram dialogs and recent messages for GMGN alert setup.

Run after ``scripts/telegram_login.py`` has authorized the session:

    .venv/bin/python scripts/telegram_diagnose.py

The script prints candidate chats and whether recent messages contain parsable
Solana mint addresses. It does not print Telegram credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from memedog.config import load_config
from memedog.discovery.gmgn_telegram import (
    normalize_telegram_chat_ref,
    parse_gmgn_solana_alerts,
)


def _entity_name(entity) -> str:
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    first_name = getattr(entity, "first_name", None)
    if title:
        return title
    if username:
        return f"@{username}"
    return first_name or str(getattr(entity, "id", "unknown"))


def _preview(text: str, width: int = 140) -> str:
    one_line = " ".join((text or "").split())
    return one_line[:width]


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--messages", type=int, default=8)
    parser.add_argument(
        "--no-age-filter",
        action="store_true",
        help="Do not require GMGN Open age to be within configured freshness window.",
    )
    parser.add_argument(
        "--show-samples",
        type=int,
        default=0,
        help="Print this many recent message previews per candidate chat.",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    api_id = cfg.settings.telegram_api_id
    api_hash = cfg.settings.telegram_api_hash
    session = cfg.settings.telegram_session or "memedog_gmgn"
    max_open_age_min = (
        None if args.no_age_filter else cfg.discovery.gmgn_max_open_age_min
    )
    if not api_id or not api_hash:
        print("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in .env", file=sys.stderr)
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
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print(
                "Telegram session is not authorized. Run: "
                ".venv/bin/python scripts/telegram_login.py",
                file=sys.stderr,
            )
            return 3

        print(f"Session authorized: {session}")
        configured_chats = cfg.discovery.gmgn_chats or [cfg.discovery.gmgn_chat]
        print(f"Configured GMGN chats: {configured_chats}")
        for chat in configured_chats:
            chat_ref = normalize_telegram_chat_ref(chat)
            try:
                configured = await client.get_entity(chat_ref)
                print(
                    "  resolved: "
                    f"{chat!r} -> id={getattr(configured, 'id', '')} "
                    f"name={_entity_name(configured)}"
                )
                parsed_any = False
                shown_samples = 0
                async for message in client.iter_messages(configured, limit=args.messages):
                    text = getattr(message, "raw_text", "") or ""
                    if args.show_samples and shown_samples < args.show_samples:
                        print(f"    sample={_preview(text)}")
                        shown_samples += 1
                    alerts = parse_gmgn_solana_alerts(
                        text,
                        max_open_age_min=max_open_age_min,
                        launch_only=True,
                    )
                    if alerts:
                        parsed_any = True
                        for alert in alerts:
                            print(
                                f"    parsable mint={alert.mint} "
                                f"creator={alert.author or '(blank)'} "
                                f"lp={alert.liquidity_pool or '(blank)'}"
                            )
                        print(f"    preview={_preview(text)}")
                        break
                if not parsed_any:
                    print("    no parsable recent Solana launch alert in sampled messages")
            except Exception as exc:
                print(
                    f"  did not resolve: {chat!r} "
                    f"({type(exc).__name__}: {exc})"
                )

        keywords = ("gmgn", "alert", "signal", "new token", "pump", "launch")
        matches = []
        async for dialog in client.iter_dialogs(limit=args.limit):
            entity = dialog.entity
            name = _entity_name(entity)
            username = getattr(entity, "username", "") or ""
            haystack = f"{name} {username}".lower()
            if any(keyword in haystack for keyword in keywords):
                matches.append(dialog)

        print(f"Candidate dialogs found: {len(matches)}")
        for dialog in matches[:20]:
            entity = dialog.entity
            print(
                f"- id={getattr(entity, 'id', '')} "
                f"username={getattr(entity, 'username', '') or ''} "
                f"name={_entity_name(entity)}"
            )
            parsed_any = False
            shown_samples = 0
            async for message in client.iter_messages(entity, limit=args.messages):
                text = getattr(message, "raw_text", "") or ""
                if args.show_samples and shown_samples < args.show_samples:
                    print(f"  sample={_preview(text)}")
                    shown_samples += 1
                alerts = parse_gmgn_solana_alerts(
                    text,
                    max_open_age_min=max_open_age_min,
                    launch_only=True,
                )
                if alerts:
                    parsed_any = True
                    for alert in alerts:
                        print(
                            f"  parsable mint={alert.mint} "
                            f"creator={alert.author or '(blank)'} "
                            f"lp={alert.liquidity_pool or '(blank)'}"
                        )
                    print(f"  preview={_preview(text)}")
                    break
            if not parsed_any:
                print("  no parsable recent Solana launch alert in sampled messages")

        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
