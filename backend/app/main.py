from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from .documents import UnreadableDocument, load_document
from .extractor import Extractor
from .schemas import ExtractionResult

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(title="MedBridge API", version="0.1.0")


def get_extractor() -> Extractor:
    return Extractor()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    return extractor.extract(text)
