"""Real phone messages through a free Telegram bot (an alternative to Twilio texts that needs no carrier approval and no public web address).

How a patient is connected:
  1. The app makes a one-time link:  https://t.me/<your bot>?start=<secret>
  2. The patient opens it in Telegram and presses Start. Telegram then sends the bot "/start <secret>" together with the patient's chat id.
  3. That is how MedBridge knows which chat belongs to which patient. Pressing Start also counts as agreeing to messages.
Replies are fetched by "long polling" (MedBridge asks Telegram "anything new?"), so nothing has to be reachable from the internet.

Needs TELEGRAM_BOT_TOKEN from @BotFather (see docs/setup-keys.md). The token is a secret: it lives only in .env and is never printed or logged.
"""

import os
import re
from typing import Any

import httpx

API = "{base}/bot{token}/{method}"
DEFAULT_BASE = "https://api.telegram.org"      # TELEGRAM_API_BASE can point at a local test server
MAX_TEXT = 4000                      # Telegram's limit is 4096
START_PAYLOAD = re.compile(r"^/start(?:@\w+)?\s+([A-Za-z0-9_-]{8,64})\s*$")


class TelegramError(RuntimeError):
    """A Telegram call failed. The message never contains the bot token."""


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())


class TelegramClient:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self._token = token
        self._http = client or httpx.Client(timeout=40)
        self._username = ""

    def _call(self, method: str, http_timeout: float | None = None, **params: Any) -> Any:
        try:
            r = self._http.post(API.format(base=os.environ.get("TELEGRAM_API_BASE", DEFAULT_BASE).rstrip("/"), token=self._token, method=method), json=params, **({"timeout": http_timeout} if http_timeout else {}))
        except httpx.HTTPError as exc:
            raise TelegramError(f"Could not reach Telegram ({type(exc).__name__}).") from exc
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 200 and data.get("ok"):
            return data.get("result")
        description = str(data.get("description") or f"HTTP {r.status_code}")
        if r.status_code == 401:
            description = "Telegram rejected the bot token. Run ./scripts/set-key.sh telegram again."
        elif r.status_code == 409:
            description = "Another copy of MedBridge is already reading this bot's messages (stop the other one)."
        raise TelegramError(f"Telegram error {data.get('error_code', r.status_code)}: {description}".replace(self._token, "<token>")[:300])

    def me(self) -> dict[str, Any]:
        return self._call("getMe")

    def username(self) -> str:
        if not self._username:
            self._username = str(self.me().get("username") or "")
        return self._username

    def send(self, chat_id: str, text: str) -> None:
        """Plain text only (no formatting is interpreted), so nothing a patient or a paper contains can change how it looks."""
        self._call("sendMessage", chat_id=chat_id, text=text[:MAX_TEXT])

    def updates(self, offset: int | None, wait_seconds: int = 25) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": wait_seconds, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", http_timeout=wait_seconds + 15, **params) or []


def build_client() -> TelegramClient | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    return TelegramClient(token) if token else None


def link_url(username: str, token: str) -> str:
    return f"https://t.me/{username}?start={token}"


def parse_update(update: dict[str, Any]) -> tuple[str, str] | None:
    """(chat id, text) of a private text message, else None. Groups, channels, photos and edits are ignored."""
    msg = update.get("message") or {}
    chat, text = msg.get("chat") or {}, msg.get("text")
    if chat.get("type") != "private" or not isinstance(text, str) or chat.get("id") is None:
        return None
    return str(chat["id"]), text.strip()


def start_token(text: str) -> str | None:
    m = START_PAYLOAD.match(text.strip())
    return m.group(1) if m else None


UNLINKED_REPLY = ("Hi! I am the MedBridge reminder bot. To connect, open the link shown in the MedBridge app and press Start. "
                  "If you think you are in danger, call 911.")
BAD_LINK_REPLY = "That link was already used or is not valid. Please open the MedBridge app and make a new link."


def handle_update(store: Any, engine: Any, client: TelegramClient, update: dict[str, Any]) -> None:
    """One incoming Telegram message: connect a patient (/start <secret>), or treat it as the patient's reply."""
    parsed = parse_update(update)
    if parsed is None:
        return
    chat_id, text = parsed
    secret = start_token(text)
    if secret:
        patient = store.find_by_link_token(secret)
        if patient is None:
            client.send(chat_id, BAD_LINK_REPLY)
            return
        store.link_telegram(patient["id"], chat_id)
        engine.start(patient["id"])                      # the welcome text, now that there is somewhere to send it
        return
    patient = store.find_by_chat(chat_id)
    if patient is None:
        client.send(chat_id, UNLINKED_REPLY)
        return
    engine.reply(patient["id"], text)


def poll_once(store: Any, make_engine: Any, client: TelegramClient, wait_seconds: int = 25) -> int:
    """Fetch new Telegram messages and handle them. Returns how many were handled. The position is saved after each one,
    and a message that causes an error is skipped (never retried forever)."""
    import logging
    log = logging.getLogger("uvicorn.error")
    offset = int(store.get_kv("telegram_offset") or 0) or None
    handled = 0
    for update in client.updates(offset, wait_seconds):
        try:
            handle_update(store, make_engine(store), client, update)
            handled += 1
        except Exception:
            log.exception("Could not handle a Telegram message")
        store.set_kv("telegram_offset", str(int(update["update_id"]) + 1))
    return handled
