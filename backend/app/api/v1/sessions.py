import uuid

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import instruction, observation
from app.ai.gateway import AIError
from app.api.schemas import (
    AcknowledgeIn,
    AssistIn,
    EscalateIn,
    EvidenceIn,
    EvidenceResultOut,
    Page,
    ReportOut,
    SessionCreateIn,
    SessionOut,
    SignoffIn,
    ValidationOut,
)
from app.assessment.service import generate_report
from app.core.audit import audit
from app.core.config import get_settings
from app.core.db import SessionLocal, get_db
from app.core.deps import current_user, require, same_org
from app.core.security import decode_token
from app.cv.detector import detect
from app.models import LearningSession, Role, Skill, User, ValidationResult
from app.sessions import hub, orchestrator as orch
from app.sessions.orchestrator import SessionError, graph_for

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _raise(e: SessionError):
    raise HTTPException(e.status, {"code": e.code, "message": e.message})


def _load(db: Session, session_id: str, user: User, write: bool = False) -> LearningSession:
    sess = same_org(db.get(LearningSession, session_id), user)
    if user.role == Role.LEARNER and sess.learner_id != user.id:
        raise HTTPException(404, "not found")
    if write and sess.learner_id != user.id:
        raise HTTPException(403, "only the learner can act in their own session")
    return sess


def _push(sess: LearningSession, kind: str, extra: dict | None = None) -> None:
    hub.publish(sess.id, {"type": kind, "session": SessionOut.model_validate(sess).model_dump(mode="json"), **(extra or {})})


def _view(db: Session, sess: LearningSession) -> dict:
    g = graph_for(db, sess)
    step = g.step(sess.current_step).model_dump(mode="json") if sess.current_step else None
    last = db.scalar(select(ValidationResult).where(ValidationResult.session_id == sess.id)
                     .order_by(ValidationResult.created_at.desc()))
    return {"session": SessionOut.model_validate(sess).model_dump(mode="json"), "current_step": step,
            "skill": {"title": g.title, "steps": [{"step_id": s.step_id, "title": s.title, "critical": s.safety.critical,
                                                   "terminal": s.terminal} for s in g.steps], "entry_step": g.entry_step},
            "last_validation": ValidationOut.model_validate(last).model_dump(mode="json") if last else None,
            "briefing": orch.safety_briefing(g)}


@router.post("", response_model=SessionOut, status_code=201)
def create(body: SessionCreateIn, user: User = Depends(require(Role.LEARNER, Role.EXPERT, Role.ADMIN)),
           db: Session = Depends(get_db)):
    skill = same_org(db.get(Skill, body.skill_id), user)
    try:
        sess = orch.create_session(db, user, skill, body.mode)
    except SessionError as e:
        _raise(e)
    db.commit()
    return sess


@router.get("", response_model=Page[SessionOut])
def list_sessions(learner_id: str | None = None, state: str | None = None, limit: int = 20, offset: int = 0,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(LearningSession).where(LearningSession.org_id == user.org_id)
    if user.role == Role.LEARNER:
        q = q.where(LearningSession.learner_id == user.id)
    elif learner_id:
        q = q.where(LearningSession.learner_id == learner_id)
    if state:
        q = q.where(LearningSession.state == state)
    rows = db.scalars(q.order_by(LearningSession.created_at.desc())).all()
    return Page(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


@router.get("/{session_id}")
def get(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _view(db, _load(db, session_id, user))


@router.post("/{session_id}/start")
def start(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user, write=True)
    try:
        briefing = orch.start(db, sess)
    except SessionError as e:
        _raise(e)
    db.commit()
    _push(sess, "state")
    return {"session": SessionOut.model_validate(sess), "briefing": briefing}


@router.post("/{session_id}/acknowledge", response_model=SessionOut)
def acknowledge(session_id: str, body: AcknowledgeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user, write=True)
    try:
        orch.acknowledge(db, sess, body.safety_briefing_ack, body.recording_consent)
    except SessionError as e:
        _raise(e)
    audit(db, user, "session.consent", "session", sess.id, recording_consent=body.recording_consent)
    db.commit()
    _push(sess, "state")
    return sess


def _submit(db: Session, sess: LearningSession, step_id: str, items: list[dict], source: str) -> EvidenceResultOut:
    try:
        vr, verdict = orch.submit_evidence(db, sess, step_id, items, source)
    except SessionError as e:
        db.commit()  # keep out_of_sequence events
        _raise(e)
    db.commit()
    out = EvidenceResultOut(validation=ValidationOut.model_validate(vr), session=SessionOut.model_validate(sess),
                            next_action=verdict.next_action)
    _push(sess, "validation", {"validation": out.validation.model_dump(mode="json")})
    return out


@router.post("/{session_id}/evidence", response_model=EvidenceResultOut)
def evidence(session_id: str, body: EvidenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Submit measurements and confirmations. Visual evidence is only accepted from /observe,
    where the server produces it from a camera frame, so clients cannot self-assert it."""
    sess = _load(db, session_id, user, write=True)
    for it in body.items:
        if it.get("type") == "visual":
            raise HTTPException(403, "visual evidence must come from a camera frame via /observe")
    return _submit(db, sess, body.step_id, body.items, "manual_entry")


# The prompt's /validate endpoint: validation runs on every evidence submission, so this
# re-reads the latest verdict for the current step instead of re-judging.
@router.post("/{session_id}/validate", response_model=ValidationOut | None)
def latest_validation(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user)
    return db.scalar(select(ValidationResult).where(ValidationResult.session_id == sess.id)
                     .order_by(ValidationResult.created_at.desc()))


_IMG = {b"\xff\xd8\xff": ".jpg", b"\x89PNG": ".png"}


@router.post("/{session_id}/observe", response_model=EvidenceResultOut)
async def observe(session_id: str, step_id: str = Form(...), method_index: int = Form(...),
                  frame: UploadFile = File(...), user: User = Depends(current_user)):
    """Camera frame → detector hints → observation agent → deterministic validation."""
    db = SessionLocal()
    try:
        sess = _load(db, session_id, user, write=True)
        if not sess.recording_consent:
            raise HTTPException(403, "camera evidence requires recording consent for this session")
        if step_id != sess.current_step:
            raise HTTPException(409, {"code": "out_of_sequence", "message": f"current step is '{sess.current_step}'"})
        data = await frame.read(get_settings().max_evidence_image_mb * 1024 * 1024 + 1)
        if len(data) > get_settings().max_evidence_image_mb * 1024 * 1024:
            raise HTTPException(413, "image too large")
        ext = next((e for sig, e in _IMG.items() if data.startswith(sig)), None)
        if ext is None:
            raise HTTPException(415, "frame must be a JPEG or PNG image")
        d = get_settings().storage_dir / "sessions" / sess.id
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(data)
        step = graph_for(db, sess).step(step_id)
        if not (0 <= method_index < len(step.validation.methods)) or step.validation.methods[method_index].type != "visual":
            raise HTTPException(422, "method_index must point to a visual validation method")
        dets = detect(str(path))
        try:
            ev = observation.observe(db, sess.org_id, step, method_index, path, dets)
        except AIError as e:
            db.commit()
            raise HTTPException(e.status, str(e)) from None
        result = _submit(db, sess, step_id, [ev.model_dump(mode="json")], "ai_vision")
        result.detections = dets
        result.observations = ev.observations and [o.model_dump() for o in ev.observations]
        return result
    finally:
        db.close()


@router.post("/{session_id}/assist")
def assist(session_id: str, body: AssistIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user, write=True)
    if not sess.current_step:
        raise HTTPException(409, "no current step")
    g = graph_for(db, sess)
    ans = instruction.answer(db, sess.org_id, g, g.step(sess.current_step), body.question)
    try:
        orch.record_assistance(db, sess, "question", {"source": ans["source"]})
    except SessionError as e:
        _raise(e)
    db.commit()
    return ans


@router.post("/{session_id}/escalate", response_model=SessionOut)
def escalate(session_id: str, body: EscalateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user, write=True)
    try:
        orch.escalate(db, sess, body.reason)
    except SessionError as e:
        _raise(e)
    db.commit()
    _push(sess, "state")
    return sess


@router.post("/{session_id}/signoff", response_model=SessionOut)
def signoff(session_id: str, body: SignoffIn, user: User = Depends(require(Role.EXPERT, Role.ADMIN)),
            db: Session = Depends(get_db)):
    sess = same_org(db.get(LearningSession, session_id), user)
    try:
        orch.instructor_signoff(db, sess, user, body.approved, body.comment)
    except SessionError as e:
        _raise(e)
    audit(db, user, "session.signoff", "session", sess.id, approved=body.approved, step=sess.current_step)
    db.commit()
    _push(sess, "state")
    return sess


@router.post("/{session_id}/complete", response_model=ReportOut)
def complete(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Generates the competency report. Only possible once the engine has reached COMPLETED (or ABANDONED)."""
    sess = _load(db, session_id, user)
    try:
        rep = generate_report(db, sess)
    except SessionError as e:
        _raise(e)
    db.commit()
    return rep


@router.post("/{session_id}/abandon", response_model=SessionOut)
def abandon(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user, write=True)
    try:
        orch.abandon(db, sess)
    except SessionError as e:
        _raise(e)
    db.commit()
    _push(sess, "state")
    return sess


@router.get("/{session_id}/events")
def events(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = _load(db, session_id, user)
    return [{"seq": e.seq, "type": e.type, "step": e.step_key, "from": e.from_state, "to": e.to_state,
             "data": e.data, "at": e.created_at} for e in sess.events]


@router.websocket("/{session_id}/ws")
async def ws(websocket: WebSocket, session_id: str, token: str):
    """Live updates. Browsers can't set headers on WebSockets, so the access token comes as ?token=."""
    try:
        payload = decode_token(token, "access")
    except jwt.PyJWTError:
        await websocket.close(code=4401)
        return
    db = SessionLocal()
    try:
        sess = db.get(LearningSession, session_id)
        user = db.get(User, payload["sub"])
        allowed = sess and user and sess.org_id == user.org_id and (user.role != Role.LEARNER or sess.learner_id == user.id)
    finally:
        db.close()
    if not allowed:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    await hub.subscribe(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive pings from the client
    except WebSocketDisconnect:
        hub.unsubscribe(session_id, websocket)
