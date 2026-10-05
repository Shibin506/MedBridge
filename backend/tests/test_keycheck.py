from app.keycheck import Attempt, advise
from app.llm import GeminiClient, make_client


def A(ok=False, code=None, note=""):
    return Attempt("x", ok, code, note)


def text(*a):
    return "\n".join(advise(*a))


def test_good_studio_key():
    assert "PASS" in text("AIzaSyAAAA" + "x" * 29, A(ok=True), A())


def test_rate_limited_key_is_valid():
    assert "VALID" in text("AIzaxxxx", A(code=429), A())


def test_vertex_only_key_tells_user_the_exact_line_to_add():
    out = text("AQ.Abcdefgh", A(code=400), A(ok=True))
    assert "GEMINI_BACKEND=vertex" in out and "AQ.A" in out


def test_rejected_everywhere_gives_the_recreate_steps():
    out = text("AQ.Abcdefgh", A(code=400, note="API key not valid"), A(code=401, note="bad"))
    assert "FAIL" in out and "aistudio.google.com/apikey" in out and "GEMINI_BACKEND" not in out


def test_unknown_model_is_called_out():
    assert "MEDBRIDGE_MODEL" in text("AIzaxxxx", A(code=404), A(code=404))


def test_the_report_never_contains_more_than_the_first_four_key_characters():
    key = "AQ" + "." + "Zq" + "TESTONLY" * 4  # synthetic; built at runtime so no key-shaped text is committed
    out = text(key, A(code=400, note="nope"), A(code=400, note="nope"))
    assert "TESTONLY" not in out and key not in out


def test_vertex_backend_is_selected_by_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("GEMINI_BACKEND", raising=False)
    assert make_client()._vertex is False
    monkeypatch.setenv("GEMINI_BACKEND", "vertex")
    assert isinstance(make_client(), GeminiClient) and make_client()._vertex is True


def test_key_that_lost_its_prefix_gets_the_double_click_hint():
    out = text("Zz9Q" + "x" * 46, A(code=400), A(code=401))
    assert "does not start with AIza or AQ." in out and "Double-clicking" in out


def test_correctly_prefixed_keys_do_not_get_the_hint():
    assert "Double-clicking" not in text("AQ.Zz9Q" + "x" * 46, A(code=400), A(code=401))
    assert "Double-clicking" not in text("AIza" + "x" * 35, A(code=400), A(code=401))


def test_pass_with_a_replaced_model_tells_user_the_permanent_fix():
    out = text("AIza" + "x" * 35, Attempt("x", True, model_used="gemini-3-flash"), A())
    assert "PASS" in out and "MEDBRIDGE_MODEL=gemini-3-flash" in out


# ---------- repairing a key that lost its "AQ." start ----------
from app import keycheck  # noqa: E402


def fake_try_factory(accept_key, vertex_only=False):
    def fake(name, key, model, vertex):
        good = key == accept_key and (vertex or not vertex_only)
        return Attempt(name, good, None if good else 400)
    return fake


def test_prefix_is_restored_and_tested(monkeypatch):
    short = "Zq" + "x" * 48
    monkeypatch.setattr(keycheck, "_try", fake_try_factory("AQ." + short))
    assert keycheck.try_restoring_prefix(short, "m") == ("AQ." + short, False)


def test_vertex_only_repair_is_reported(monkeypatch):
    short = "Zq" + "x" * 48
    monkeypatch.setattr(keycheck, "_try", fake_try_factory("AQ." + short, vertex_only=True))
    assert keycheck.try_restoring_prefix(short, "m") == ("AQ." + short, True)


def test_no_repair_when_it_does_not_help_or_does_not_apply(monkeypatch):
    short = "Zq" + "x" * 48
    monkeypatch.setattr(keycheck, "_try", fake_try_factory("something else"))
    assert keycheck.try_restoring_prefix(short, "m") is None            # repaired key also rejected
    assert keycheck.try_restoring_prefix("AIza" + "x" * 35, "m") is None  # already has a good start
    assert keycheck.try_restoring_prefix("short", "m") is None            # wrong length: do not guess


def test_write_key_keeps_other_lines_and_locks_the_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MEDBRIDGE_MODEL=m\nGEMINI_API_KEY=old\nGEMINI_BACKEND=vertex\n# note\n")
    keycheck.write_key(env, "AIzaNEW", vertex=False)
    assert env.read_text() == "GEMINI_API_KEY=AIzaNEW\nMEDBRIDGE_MODEL=m\n# note\n"
    keycheck.write_key(env, "AQ.NEW", vertex=True)
    assert env.read_text().startswith("GEMINI_API_KEY=AQ.NEW\nGEMINI_BACKEND=vertex\n")
    assert oct(env.stat().st_mode & 0o777) == "0o600"


def test_run_with_fix_repairs_env_and_without_fix_does_not(monkeypatch, tmp_path, capsys):
    short = "Zq" + "x" * 48
    env = tmp_path / ".env"
    env.write_text(f"GEMINI_API_KEY={short}\n")
    monkeypatch.setenv("GEMINI_API_KEY", short)
    monkeypatch.setenv("MEDBRIDGE_ENV_FILE", str(env))
    monkeypatch.setattr(keycheck, "_try", fake_try_factory("AQ." + short))

    assert keycheck.run(fix=False) == 1
    assert env.read_text() == f"GEMINI_API_KEY={short}\n"  # untouched
    assert "check-key.sh --fix" in capsys.readouterr().out

    assert keycheck.run(fix=True) == 0
    assert env.read_text() == f"GEMINI_API_KEY=AQ.{short}\n"
    out = capsys.readouterr().out
    assert "Repaired .env" in out and short not in out  # the key itself is never printed
