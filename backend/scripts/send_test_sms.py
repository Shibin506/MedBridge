"""Sends ONE test text through MedBridge's own sender, then asks Twilio whether it really arrived.

    ./scripts/send-test-sms.sh +16692926275

Twilio says "queued" the moment it accepts a text. Whether the phone gets it is decided later (carrier blocks, unverified numbers...),
so this waits up to 40 seconds and prints Twilio's final answer, with a plain-English explanation. It never prints your token.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sms import FINAL_STATUSES, SmsError, TwilioSender, explain_error, normalize_phone, twilio_configured  # noqa: E402


def main(argv: list[str]) -> int:
    if not twilio_configured():
        print("Twilio is not set up. Run ./scripts/set-key.sh twilio first.")
        return 2
    to = normalize_phone(argv[0]) if argv else None
    if not to:
        print("Usage: ./scripts/send-test-sms.sh +16692926275   (your own mobile number, with + and country code)")
        return 2
    sender = TwilioSender(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"], os.environ["TWILIO_FROM_NUMBER"])
    print(f"Sending a test text from {os.environ['TWILIO_FROM_NUMBER']} to {to} ...")
    try:
        message_id = sender.send(to, "MedBridge test: if you can read this, real texts work.")
    except SmsError as exc:
        print(f"\nFAIL at send time: {exc}")
        return 1
    print(f"Twilio accepted it (id {message_id[:6]}...). Now waiting to see whether it arrives.")
    status, code, message = "queued", "", ""
    for _ in range(14):
        time.sleep(3)
        try:
            status, code, message = sender.status(message_id)
        except SmsError as exc:
            print(f"(could not check the status: {exc})")
            continue
        print(f"  status: {status}" + (f"  (error {code})" if code else ""))
        if status in FINAL_STATUSES:
            break
    print()
    if status == "delivered":
        print("PASS: Twilio says the text was DELIVERED. Check your phone.")
        return 0
    if status in {"undelivered", "failed", "canceled"}:
        print(f"FAIL: Twilio says the text was {status.upper()}." + (f" Error {code}: {message}" if code else ""))
        print(explain_error(code, "Look up this error number at https://www.twilio.com/docs/api/errors") if code else "No error number was given.")
        return 1
    print(f"Not finished after 40 seconds (last status: {status}). Check Monitor > Logs > Messaging in the Twilio console, or run this again.")
    if status == "sent":
        print("'sent' means Twilio handed it to the carrier; some carriers never confirm delivery. If it is on your phone, it worked.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
