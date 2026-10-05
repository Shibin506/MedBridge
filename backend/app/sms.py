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


class TwilioSender:
    API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

    def __init__(self, sid: str, token: str, from_number: str, client: httpx.Client | None = None):
        self._sid, self._token, self._from = sid, token, from_number
        self._http = client or httpx.Client(timeout=20)

    def __call__(self, to: str, body: str) -> None:
        try:
            r = self._http.post(self.API.format(sid=self._sid), auth=(self._sid, self._token),
                                data={"To": to, "From": self._from, "Body": body[:1500]})
        except httpx.HTTPError as exc:
            raise SmsError(f"Could not reach Twilio ({type(exc).__name__}).") from exc
        if r.status_code // 100 == 2:
            return
        try:
            err = r.json()
            detail = f"Twilio error {err.get('code', r.status_code)}: {err.get('message', '')}"
        except ValueError:
            detail = f"Twilio error {r.status_code}"
        hint = ""
        if str(err.get("code") if isinstance(err, dict) else "") in {"30034", "30032", "30007"} or r.status_code == 400:
            hint = " (US carriers block texts from unregistered numbers; see docs/setup-keys.md)"
        raise SmsError((detail + hint).replace(self._token, "<token>")[:300])


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
