"""FastAPI service for prompt-based domain-drift detection."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

import failproofai_sdk as fp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from benchmark import dashboard, run_benchmark
from drift import run_drift
from engine import configure
from failproof_cloud import CloudUploadError, upload_pending_events
from prompts import EXAMPLES, SCOPES, VARIANTS
import store

ROOT = Path(__file__).parent


@asynccontextmanager
async def lifespan(app):
    configure()
    store.init_db()
    store.interrupt_batches()
    yield
    fp._writer.flush_now()


app = FastAPI(title="FailProof Domain Drift Lab", version="1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class EvaluationRequest(BaseModel):
    domain: str
    variant: str = "strict"
    question: str = Field(min_length=1, max_length=4000)
    mode: str = "demo"
    threshold: float = Field(default=0.5, gt=0, le=1)


class BenchmarkRequest(BaseModel):
    mode: str = "demo"
    threshold: float = Field(default=0.5, gt=0, le=1)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
async def config():
    return {"domains": {key: {"scope": value, "example": EXAMPLES[key]} for key, value in SCOPES.items()},
            "variants": VARIANTS, "live_available": bool(os.environ.get("OPENAI_API_KEY")),
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "spool": os.environ.get("FAILPROOF_SPOOL", ".runtime/failproof")}


@app.post("/api/evaluations")
async def evaluate(body: EvaluationRequest):
    try:
        return await run_drift(body.domain, body.variant, body.question, body.mode, body.threshold)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/benchmarks")
async def benchmark(body: BenchmarkRequest):
    if body.mode not in ("demo", "live"):
        raise HTTPException(422, "mode must be demo or live")
    return await run_benchmark(body.mode, body.threshold)


@app.get("/api/dashboard")
async def get_dashboard():
    return dashboard()


@app.post("/api/failproof/sync")
async def sync_failproof_events():
    """Explicitly upload pending local SDK event batches to FailProof Cloud."""
    try:
        return upload_pending_events()
    except CloudUploadError as exc:
        raise HTTPException(502, str(exc)) from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), reload=False)
