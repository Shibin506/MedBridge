import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(tmp_path, content: str, names: list[str]) -> dict[str, str]:
    env_file = tmp_path / ".env"
    env_file.write_bytes(content.encode())
    script = f'. "{ROOT}/scripts/load-env.sh"; load_env "{env_file}"; ' + "; ".join(
        f'printf "{n}=[%s]\\n" "${{{n}-UNSET}}"' for n in names
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    assert out.stderr == "", f"loader must be silent, got: {out.stderr!r}"
    return dict(line.split("=", 1) for line in out.stdout.splitlines())


def test_plain_value(tmp_path):
    assert load(tmp_path, "GEMINI_API_KEY=abc123\n", ["GEMINI_API_KEY"]) == {"GEMINI_API_KEY": "[abc123]"}


def test_the_exact_mistake_that_broke_the_launcher_a_space_inside_the_key(tmp_path):
    got = load(tmp_path, "GEMINI_API_KEY=AQ. Ab8RN6Ka69\n", ["GEMINI_API_KEY"])
    assert got["GEMINI_API_KEY"] == "[AQ.Ab8RN6Ka69]"  # repaired, and nothing was run as a command


def test_quotes_spaces_around_equals_and_windows_line_endings(tmp_path):
    content = 'GEMINI_API_KEY = "abc"\r\nTWILIO_FROM_NUMBER=\'+15551234567\'\r\n'
    got = load(tmp_path, content, ["GEMINI_API_KEY", "TWILIO_FROM_NUMBER"])
    assert got == {"GEMINI_API_KEY": "[abc]", "TWILIO_FROM_NUMBER": "[+15551234567]"}


def test_comments_blank_lines_empty_values_and_missing_final_newline(tmp_path):
    content = "# GEMINI_API_KEY=commented\n\nANTHROPIC_API_KEY=\nGOOGLE_API_KEY=last"
    got = load(tmp_path, content, ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"])
    assert got == {"GEMINI_API_KEY": "[UNSET]", "ANTHROPIC_API_KEY": "[UNSET]", "GOOGLE_API_KEY": "[last]"}


def test_file_content_is_never_executed(tmp_path):
    marker = tmp_path / "pwned"
    content = f"GEMINI_API_KEY=$(touch {marker})\nX=`touch {marker}`\nrm -rf {tmp_path}; GOOGLE_API_KEY=ok\n"
    load(tmp_path, content, ["GEMINI_API_KEY"])
    assert not marker.exists()
    assert tmp_path.exists()


def test_missing_file_is_fine(tmp_path):
    script = f'. "{ROOT}/scripts/load-env.sh"; load_env "{tmp_path}/nope.env"; echo ok'
    assert subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.strip() == "ok"
