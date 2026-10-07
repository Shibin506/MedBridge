"""Real text messages through Twilio (optional). The on-screen phone simulator needs none of this.

* ``TwilioSender``  sends one text (HTTPS POST to Twilio's REST API).
* ``valid_signature``  checks that an incoming webhook really came from Twilio (anyone can POST to a public URL).
* phone numbers must be in international format (+15551234567).

Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER (see docs/setup-keys.md).
"""

import base64
import hashlib
import hmac
import os
import re

import httpx

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class SmsError(RuntimeError):
    """A text could not be sent. The message never contains the auth token."""


def normalize_phone(raw: str | None) -> str | None:
    """'+1 (555) 123-4567' or '555-123-4567' -> '+15551234567'. None if it cannot be a valid number."""
    if not raw:
        return None
    digits = re.sub(r"[\s().-]", "", raw)
    if re.fullmatch(r"\d{10}", digits):          # a bare US number
        digits = "+1" + digits
    return digits if E164.match(digits) else None


def twilio_configured() -> bool:
    return all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))


# What Twilio's error numbers mean, in plain words. Only the common ones; unknown numbers are shown as Twilio words them.
ERROR_HELP = {
    "21608": "This is a trial account and the phone number is not verified. Add it under Phone Numbers > Manage > Verified Caller IDs.",
    "21610": "That phone replied STOP to your Twilio number, so Twilio blocks every text to it. Text START to the Twilio number from that phone.",
    "21211": "Twilio says the destination phone number is not valid. Use the full number, like +15551234567.",
    "21614": "Twilio says the destination is not a mobile number that can receive texts.",
    "21606": "The number MedBridge sends FROM is not a text-capable number in this Twilio account. Check TWILIO_FROM_NUMBER.",
    "21659": "The number MedBridge sends FROM is not a Twilio number of yours. Check TWILIO_FROM_NUMBER.",
    "21660": "The number MedBridge sends FROM does not belong to this account. Check TWILIO_FROM_NUMBER.",
    "21612": "Twilio cannot send from this number to that country or number type.",
    "30034": "US carriers block texts from US numbers that are not registered yet (A2P 10DLC). Registration takes days. Use the phone simulator for the demo, or a toll-free number once verified.",
    "30032": "Toll-free numbers must be verified before they can text. Verification takes days. Use the phone simulator for the demo.",
    "30007": "The carrier filtered the message as spam. Registration of the number usually fixes this.",
    "30006": "The destination is a landline or cannot receive texts.",
    "30005": "The destination number is unknown or inactive.",
    "30003": "The phone was unreachable (off, no signal). Twilio gave up.",
    "30008": "Unknown delivery error from the carrier. Try again, or use the phone simulator.",
    "63038": "The daily message limit of this Twilio account was reached. Try again tomorrow.",
    "20003": "Twilio rejected the Account SID or Auth Token. Run ./scripts/set-key.sh twilio again.",
}
FINAL_STATUSES = {"delivered", "undelivered", "failed", "canceled"}


def explain_error(code: object, fallback: str = "") -> str:
    return ERROR_HELP.get(str(code), fallback)


class TwilioSender:
    API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    ONE = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages/{msid}.json"

    def __init__(self, sid: str, token: str, from_number: str, client: httpx.Client | None = None):
        self._sid, self._token, self._from = sid, token, from_number
        self._http = client or httpx.Client(timeout=20)

    def send(self, to: str, body: str) -> str:
        """Hands one text to Twilio and returns its id. "Accepted" here only means queued: use ``status`` to see whether it arrived."""
        try:
            r = self._http.post(self.API.format(sid=self._sid), auth=(self._sid, self._token),
                                data={"To": to, "From": self._from, "Body": body[:1500]})
        except httpx.HTTPError as exc:
            raise SmsError(f"Could not reach Twilio ({type(exc).__name__}).") from exc
        if r.status_code // 100 == 2:
            try:
                return str(r.json().get("sid", ""))
            except ValueError:
                return ""
        try:
            err = r.json()
            code = err.get("code", r.status_code)
            detail = f"Twilio error {code}: {err.get('message', '')}"
        except ValueError:
            code, detail = r.status_code, f"Twilio error {r.status_code}"
        hint = explain_error(code)
        raise SmsError((detail + (f" ({hint})" if hint else "")).replace(self._token, "<token>")[:420])

    def __call__(self, to: str, body: str) -> None:
        self.send(to, body)

    def status(self, message_id: str) -> tuple[str, str, str]:
        """(status, error code, error message) of a text already handed to Twilio. Status is queued, sent, delivered, undelivered or failed."""
        try:
            r = self._http.get(self.ONE.format(sid=self._sid, msid=message_id), auth=(self._sid, self._token))
            data = r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise SmsError(f"Could not reach Twilio ({type(exc).__name__}).") from exc
        if r.status_code != 200:
            raise SmsError(f"Twilio error {r.status_code} while checking the text.")
        return str(data.get("status", "")), str(data.get("error_code") or ""), str(data.get("error_message") or "")


def build_sender() -> TwilioSender | None:
    if not twilio_configured():
        return None
    return TwilioSender(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"], os.environ["TWILIO_FROM_NUMBER"])


def valid_signature(token: str, url: str, params: dict[str, str], signature: str | None) -> bool:
    """Twilio signs: base64(HMAC-SHA1(token, url + each POST field name and value, sorted by name))."""
    if not signature:
        return False
    data = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)
