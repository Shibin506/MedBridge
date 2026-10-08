import asyncio
import hmac
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import dashboard as team_dashboard
from . import demo_patients, scheduler
from .checkins import CheckInEngine
from .demo import DemoExtractionClient, DemoLabelSource, DemoPlanClient
from .documents import UnreadableDocument, load_document
from .extractor import Extractor
from .llm import LLMError, LLMUnavailable
from .plan import LANGUAGES, PlanError, PlanGenerator, readiness_problems
from .safety import SafetyChecker, build_live_checker
from .schedule import build_schedule
from .sms import build_sender, normalize_phone, twilio_configured, valid_signature
from .store import Store
from .telegram import TelegramClient, TelegramError, build_client, handle_update, link_url, poll_once, telegram_configured
from .schemas import DailySchedule, ExtractionResult, PatientPlan, PlanRequest, SafetyReport

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

log = logging.getLogger("uvicorn.error")  # shows up in the same terminal as the server

_telegram: TelegramClient | None = None


def get_telegram() -> TelegramClient | None:
    """One shared client, so the bot's name is looked up once."""
    global _telegram
    if _telegram is None:
        _telegram = build_client()
    return _telegram


def _telegram_sender():
    tg = get_telegram()
    return (lambda chat_id, body: tg.send(chat_id, body)) if tg else None


def _make_engine(store: Store) -> CheckInEngine:
    return CheckInEngine(store, sender=build_sender(), telegram=_telegram_sender())


async def _telegram_loop() -> None:
    while True:
        try:
            tg = get_telegram()
            if tg is None:
                return
            await asyncio.to_thread(lambda: poll_once(Store(), _make_engine, tg))
        except TelegramError as exc:
            log.warning("Telegram: %s", exc)
            await asyncio.sleep(15)
        except Exception:
            log.exception("Telegram pass failed")
            await asyncio.sleep(15)


async def _scheduler_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(lambda: scheduler.tick(Store(), _make_engine))
        except Exception:
            log.exception("Scheduler pass failed")
        await asyncio.sleep(scheduler.TICK_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = []
    if scheduler.enabled():
        tasks.append(asyncio.create_task(_scheduler_loop()))
        log.info("Reminder scheduler is running (a pass every %d s; real-message patients only).", scheduler.TICK_SECONDS)
    if telegram_configured() and os.environ.get("MEDBRIDGE_TELEGRAM", "on").lower() not in {"off", "0", "false", "no"}:
        tasks.append(asyncio.create_task(_telegram_loop()))
        log.info("Telegram bot is connected: listening for patients' messages.")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="MedBridge API", version="0.2.0", lifespan=lifespan)


@app.exception_handler(LLMUnavailable)
def _ai_busy(request: Request, exc: LLMUnavailable) -> JSONResponse:
    log.warning("AI service unavailable on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={
        "detail": "The AI service is busy or could not be reached (free tiers have limits). "
                  "Please wait a minute and try again."})


@app.exception_handler(LLMError)
def _ai_error(request: Request, exc: LLMError) -> JSONResponse:
    log.warning("AI error on %s: %s", request.url.path, exc)  # messages never contain your key
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def demo_mode() -> bool:
    return os.environ.get("MEDBRIDGE_DEMO", "").lower() in {"1", "true", "yes"}


def get_extractor() -> Extractor:
    return Extractor(client=DemoExtractionClient() if demo_mode() else None)


def get_plan_generator() -> PlanGenerator:
    return PlanGenerator(client=DemoPlanClient() if demo_mode() else None)


def get_safety_checker() -> SafetyChecker:
    return SafetyChecker(labels=DemoLabelSource()) if demo_mode() else build_live_checker()


def _require_ready(req: PlanRequest) -> None:
    # Same gate as /plan: nothing is derived from items the patient has not checked.
    problems = readiness_problems(req)
    if problems:
        raise HTTPException(status_code=409, detail={"problems": problems})


def team_key() -> str:
    return os.environ.get("MEDBRIDGE_TEAM_KEY", "")


def require_team(request: Request) -> None:
    """The care-team pages show every patient. If MEDBRIDGE_TEAM_KEY is set, they need that access code.
    (Not set = open, which is only fine on your own computer.)"""
    key = team_key()
    if key and not hmac.compare_digest(request.headers.get("X-Team-Key", "").encode(), key.encode()):
        raise HTTPException(status_code=401, detail="Care-team access code needed.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config() -> dict:
    """What the UI needs to know at startup."""
    return {"demo": demo_mode(), "languages": LANGUAGES, "sms": twilio_configured(), "telegram": telegram_configured(), "team_key_required": bool(team_key())}


@app.get("/samples")
def list_samples() -> list[str]:
    return sorted(p.name for p in SAMPLES_DIR.glob("*.txt"))


@app.get("/samples/{name}")
def get_sample(name: str) -> dict[str, str]:
    # Only names that really exist in samples/ are served (no path tricks like ../).
    if name not in {p.name for p in SAMPLES_DIR.glob("*.txt")}:
        raise HTTPException(status_code=404, detail="Unknown sample.")
    return {"name": name, "text": (SAMPLES_DIR / name).read_text(encoding="utf-8")}


@app.post("/extract", response_model=ExtractionResult)
def extract(file: UploadFile = File(...), extractor: Extractor = Depends(get_extractor)) -> ExtractionResult:
    # Plain `def` (not async): FastAPI runs it in a worker thread, so the slow,
    # blocking LLM call does not freeze the whole server.
    data = file.file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (10 MB max).")
    try:
        text = load_document(file.filename or "", data)
    except UnreadableDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = extractor.extract(text)
    result.document_text = text
    return result


@app.post("/plan", response_model=PatientPlan)
def make_plan(req: PlanRequest, generator: PlanGenerator = Depends(get_plan_generator)) -> PatientPlan:
    # The gate lives in code: the UI can hide the button, but the server refuses anyway.
    _require_ready(req)
    try:
        return generator.generate(req)
    except PlanError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/schedule", response_model=DailySchedule)
def make_schedule(req: PlanRequest) -> DailySchedule:
    _require_ready(req)
    return build_schedule(req.extraction.medications)


@app.post("/safety", response_model=SafetyReport)
def safety_check(req: PlanRequest, checker: SafetyChecker = Depends(get_safety_checker)) -> SafetyReport:
    _require_ready(req)
    return checker.check(req.extraction)


# ----------------------------------------------------------------------------------------------------------
# Phase 4: daily text check-ins (phone simulator, or real texts through Twilio)
# ----------------------------------------------------------------------------------------------------------
def get_store() -> Store:
    return Store()


def get_engine(store: Store = Depends(get_store)) -> CheckInEngine:
    return _make_engine(store)


class CreatePatient(BaseModel):
    plan: PlanRequest
    name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    mode: Literal["simulator", "sms", "telegram"] = "simulator"
    consent_sms: bool = False
    timezone: str = Field(default="", max_length=64)   # the browser's zone, e.g. "America/Chicago"; decides when 8:00 AM is


class ReplyBody(BaseModel):
    text: str = Field(max_length=1000)


@app.post("/patients")
def create_patient(body: CreatePatient, store: Store = Depends(get_store), engine: CheckInEngine = Depends(get_engine)) -> dict:
    _require_ready(body.plan)  # same gate: nothing is sent about a list the patient has not checked
    phone = None
    if body.mode == "sms":
        if not twilio_configured():
            raise HTTPException(status_code=409, detail="Real text messages are not set up on this server. Use the phone simulator.")
        phone = normalize_phone(body.phone)
        if phone is None:
            raise HTTPException(status_code=422, detail="Please enter a full phone number, for example +15551234567.")
        if not body.consent_sms:
            raise HTTPException(status_code=409, detail="We can only text you if you agree to receive text messages.")
    link_token = ""
    if body.mode == "telegram":
        if not telegram_configured():
            raise HTTPException(status_code=409, detail="Telegram is not set up on this server. Use the phone simulator.")
        link_token = secrets.token_urlsafe(12)
    pid = store.create_patient(name=body.name, phone=phone, mode=body.mode, consent=body.consent_sms,
                               language=body.plan.language, extraction_json=body.plan.extraction.model_dump_json(),
                               timezone=scheduler.resolve_timezone(body.timezone), link_token=link_token)
    if body.mode != "telegram":
        engine.start(pid)           # a Telegram patient gets the welcome message the moment they press Start
    return _state(engine, pid)


def _state(engine: CheckInEngine, pid: str) -> dict:
    """The patient's screen data, plus (for real texts) when the next text will go out by itself."""
    state = engine.state(pid)
    p = engine.store.get_patient(pid) or {}
    state["scheduled_next"] = None
    state["timezone"] = p.get("timezone") or ""
    if p.get("mode") == "telegram":
        link, problem = None, None
        if not p.get("chat_id") and p.get("link_token"):
            tg = get_telegram()
            try:
                link = link_url(tg.username(), p["link_token"]) if tg else None
            except TelegramError as exc:
                problem = str(exc)
        state["telegram"] = {"linked": bool(p.get("chat_id")), "link_url": link, "problem": problem}
    reachable = p.get("mode") == "sms" or (p.get("mode") == "telegram" and p.get("chat_id"))
    if reachable and not p.get("opted_out"):
        nxt = scheduler.next_due(p, datetime.now(timezone.utc))
        if nxt:
            state["scheduled_next"] = {"at": nxt[0].isoformat(), "label": nxt[1]}
    return state


def _known(engine: CheckInEngine, pid: str) -> None:
    if engine.store.get_patient(pid) is None:
        raise HTTPException(status_code=404, detail="Unknown patient.")


@app.get("/patients/{pid}")
def get_patient_state(pid: str, engine: CheckInEngine = Depends(get_engine)) -> dict:
    _known(engine, pid)
    return _state(engine, pid)


@app.post("/patients/{pid}/advance")
def advance(pid: str, engine: CheckInEngine = Depends(get_engine)) -> dict:
    _known(engine, pid)
    p = engine.store.get_patient(pid) or {}
    if p.get("mode") == "telegram" and not p.get("chat_id"):
        raise HTTPException(status_code=409, detail="This patient has not connected Telegram yet: open the link and press Start first.")
    engine.advance(pid)
    return _state(engine, pid)


@app.post("/patients/{pid}/reply")
def patient_reply(pid: str, body: ReplyBody, engine: CheckInEngine = Depends(get_engine)) -> dict:
    _known(engine, pid)
    engine.reply(pid, body.text)
    return _state(engine, pid)


class AckBody(BaseModel):
    note: str = Field(default="", max_length=500)   # what was done, e.g. "Called, advised to keep leg raised"
    by: str = Field(default="", max_length=80)      # who did it


@app.post("/alerts/{alert_id}/ack", dependencies=[Depends(require_team)])
def acknowledge_alert(alert_id: int, body: AckBody | None = None, store: Store = Depends(get_store)) -> dict[str, bool]:
    body = body or AckBody()
    if not store.acknowledge(alert_id, body.note, body.by):
        raise HTTPException(status_code=404, detail="Unknown alert.")
    return {"ok": True}


# ----------------------------------------------------------------------------------------------------------
# Phase 5: the care-team dashboard (all patients, one screen)
# ----------------------------------------------------------------------------------------------------------
@app.get("/dashboard", dependencies=[Depends(require_team)])
def get_dashboard(store: Store = Depends(get_store)) -> dict:
    return team_dashboard.overview(store)


@app.get("/dashboard/patients/{pid}", dependencies=[Depends(require_team)])
def get_dashboard_patient(pid: str, engine: CheckInEngine = Depends(get_engine)) -> dict:
    _known(engine, pid)
    return team_dashboard.patient_detail(engine, pid)


@app.post("/demo/patients", dependencies=[Depends(require_team)])
def load_example_patients(store: Store = Depends(get_store)) -> dict:
    """Replaces the fictional example patients with fresh ones (see demo_patients.py). Real patients are never touched."""
    ids = demo_patients.seed(store)
    return {"loaded": len(ids)}


@app.delete("/demo/patients", dependencies=[Depends(require_team)])
def remove_example_patients(store: Store = Depends(get_store)) -> dict:
    return {"removed": demo_patients.reset(store)}


@app.post("/sms/incoming")
async def sms_incoming(request: Request, engine: CheckInEngine = Depends(get_engine)) -> Response:
    """Twilio calls this when a patient texts back. Only Twilio's signed requests are accepted."""
    token, public = os.environ.get("TWILIO_AUTH_TOKEN"), os.environ.get("MEDBRIDGE_PUBLIC_URL", "").rstrip("/")
    if not twilio_configured() or not public:
        raise HTTPException(status_code=503, detail="Incoming texts are not set up (needs Twilio keys and MEDBRIDGE_PUBLIC_URL).")
    form = {k: str(v) for k, v in (await request.form()).items()}
    if not valid_signature(token or "", f"{public}/sms/incoming", form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Bad signature.")
    patient = engine.store.find_by_phone(normalize_phone(form.get("From")) or "")
    if patient is not None:
        engine.reply(patient["id"], form.get("Body", ""))
    return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>", media_type="text/xml")
