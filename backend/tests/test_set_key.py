import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(tmp: Path, pasted: str, existing_env: str | None = None):
    (tmp / "scripts").mkdir(exist_ok=True)
    for name in ("set-key.sh", "load-env.sh"):
        shutil.copy(ROOT / "scripts" / name, tmp / "scripts" / name)
    shutil.copy(ROOT / ".env.example", tmp / ".env.example")
    if existing_env is not None:
        (tmp / ".env").write_text(existing_env)
    return subprocess.run(["bash", str(tmp / "scripts/set-key.sh")], input=pasted, capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "MEDBRIDGE_SKIP_CHECK": "1"})


def test_writes_a_clean_line_and_never_prints_the_key(tmp_path):
    key = "AIza" + "TESTONLY" * 4
    out = run(tmp_path, f'  "{key}" \n')
    assert out.returncode == 0, out.stderr
    assert f"GEMINI_API_KEY={key}\n" in (tmp_path / ".env").read_text()
    assert key not in out.stdout + out.stderr and "starts with “AIza”" in out.stdout
    assert oct((tmp_path / ".env").stat().st_mode & 0o777) == "0o600"


def test_replaces_the_old_key_and_keeps_other_settings(tmp_path):
    existing = "# comment\nGEMINI_API_KEY=old-bad-key\nMEDBRIDGE_MODEL=gemini-custom\n"
    run(tmp_path, "AQ." + "N" * 30 + "\n", existing)
    text = (tmp_path / ".env").read_text()
    assert text.count("GEMINI_API_KEY=") == 1 and "old-bad-key" not in text
    assert "MEDBRIDGE_MODEL=gemini-custom" in text and "# comment" in text


def test_warns_when_the_key_lost_its_prefix(tmp_path):
    out = run(tmp_path, "Zq" + "x" * 48 + "\n")
    assert "Real keys start with AIza or AQ." in out.stdout


def test_empty_paste_changes_nothing(tmp_path):
    out = run(tmp_path, "\n", "GEMINI_API_KEY=keep-me\n")
    assert out.returncode == 1 and (tmp_path / ".env").read_text() == "GEMINI_API_KEY=keep-me\n"
