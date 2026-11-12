from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.assessment.scoring import CRITERIA, compute_metrics, profile_level, session_level
from app.models import AssessmentReport, Competency, LearningSession
from app.sessions.orchestrator import SessionError, graph_for


def _events(sess: LearningSession) -> list[dict]:
    return [{"type": e.type, "step_key": e.step_key, "data": e.data, "to_state": e.to_state,
             "created_at": e.created_at.isoformat() if e.created_at else None} for e in sess.events]


def generate_report(db: DB, sess: LearningSession) -> AssessmentReport:
    if sess.state not in ("COMPLETED", "ABANDONED"):
        raise SessionError("not_finished", "a report is generated when the session is completed or abandoned")
    existing = db.scalar(select(AssessmentReport).where(AssessmentReport.session_id == sess.id))
    if existing:
        return existing
    g = graph_for(db, sess)
    metrics = compute_metrics(_events(sess), g, sess.mode)
    level, trace = session_level(metrics)
    rep = AssessmentReport(org_id=sess.org_id, session_id=sess.id, learner_id=sess.learner_id, skill_id=sess.skill_id,
                           version_id=sess.version_id, mode=sess.mode, metrics=metrics, session_level=level,
                           rule_trace=trace)
    db.add(rep)
    db.flush()
    update_competency(db, sess.org_id, sess.learner_id, sess.skill_id)
    return rep


def update_competency(db: DB, org_id: str, learner_id: str, skill_id: str) -> Competency:
    reports = db.scalars(select(AssessmentReport).where(AssessmentReport.learner_id == learner_id,
                                                        AssessmentReport.skill_id == skill_id)
                         .order_by(AssessmentReport.created_at)).all()
    history = [{"mode": r.mode, "session_level": r.session_level, "created_at": r.created_at.isoformat()} for r in reports]
    level, evidence = profile_level(history)
    comp = db.scalar(select(Competency).where(Competency.learner_id == learner_id, Competency.skill_id == skill_id))
    if comp is None:
        comp = Competency(org_id=org_id, learner_id=learner_id, skill_id=skill_id)
        db.add(comp)
    comp.level, comp.attempts, comp.completions = level, evidence["attempts"], evidence["completions"]
    comp.evidence = evidence
    db.flush()
    return comp


__all__ = ["CRITERIA", "generate_report", "update_competency"]
