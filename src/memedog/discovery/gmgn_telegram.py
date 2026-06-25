"""GMGN Telegram alert listener for Solana token discovery."""
from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from memedog.discovery.buffer import MintBuffer

logger = logging.getLogger(__name__)

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_SOLANA_MINT_RE = re.compile(
    rf"(?<![{_BASE58_ALPHABET}])([{_BASE58_ALPHABET}]{{32,44}})(?![{_BASE58_ALPHABET}])"
)
_LABELED_MINT_RE = re.compile(
    rf"(?i)\b(?:ca|mint|contract|contract\s+address|token\s+address)\s*[:：]\s*"
    rf"([{_BASE58_ALPHABET}]{{32,44}})"
)
_SOLANA_URL_MINT_RE = re.compile(
    rf"(?i)\b(?:solscan\.io/token|dexscreener\.com/solana|gmgn\.ai/sol/token|pump\.fun)"
    rf"/([{_BASE58_ALPHABET}]{{32,44}})"
)
_AUTHOR_RE = re.compile(
    rf"(?i)\b(?:author|creator|deployer|developer|dev|owner)\s*"
    rf"(?:address|wallet)?\s*[:：]\s*([{_BASE58_ALPHABET}]{{32,44}})"
)
_LIQUIDITY_POOL_RE = re.compile(
    rf"(?i)\b(?:lp|pool|pair|liquidity\s+pool)\s*"
    rf"(?:address)?\s*[:：]\s*([{_BASE58_ALPHABET}]{{32,44}})"
)
_OPEN_AGE_RE = re.compile(
    r"(?i)\bopen\s*[:：]\s*(\d+(?:\.\d+)?)\s*"
    r"(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)"
    r"\s+ago\b"
)
_EVM_CONTRACT_RE = re.compile(r"(?i)\b0x[a-f0-9]{40}\b")
_LAUNCH_KEYWORDS = (
    "new pool",
    "new lp",
    "new pair",
    "new token",
    "new launch",
    "just launched",
    "launch",
    "pool created",
    "pair created",
    "liquidity added",
    "raydium launch",
    "pump filled",
    "pump token launched",
    "打满",
    "秒满",
    "已满",
    "新池",
    "新币",
    "新代币",
)
_NON_LAUNCH_KEYWORDS = (
    "dev sold",
    "dev bought",
    "king of the hill",
    "koth",
    "fdv surge",
    "burn alert",
    "lp burn",
)


@dataclass(frozen=True)
class GMGNTokenAlert:
    """Token addresses extracted from a GMGN Telegram alert."""

    mint: str
    author: str = ""
    liquidity_pool: str = ""
    open_age_min: float | None = None


ChatRef = str | int


def normalize_telegram_chat_ref(chat: ChatRef) -> ChatRef:
    """Return a Telethon-friendly chat reference.

    Usernames stay strings. Numeric group/channel ids from config are converted
    to integers so private ``-100...`` channel ids work too.
    """
    if isinstance(chat, int):
        return chat
    stripped = str(chat).strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


def normalize_telegram_chat_refs(chats: ChatRef | Sequence[ChatRef]) -> ChatRef | list[ChatRef]:
    """Normalize one or many Telegram chat references for Telethon."""
    if isinstance(chats, str | int):
        return normalize_telegram_chat_ref(chats)
    return [normalize_telegram_chat_ref(chat) for chat in chats]


def parse_open_age_min(text: str | None) -> float | None:
    """Parse GMGN ``Open: 6s ago`` / ``Open: 2min ago`` text into minutes."""
    if not text:
        return None
    match = _OPEN_AGE_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("s"):
        return value / 60.0
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return value
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return value * 60.0
    if unit in {"d", "day", "days"}:
        return value * 24.0 * 60.0
    return None


def is_gmgn_launch_alert(text: str | None) -> bool:
    """Return True when GMGN text looks like a launch/new-pool alert."""
    if not text:
        return False
    lowered = " ".join(text.lower().split())
    if any(keyword in lowered for keyword in _NON_LAUNCH_KEYWORDS):
        return False
    return any(keyword in lowered for keyword in _LAUNCH_KEYWORDS)


def parse_gmgn_solana_alerts(
    text: str | None,
    *,
    max_open_age_min: int | float | None = None,
    launch_only: bool = False,
) -> list[GMGNTokenAlert]:
    """Extract Solana token alerts from GMGN Telegram text.

    The parser intentionally accepts only Solana base58-looking addresses.
    EVM/BSC ``0x...`` contracts are ignored so this feed cannot accidentally
    route BSC alerts into the Solana-only downstream pipeline.
    """
    if not text:
        return []
    if launch_only and not is_gmgn_launch_alert(text):
        return []

    open_age_min = parse_open_age_min(text)
    if max_open_age_min is not None and open_age_min is not None:
        if open_age_min > max_open_age_min:
            return []
    elif max_open_age_min is not None and not launch_only:
        if open_age_min is None or open_age_min > max_open_age_min:
            return []

    evm_spans = [match.span() for match in _EVM_CONTRACT_RE.finditer(text)]
    author_matches = list(_AUTHOR_RE.finditer(text))
    author_spans = [match.span(1) for match in author_matches]
    pool_matches = list(_LIQUIDITY_POOL_RE.finditer(text))
    pool_spans = [match.span(1) for match in pool_matches]
    candidates: list[tuple[int, str]] = []

    def _inside_evm_contract(start: int) -> bool:
        return any(span_start <= start < span_end for span_start, span_end in evm_spans)

    def _inside_author(start: int) -> bool:
        return any(span_start <= start < span_end for span_start, span_end in author_spans)

    def _inside_pool(start: int) -> bool:
        return any(span_start <= start < span_end for span_start, span_end in pool_spans)

    for regex in (_LABELED_MINT_RE, _SOLANA_URL_MINT_RE, _SOLANA_MINT_RE):
        for match in regex.finditer(text):
            start = match.start(1)
            if (
                not _inside_evm_contract(start)
                and not _inside_author(start)
                and not _inside_pool(start)
            ):
                candidates.append((start, match.group(1)))

    seen: set[str] = set()
    mints: list[str] = []
    for _start, mint in sorted(candidates, key=lambda item: item[0]):
        if mint not in seen:
            seen.add(mint)
            mints.append(mint)

    author = ""
    for match in author_matches:
        if not _inside_evm_contract(match.start(1)):
            author = match.group(1)
            break

    liquidity_pool = ""
    for match in pool_matches:
        if not _inside_evm_contract(match.start(1)):
            liquidity_pool = match.group(1)
            break

    return [
        GMGNTokenAlert(
            mint=mint,
            author=author if author != mint else "",
            liquidity_pool=liquidity_pool if liquidity_pool != mint else "",
            open_age_min=open_age_min,
        )
        for mint in mints
    ]


def parse_gmgn_solana_mints(text: str | None) -> list[str]:
    """Extract only Solana mint addresses from GMGN Telegram alert text."""
    return [alert.mint for alert in parse_gmgn_solana_alerts(text)]


class GMGNTelegramFeed:
    """Read GMGN Telegram alert messages and add discovered mints to a buffer.

    The Telethon dependency is imported lazily when ``run`` starts. Constructing
    this feed is side-effect free: no Telegram session file is touched and no
    network connection is opened until the background feed actually runs.
    """

    def __init__(
        self,
        buffer: MintBuffer,
        *,
        api_id: int,
        api_hash: str,
        session: str,
        chat: ChatRef | Sequence[ChatRef],
        store: Any | None = None,
        author_resolver: Callable[[str], Awaitable[str | None]] | None = None,
        client_factory: Callable[[str, int, str], Any] | None = None,
        new_message_factory: Callable[..., Any] | None = None,
        backoff_initial: float = 1.0,
        backoff_max: float = 30.0,
        backfill_limit: int = 0,
        max_open_age_min: int | float | None = None,
        launch_only: bool = True,
    ) -> None:
        self._buffer = buffer
        self._api_id = api_id
        self._api_hash = api_hash
        self._session = session
        self._chat = normalize_telegram_chat_refs(chat)
        self._store = store
        self._author_resolver = author_resolver
        self._client_factory = client_factory or self._default_client_factory
        self._new_message_factory = (
            new_message_factory or self._default_new_message_factory
        )
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._backfill_limit = backfill_limit
        self._max_open_age_min = max_open_age_min
        self._launch_only = launch_only

    def recent_mints(self) -> list[str]:
        return self._buffer.recent()

    @staticmethod
    def _default_client_factory(session: str, api_id: int, api_hash: str):
        try:
            from telethon import TelegramClient
        except ImportError as exc:  # pragma: no cover - exercised only without dep
            raise RuntimeError(
                "GMGN Telegram discovery requires the optional 'telethon' package"
            ) from exc
        return TelegramClient(session, api_id, api_hash)

    @staticmethod
    def _default_new_message_factory(**kwargs):
        try:
            from telethon import events
        except ImportError as exc:  # pragma: no cover - exercised only without dep
            raise RuntimeError(
                "GMGN Telegram discovery requires the optional 'telethon' package"
            ) from exc
        return events.NewMessage(**kwargs)

    @staticmethod
    def _event_text(event: Any) -> str:
        raw_text = getattr(event, "raw_text", None)
        if isinstance(raw_text, str):
            return raw_text
        text = getattr(event, "text", None)
        if isinstance(text, str):
            return text
        message = getattr(event, "message", None)
        message_text = getattr(message, "message", None)
        return message_text if isinstance(message_text, str) else ""

    async def _resolve_author(self, alert: GMGNTokenAlert) -> str:
        if alert.author or self._author_resolver is None:
            return alert.author
        try:
            author = await self._author_resolver(alert.mint)
        except Exception as exc:
            logger.debug(
                "GMGNTelegramFeed author resolver failed for mint=%s: %s",
                alert.mint,
                exc,
            )
            return ""
        return author or ""

    async def _record_text(self, text: str, *, status: str = "alert") -> int:
        count = 0
        for alert in parse_gmgn_solana_alerts(
            text,
            max_open_age_min=self._max_open_age_min,
            launch_only=self._launch_only,
        ):
            count += 1
            author = await self._resolve_author(alert)
            self._buffer.add(
                alert.mint,
                source="gmgn_telegram",
                author=author,
                liquidity_pool=alert.liquidity_pool,
                raw_text=text,
            )
            if self._store is not None:
                try:
                    self._store.save_discovery_alert(
                        source="gmgn_telegram",
                        mint=alert.mint,
                        author=author,
                        liquidity_pool=alert.liquidity_pool,
                        raw_text=text,
                    )
                    self._store.save_event(
                        "gmgn",
                        mint=alert.mint,
                        status=status,
                        detail=f"author={author}" if author else "author=",
                    )
                except Exception as exc:
                    logger.debug("GMGNTelegramFeed failed to persist alert: %s", exc)
            logger.info(
                "GMGNTelegramFeed discovered mint=%s author=%s",
                alert.mint,
                author,
            )
        return count

    async def _handle_event(self, event: Any) -> None:
        await self._record_text(self._event_text(event), status="alert")

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _connect_authorized(self, client: Any) -> None:
        connect = getattr(client, "connect", None)
        if connect is not None:
            await self._maybe_await(connect())
            is_authorized = getattr(client, "is_user_authorized", None)
            if is_authorized is not None:
                authorized = await self._maybe_await(is_authorized())
                if not authorized:
                    raise RuntimeError(
                        "Telegram session is not authorized; run "
                        "`MEMEDOG_DB=memedog.db .venv/bin/python scripts/telegram_login.py` "
                        "once in an interactive terminal"
                    )
            return

        await self._maybe_await(client.start())

    def _chat_refs(self) -> list[ChatRef]:
        return self._chat if isinstance(self._chat, list) else [self._chat]

    async def _backfill_recent(self, client: Any) -> None:
        if self._backfill_limit <= 0:
            return
        iter_messages = getattr(client, "iter_messages", None)
        if iter_messages is None:
            return

        total = 0
        for chat in self._chat_refs():
            try:
                entity = await self._maybe_await(client.get_entity(chat))
                async for message in iter_messages(entity, limit=self._backfill_limit):
                    text = getattr(message, "raw_text", None)
                    if not isinstance(text, str):
                        text = getattr(message, "text", "") or ""
                    total += await self._record_text(text, status="backfill")
            except Exception as exc:
                logger.warning("GMGNTelegramFeed backfill failed for chat=%s: %s", chat, exc)
        if total:
            logger.info("GMGNTelegramFeed backfilled %d alert(s)", total)

    async def _listen_once(self, stop_event: asyncio.Event) -> None:
        client = self._client_factory(self._session, self._api_id, self._api_hash)
        await self._connect_authorized(client)

        event_builder = self._new_message_factory(chats=self._chat)
        client.add_event_handler(self._handle_event, event_builder)

        try:
            await self._backfill_recent(client)
            disconnected = getattr(client, "disconnected", None)
            if disconnected is None:
                await stop_event.wait()
                return

            stop_task = asyncio.create_task(stop_event.wait())
            disconnect_task = asyncio.ensure_future(disconnected)
            done, pending = await asyncio.wait(
                {stop_task, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                await self._maybe_await(task)
        finally:
            try:
                client.remove_event_handler(self._handle_event, event_builder)
            except Exception:
                pass
            disconnect = getattr(client, "disconnect", None)
            if disconnect is not None:
                await self._maybe_await(disconnect())

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = self._backoff_initial
        while not stop_event.is_set():
            try:
                await self._listen_once(stop_event)
                backoff = self._backoff_initial
            except Exception as exc:
                logger.warning("GMGNTelegramFeed connection error: %s", exc)

            if stop_event.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._backoff_max)
