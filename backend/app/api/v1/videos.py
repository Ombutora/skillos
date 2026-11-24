import hashlib
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import JobOut, Page, VideoOut
from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import require, same_org
from app.models import ProcessingJob, Role, SkillVersion, UploadedVideo, User
from app.video.pipeline import enqueue

router = APIRouter(tags=["videos"])
EDITORS = (Role.ADMIN, Role.EXPERT)

# Leading bytes of the containers we accept. The extension and the client's content type are not trusted.
_SIGNATURES = {
    "video/mp4": lambda h: h[4:8] == b"ftyp" and h[8:10] != b"qt",
    "video/quicktime": lambda h: h[4:8] in (b"ftyp", b"moov", b"mdat", b"wide"),
    "video/webm": lambda h: h[:4] == b"\x1a\x45\xdf\xa3",
}


def _sniff(head: bytes) -> str | None:
    for ctype, test in _SIGNATURES.items():
        if test(head):
            return ctype
    return None


@router.post("/videos/upload", response_model=VideoOut, status_code=201)
async def upload(file: UploadFile = File(...), title: str = Form(..., max_length=200),
                 consent_confirmed: bool = Form(...), user: User = Depends(require(*EDITORS)),
                 db: Session = Depends(get_db)):
    s = get_settings()
    if not consent_confirmed:
        raise HTTPException(422, "confirm that everyone shown in the video consented to recording")
    head = await file.read(16)
    ctype = _sniff(head)
    if ctype is None or ctype not in s.allowed_video_types:
        raise HTTPException(415, "unsupported file: upload an MP4, MOV or WebM video")
    dest_dir = s.storage_dir / "videos" / user.org_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    sha, size, limit = hashlib.sha256(head), len(head), s.max_upload_mb * 1024 * 1024
    tmp = dest_dir / f".upload-{hashlib.md5(title.encode() + head).hexdigest()}"
    with open(tmp, "wb") as out:
        out.write(head)
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, f"video exceeds {s.max_upload_mb} MB")
            sha.update(chunk)
            out.write(chunk)
    digest = sha.hexdigest()
    ext = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}[ctype]
    final = dest_dir / f"{digest}{ext}"  # server-chosen name; the client filename is never used as a path
    tmp.replace(final)
    v = UploadedVideo(org_id=user.org_id, uploaded_by=user.id, title=title.strip(),
                      original_filename=Path(file.filename or "video").name[:300], content_type=ctype,
                      size_bytes=size, sha256=digest, storage_path=str(final), consent_confirmed=True)
    db.add(v)
    db.flush()
    audit(db, user, "video.uploaded", "video", v.id, size=size)
    db.commit()
    return v


@router.get("/videos", response_model=Page[VideoOut])
def list_videos(limit: int = 20, offset: int = 0, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    rows = db.scalars(select(UploadedVideo).where(UploadedVideo.org_id == user.org_id)
                      .order_by(UploadedVideo.created_at.desc())).all()
    return Page(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


@router.get("/videos/{video_id}", response_model=VideoOut)
def get_video(video_id: str, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    return same_org(db.get(UploadedVideo, video_id), user)


@router.get("/videos/{video_id}/processing-status", response_model=list[JobOut])
def processing_status(video_id: str, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    same_org(db.get(UploadedVideo, video_id), user)
    return db.scalars(select(ProcessingJob).where(ProcessingJob.video_id == video_id)
                      .order_by(ProcessingJob.created_at.desc())).all()


@router.post("/extraction/{video_id}", response_model=JobOut, status_code=202)
def start_extraction(video_id: str, background: BackgroundTasks, user: User = Depends(require(*EDITORS)),
                     db: Session = Depends(get_db)):
    from app.ai.gateway import AINotConfigured, ai_available

    v = same_org(db.get(UploadedVideo, video_id), user)
    if not ai_available():
        raise HTTPException(503, str(AINotConfigured()))
    job = ProcessingJob(org_id=v.org_id, video_id=v.id, kind="extraction")
    db.add(job)
    db.flush()
    audit(db, user, "extraction.started", "processing_job", job.id)
    db.commit()
    enqueue(job.id, background)
    return job


@router.get("/extraction/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    return same_org(db.get(ProcessingJob, job_id), user)


@router.get("/extraction/{job_id}/skill-graph")
def job_graph(job_id: str, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    job = same_org(db.get(ProcessingJob, job_id), user)
    vid = (job.result or {}).get("version_id")
    if not vid:
        raise HTTPException(409, f"no skill graph yet (job status: {job.status.value}, stage: {job.stage})")
    v = db.get(SkillVersion, vid)
    return {"skill_id": job.result["skill_id"], "version_id": v.id, "graph": v.graph,
            "validation_report": v.validation_report, "uncertainties": job.result.get("uncertainties", [])}
