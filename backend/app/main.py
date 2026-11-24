from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models  # noqa: F401  (register tables)
from app.ai.gateway import ai_available, model_name, provider, transcription_backend
from app.api.v1 import assessments, auth, sessions, skills, videos
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.deps import current_user
from app.cv.detector import detector_status
from app.sessions.orchestrator import SessionError
from app.skillgraph.service import SkillError


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all keeps local setup to one command; production should use migrations (see docs/database.md).
    Base.metadata.create_all(engine)
    if get_settings().seed_demo_data:
        from app.seed.demo import seed

        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(title="SkillOS API", version="0.1.0", lifespan=lifespan,
              description="Capture expert practical skills, guide learners, and verify competency from evidence.")

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

API = "/api/v1"
for r in (auth.router, skills.router, videos.router, sessions.router, assessments.router):
    app.include_router(r, prefix=API)


@app.exception_handler(SessionError)
async def _session_error(_: Request, e: SessionError):
    return JSONResponse({"detail": {"code": e.code, "message": e.message}}, status_code=e.status)


@app.exception_handler(SkillError)
async def _skill_error(_: Request, e: SkillError):
    return JSONResponse({"detail": {"message": e.message, **e.details}}, status_code=e.status)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get(f"{API}/system/capabilities", tags=["system"])
def capabilities(_=Depends(current_user)):
    """What is actually configured, so the UI can show limitations instead of pretending."""
    import shutil

    return {"ai": ai_available(), "ai_provider": provider(), "ai_model": model_name(),
            "transcription": transcription_backend(), "detector": detector_status(),
            "ffmpeg": bool(shutil.which("ffmpeg"))}
