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
