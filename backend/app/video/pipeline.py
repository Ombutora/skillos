"""Video-to-skill compilation job.

Stages: probe → sample frames → audio + transcript → segment → multimodal
extraction → compile → validate → save as DRAFT skill version (never published
automatically; an expert must review and publish it).
"""

import traceback
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai import extraction, gateway
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import JobStatus, ProcessingJob, Skill, UploadedVideo, User
from app.skillgraph import service
from app.video import processing


def _stage(db: Session, job: ProcessingJob, stage: str, progress: float) -> None:
    job.stage, job.progress = stage, progress
    db.commit()


def run_extraction(job_id: str, db: Session | None = None) -> None:
    own = db is None
    db = db or SessionLocal()
    job = db.get(ProcessingJob, job_id)
    try:
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        video = db.get(UploadedVideo, job.video_id)
        user = db.get(User, video.uploaded_by)
        src = Path(video.storage_path)
        work = get_settings().storage_dir / "jobs" / job.id
        notes: list[str] = []

        _stage(db, job, "probing", 0.05)
        meta = processing.probe(src)
        video.duration_s, video.metadata_ = meta["duration_s"], meta

        _stage(db, job, "sampling_frames", 0.15)
        frames = processing.sample_frames(src, work / "frames")
        if not frames:
            raise RuntimeError("no frames could be extracted")

        transcript = {"text": "", "segments": []}
        if meta["has_audio"]:
            _stage(db, job, "transcribing", 0.3)
            audio = processing.extract_audio(src, work / "audio.mp3")
            if audio:
                try:
                    transcript = gateway.transcribe(db, video.org_id, audio)
                except gateway.AIError as e:
                    notes.append(f"transcript unavailable: {e}")
        else:
            notes.append("video has no audio track")

        _stage(db, job, "segmenting", 0.4)
        segments = processing.segment(frames, meta["duration_s"], transcript["segments"])

        _stage(db, job, "analyzing", 0.5)
        draft = extraction.extract(db, video.org_id, segments, transcript["text"])

        _stage(db, job, "compiling", 0.85)
        graph = extraction.compile_draft(draft, video_id=video.id, job_id=job.id, segments=segments,
                                         model=gateway.model_name())

        _stage(db, job, "validating", 0.92)
        skill = service.create_skill(db, user, graph, "Generated from video; pending expert review",
                                     source_video_id=video.id, extraction_job_id=job.id)
        version = skill.versions[-1]
        job.result = {"skill_id": skill.id, "version_id": version.id, "validation": version.validation_report,
                      "uncertainties": draft.get("uncertainties", []), "notes": notes,
                      "frames": len(frames), "segments": len(segments), "draft": draft}
        job.status, job.stage, job.progress = JobStatus.SUCCEEDED, "awaiting_expert_review", 1.0
    except Exception as e:
        db.rollback()
        job = db.get(ProcessingJob, job_id)
        job.status, job.stage = JobStatus.FAILED, "failed"
        job.error = f"{e.__class__.__name__}: {e}"[:2000]
        job.result = {"traceback": traceback.format_exc()[-3000:]}
    finally:
        job.finished_at = datetime.now(UTC)
        db.commit()
        if own:
            db.close()


def enqueue(job_id: str, background_tasks=None) -> str:
    """RQ when Redis is configured (docker), else in-process background task."""
    url = get_settings().redis_url
    if url:
        from redis import Redis
        from rq import Queue

        Queue("skillos", connection=Redis.from_url(url)).enqueue(run_extraction, job_id, job_timeout=3600)
        return "rq"
    if background_tasks is not None:
        background_tasks.add_task(run_extraction, job_id)
        return "background_task"
    run_extraction(job_id)
    return "inline"


__all__ = ["Skill", "enqueue", "run_extraction"]
