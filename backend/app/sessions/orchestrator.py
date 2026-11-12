"""Session orchestrator: the only code allowed to move a learning session.

All moves go through `_move`, which checks the state machine and appends an
event. AI components never call into this module directly; their output is
submitted as evidence and judged by `validation.evidence`.
"""

from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy.orm import Session as DB

from app.core.config import get_settings
from app.models import (
    ActionObservation,
    LearningSession,
    SessionEvent,
    Skill,
    SkillVersion,
    User,
    ValidationResult,
    VersionStatus,
)
from app.sessions.state_machine import ACCEPTS_EVIDENCE, TERMINAL, S, check
from app.skillgraph.schema import SkillGraph, Step
from app.validation.evidence import Evidence, StepVerdict, Verdict, evaluate_step

_evidence_list = TypeAdapter(list[Evidence])


class SessionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def graph_for(db: DB, sess: LearningSession) -> SkillGraph:
    v = db.get(SkillVersion, sess.version_id)
    return SkillGraph.model_validate(v.graph)


def _event(db: DB, sess: LearningSession, type_: str, step: str | None = None, data: dict | None = None,
           src: str | None = None, dst: str | None = None) -> SessionEvent:
    seq = len(sess.events) + 1
    ev = SessionEvent(session_id=sess.id, seq=seq, type=type_, step_key=step, from_state=src, to_state=dst, data=data or {})
    sess.events.append(ev)
    db.add(ev)
    return ev


def _move(db: DB, sess: LearningSession, dst: S, reason: str, data: dict | None = None) -> None:
    check(sess.state, dst.value)
    _event(db, sess, "state_changed", sess.current_step, {"reason": reason, **(data or {})}, sess.state, dst.value)
    sess.state = dst.value


# ---------- lifecycle ----------

def create_session(db: DB, learner: User, skill: Skill, mode: str = "guided") -> LearningSession:
    if mode not in ("guided", "assessment"):
        raise SessionError("bad_mode", "mode must be 'guided' or 'assessment'", 422)
    if not skill.published_version_id:
        raise SessionError("not_published", "skill has no published version")
    v = db.get(SkillVersion, skill.published_version_id)
    if v.status != VersionStatus.PUBLISHED:
        raise SessionError("not_published", "skill version is not published")
    sess = LearningSession(org_id=learner.org_id, learner_id=learner.id, skill_id=skill.id, version_id=v.id, mode=mode,
                           state=S.CREATED.value, path=[], verified_steps=[])
    db.add(sess)
    db.flush()
    _event(db, sess, "created", data={"mode": mode, "version": v.version_number}, dst=S.CREATED.value)
    return sess


def safety_briefing(g: SkillGraph) -> dict:
    reqs, hazards = [], set()
    for s in g.steps:
        for r in s.safety.requirements:
            if r not in reqs:
                reqs.append(r)
        hazards |= set(s.safety.hazards)
    return {"requirements": reqs, "hazards": sorted(hazards),
            "scope": "Isolated low-voltage DC training rig only. Do not work on mains or live high-voltage systems."}


def start(db: DB, sess: LearningSession) -> dict:
    _move(db, sess, S.PREPARING, "start")
    sess.started_at = datetime.now(UTC)
    return safety_briefing(graph_for(db, sess))


def acknowledge(db: DB, sess: LearningSession, safety_briefing_ack: bool, recording_consent: bool) -> None:
    if S(sess.state) != S.PREPARING:
        raise SessionError("bad_state", f"cannot acknowledge in state {sess.state}")
    if not safety_briefing_ack:
        raise SessionError("briefing_required", "the safety briefing must be acknowledged before starting", 422)
    g = graph_for(db, sess)
    sess.safety_briefing_ack = True
    sess.recording_consent = recording_consent
    _event(db, sess, "acknowledged", data={"recording_consent": recording_consent})
    _move(db, sess, S.IN_PROGRESS, "briefing acknowledged")
    _enter_step(db, sess, g, g.entry_step)


def _enter_step(db: DB, sess: LearningSession, g: SkillGraph, step_id: str) -> None:
    step = g.step(step_id)
    missing = [p for p in step.prerequisites if p not in sess.verified_steps]
    if missing:
        # The graph validator should make this impossible; refuse rather than skip.
        raise SessionError("prerequisites_unmet", f"cannot enter '{step_id}': prerequisites {missing} not verified", 500)
    sess.current_step = step_id
    sess.path = [*sess.path, step_id]
    _event(db, sess, "step_entered", step_id)


def _current_attempt_evidence(sess: LearningSession, step_id: str) -> list:
    """Evidence submitted since the learner last entered this step."""
    items: list = []
    for ev in reversed(sess.events):
        if ev.type == "step_entered" and ev.step_key == step_id:
            break
        if ev.type == "evidence" and ev.step_key == step_id:
            items = ev.data["items"] + items
    return _evidence_list.validate_python(items)


def _select_transition(step: Step, verdict: StepVerdict) -> str | None:
    by_idx = {m.method_index: m for m in verdict.methods}
    for t in step.transitions:
        c = t.condition
        m = by_idx.get(c.method_index) if c.method_index is not None else None
        val = m.value if m and isinstance(m.value, (int, float)) and not isinstance(m.value, bool) else None
        if c.type == "always" and verdict.verdict == Verdict.VERIFIED:
            return t.to
        if c.type == "verified" and verdict.verdict == Verdict.VERIFIED:
            return t.to
        if c.type == "failed" and verdict.verdict == Verdict.FAILED:
            return t.to
        if c.type == "measurement_in_range" and m and m.verdict == Verdict.VERIFIED:
            return t.to
        if c.type == "measurement_below" and val is not None and val < c.value:
            return t.to
        if c.type == "measurement_above" and val is not None and val > c.value:
            return t.to
    return None


def submit_evidence(db: DB, sess: LearningSession, step_id: str, items: list[dict], source: str = "manual_entry") -> tuple[ValidationResult, StepVerdict]:
    if S(sess.state) not in ACCEPTS_EVIDENCE:
        raise SessionError("bad_state", f"session in state {sess.state} does not accept evidence")
    if step_id != sess.current_step:
        _event(db, sess, "out_of_sequence", step_id, {"current": sess.current_step})
        db.flush()
        raise SessionError("out_of_sequence", f"current step is '{sess.current_step}'; complete it before '{step_id}'")
    parsed = _evidence_list.validate_python(items)
    if not parsed:
        raise SessionError("no_evidence", "at least one evidence item is required", 422)
    if any(e.type == "visual" for e in parsed) and not sess.recording_consent:
        raise SessionError("consent_required", "camera evidence requires recording consent for this session", 403)
    if any(e.type == "instructor_signoff" for e in parsed):
        raise SessionError("signoff_via_review", "instructor sign-off must go through the review endpoint", 403)

    g = graph_for(db, sess)
    step = g.step(step_id)
    for e in parsed:
        if e.method_index >= len(step.validation.methods):
            raise SessionError("bad_method_index", f"step has no validation method {e.method_index}", 422)

    obs_ids = []
    for e in parsed:
        o = ActionObservation(session_id=sess.id, step_key=step_id, evidence_type=e.type,
                              source=getattr(e, "source", source), payload=e.model_dump(mode="json"),
                              frame_path=getattr(e, "frame_path", None) or getattr(e, "photo_path", None))
        db.add(o)
        db.flush()
        obs_ids.append(o.id)
    _event(db, sess, "evidence", step_id, {"items": [e.model_dump(mode="json") for e in parsed], "observation_ids": obs_ids})
    _move(db, sess, S.VALIDATING, "evidence submitted")

    verdict = evaluate_step(step, _current_attempt_evidence(sess, step_id), get_settings().visual_confidence_threshold)
    vr = ValidationResult(session_id=sess.id, step_key=step_id, verdict=verdict.verdict.value, confidence=verdict.confidence,
                          method_results=verdict.methods_dict(), message=verdict.message,
                          detected_mistake_id=verdict.mistake.id if verdict.mistake else None,
                          safety_violation=verdict.safety_violation, observation_ids=obs_ids)
    db.add(vr)
    _event(db, sess, "validation", step_id, {"verdict": verdict.verdict.value, "mistake": vr.detected_mistake_id,
                                             "safety_violation": verdict.safety_violation, "message": verdict.message,
                                             "critical": step.safety.critical})
    _apply_verdict(db, sess, g, step, verdict)
    db.flush()
    return vr, verdict


def _apply_verdict(db: DB, sess: LearningSession, g: SkillGraph, step: Step, verdict: StepVerdict) -> None:
    if verdict.verdict == Verdict.UNCERTAIN:
        _move(db, sess, S.AWAITING_EVIDENCE, "evidence inconclusive")
        return
    if verdict.verdict == Verdict.FAILED:
        if verdict.safety_violation:
            _move(db, sess, S.BLOCKED_BY_SAFETY, "safety-critical failure", {"mistake": verdict.mistake.id if verdict.mistake else None})
            return
        branch = _select_transition(step, verdict)
        if branch:
            _move(db, sess, S.IN_PROGRESS, "failure branch", {"to": branch})
            _event(db, sess, "branched", step.step_id, {"to": branch, "reason": "failed"})
            _enter_step(db, sess, g, branch)
            return
        _move(db, sess, S.NEEDS_CORRECTION, "step failed")
        return
    _advance(db, sess, g, step, verdict)


def _advance(db: DB, sess: LearningSession, g: SkillGraph, step: Step, verdict: StepVerdict | None) -> None:
    _move(db, sess, S.VERIFIED, "step verified")
    sess.verified_steps = [*sess.verified_steps, step.step_id]
    if step.terminal:
        _move(db, sess, S.COMPLETED, "terminal step verified")
        sess.completed_at = datetime.now(UTC)
        sess.current_step = None
        return
    nxt = _select_transition(step, verdict) if verdict else next(
        (t.to for t in step.transitions if t.condition.type in ("verified", "always", "measurement_in_range")), None)
    if nxt is None:
        raise SessionError("no_transition", f"no transition matched from '{step.step_id}'", 500)
    _move(db, sess, S.IN_PROGRESS, "next step", {"to": nxt})
    if any(t.to == nxt and t.condition.type not in ("verified", "always") for t in step.transitions):
        _event(db, sess, "branched", step.step_id, {"to": nxt, "reason": "condition"})
    _enter_step(db, sess, g, nxt)


# ---------- assistance and human review ----------

def record_assistance(db: DB, sess: LearningSession, kind: str, detail: dict | None = None) -> None:
    if S(sess.state) in TERMINAL:
        raise SessionError("bad_state", "session is finished")
    sess.assistance_count += 1
    _event(db, sess, "assistance", sess.current_step, {"kind": kind, **(detail or {})})


def escalate(db: DB, sess: LearningSession, reason: str) -> None:
    _move(db, sess, S.NEEDS_HUMAN_REVIEW, reason)


def instructor_signoff(db: DB, sess: LearningSession, instructor: User, approved: bool, comment: str) -> None:
    if S(sess.state) != S.NEEDS_HUMAN_REVIEW:
        raise SessionError("bad_state", "sign-off is only possible while the session awaits human review")
    g = graph_for(db, sess)
    step = g.step(sess.current_step)
    _event(db, sess, "instructor_signoff", step.step_id,
           {"instructor_id": instructor.id, "approved": approved, "comment": comment, "critical": step.safety.critical})
    if approved:
        _advance(db, sess, g, step, None)
    else:
        _move(db, sess, S.BLOCKED_BY_SAFETY if step.safety.critical else S.IN_PROGRESS, "instructor rejected")


def abandon(db: DB, sess: LearningSession, reason: str = "learner abandoned") -> None:
    _move(db, sess, S.ABANDONED, reason)
