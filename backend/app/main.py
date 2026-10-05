import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from .demo import DemoExtractionClient, DemoLabelSource, DemoPlanClient
from .documents import UnreadableDocument, load_document
from .extractor import Extractor
from .plan import LANGUAGES, PlanError, PlanGenerator, readiness_problems
from .safety import SafetyChecker, build_live_checker
from .schedule import build_schedule
from .schemas import DailySchedule, ExtractionResult, PatientPlan, PlanRequest, SafetyReport

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

app = FastAPI(title="MedBridge API", version="0.2.0")


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config() -> dict:
    """What the UI needs to know at startup."""
    return {"demo": demo_mode(), "languages": LANGUAGES}


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
