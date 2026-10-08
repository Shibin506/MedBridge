import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.keycheck import twilio_advise

ROOT = Path(__file__).resolve().parents[2]
SID, TOKEN = "AC" + "0" * 32, "TESTONLYTOKEN" * 2


def text(*a):
    return "\n".join(twilio_advise(*a))


def test_good_full_account():
    out = text(200, {"type": "Full", "status": "active"}, True, "+15551234567")
    assert "PASS" in out and "belongs to your account" in out and "TRIAL" not in out and "webhook" in out


def test_trial_account_explains_the_limits():
    out = text(200, {"type": "Trial", "status": "active"}, True, "+15551234567")
    assert "TRIAL" in out and "Verified Caller IDs" in out and "30034" in out and "simulator" in out


def test_a_number_that_is_not_in_the_account_is_called_out():
    out = text(200, {"type": "Trial", "status": "active"}, False, "+15557654321")
    assert "not in this Twilio account" in out and "+15557654321" in out


def test_suspended_accounts_are_called_out():
    assert "“suspended”" in text(200, {"type": "Full", "status": "suspended"}, True, "+1")


def test_bad_credentials_and_offline_and_odd_errors():
    assert "rejected" in text(401, {}, None, "+1") and "set-key.sh twilio" in text(401, {}, None, "+1")
    assert "internet" in text(None, {}, None, "+1")
    assert "unexpected error (500)" in text(500, {}, None, "+1")


def test_the_report_never_contains_the_secrets():
    for status in (200, 401, 500, None):
        out = text(status, {"type": "Trial", "status": "active"}, True, "+15551234567")
        assert TOKEN not in out and SID not in out


def run_script(tmp: Path, stdin: str, *args: str):
    (tmp / "scripts").mkdir(exist_ok=True)
    for name in ("set-key.sh", "load-env.sh"):
        shutil.copy(ROOT / "scripts" / name, tmp / "scripts" / name)
    shutil.copy(ROOT / ".env.example", tmp / ".env.example")
    return subprocess.run(["bash", str(tmp / "scripts/set-key.sh"), *args], input=stdin, capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "MEDBRIDGE_SKIP_CHECK": "1"})


def test_set_key_twilio_writes_three_lines_and_never_prints_secrets(tmp_path):
    (tmp_path / ".env").write_text("GROQ_API_KEY=keep\nTWILIO_AUTH_TOKEN=old\n")
    out = run_script(tmp_path, f"{SID}\n {TOKEN} \n+1 555 123 4567\n", "twilio")
    assert out.returncode == 0, out.stderr
    env = (tmp_path / ".env").read_text()
    assert f"TWILIO_ACCOUNT_SID={SID}\n" in env and f"TWILIO_AUTH_TOKEN={TOKEN}\n" in env
    assert "TWILIO_FROM_NUMBER=+15551234567\n" in env                    # spaces removed
    assert env.count("TWILIO_AUTH_TOKEN=") == 1 and "old" not in env and "GROQ_API_KEY=keep" in env
    assert TOKEN not in out.stdout + out.stderr and SID not in out.stdout + out.stderr
    assert oct((tmp_path / ".env").stat().st_mode & 0o777) == "0o600"


def test_set_key_twilio_warns_about_odd_values_and_refuses_empty_ones(tmp_path):
    out = run_script(tmp_path, f"XY123\n{TOKEN}\n5551234567\n", "twilio")
    assert "starts with AC" in out.stdout and "should start with +" in out.stdout
    empty = run_script(tmp_path / "e", f"{SID}\n\n+15551234567\n", "twilio") if (tmp_path / "e").mkdir() is None else None
    assert empty.returncode == 1 and "All three values are needed" in empty.stdout
    assert not (tmp_path / "e" / ".env").exists()


# ---------- Telegram ----------
def test_telegram_pass_names_the_bot():
    from app.keycheck import telegram_advise
    out = "\n".join(telegram_advise(200, {"username": "MedBridgeDemoBot"}))
    assert "PASS" in out and "@MedBridgeDemoBot" in out and "Connect Telegram" in out


def test_telegram_bad_token_says_what_to_do():
    from app.keycheck import telegram_advise
    out = "\n".join(telegram_advise(401, {}))
    assert "FAIL" in out and "BotFather" in out and "set-key.sh telegram" in out
    assert "internet" in "\n".join(telegram_advise(None, {}))


def test_set_key_telegram_saves_the_token_and_never_prints_it(tmp_path):
    token = "123456789" + ":" + "ABCdefGhIJKlmNoPQRsTUVwxyz012345678"
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    for f in ("set-key.sh", "load-env.sh"):
        shutil.copy(ROOT / "scripts" / f, work / "scripts" / f)
    (work / ".env.example").write_text("# TELEGRAM_BOT_TOKEN=\n")
    out = subprocess.run(["bash", "scripts/set-key.sh", "telegram"], cwd=work, input=token + "\n", capture_output=True, text=True,
                         env={**os.environ, "MEDBRIDGE_SKIP_CHECK": "1"})
    assert out.returncode == 0 and token not in out.stdout + out.stderr
    assert f"TELEGRAM_BOT_TOKEN={token}" in (work / ".env").read_text()
