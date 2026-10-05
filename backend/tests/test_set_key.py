import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run(tmp: Path, pasted: str, existing_env: str | None = None, *args: str):
    (tmp / "scripts").mkdir(exist_ok=True)
    for name in ("set-key.sh", "load-env.sh"):
        shutil.copy(ROOT / "scripts" / name, tmp / "scripts" / name)
    shutil.copy(ROOT / ".env.example", tmp / ".env.example")
    if existing_env is not None:
        (tmp / ".env").write_text(existing_env)
    return subprocess.run(["bash", str(tmp / "scripts/set-key.sh"), *args], input=pasted, capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "MEDBRIDGE_SKIP_CHECK": "1"})


def test_default_provider_is_groq_and_the_key_is_never_printed(tmp_path):
    key = "gsk_" + "TESTONLY" * 4
    out = run(tmp_path, f'  "{key}" \n')
    assert out.returncode == 0, out.stderr
    assert f"GROQ_API_KEY={key}\n" in (tmp_path / ".env").read_text()
    assert key not in out.stdout + out.stderr and "starts with “gsk_”" in out.stdout
    assert "normally starts with" not in out.stdout  # a good key gets no warning
    assert oct((tmp_path / ".env").stat().st_mode & 0o777) == "0o600"


def test_gemini_still_available(tmp_path):
    out = run(tmp_path, "AIza" + "N" * 35 + "\n", None, "gemini")
    assert out.returncode == 0 and "GEMINI_API_KEY=AIza" in (tmp_path / ".env").read_text()
    assert "normally starts with" not in out.stdout


def test_replaces_the_old_key_and_keeps_other_settings(tmp_path):
    existing = "# comment\nGROQ_API_KEY=old-bad-key\nGEMINI_API_KEY=keep-gemini\nMEDBRIDGE_MODEL=custom\n"
    run(tmp_path, "gsk_" + "N" * 30 + "\n", existing)
    text = (tmp_path / ".env").read_text()
    assert text.count("GROQ_API_KEY=") == 1 and "old-bad-key" not in text
    assert "GEMINI_API_KEY=keep-gemini" in text and "MEDBRIDGE_MODEL=custom" in text and "# comment" in text


@pytest.mark.parametrize("provider,bad", [("groq", "Zq" + "x" * 40), ("gemini", "Ab8R" + "x" * 46)])
def test_warns_when_a_key_has_the_wrong_start(tmp_path, provider, bad):
    out = run(tmp_path, bad + "\n", None, provider)
    assert "normally starts with" in out.stdout


def test_empty_paste_changes_nothing(tmp_path):
    out = run(tmp_path, "\n", "GROQ_API_KEY=keep-me\n")
    assert out.returncode == 1 and (tmp_path / ".env").read_text() == "GROQ_API_KEY=keep-me\n"


def test_unknown_provider_is_refused(tmp_path):
    assert run(tmp_path, "x\n", None, "openai").returncode == 1
