"""Skill lifecycle: draft → (review) → publish. Publishing is gated by the validator and an expert."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    InstructorReview,
    Skill,
    SkillDependency,
    SkillEvidence,
    SkillStep,
    SkillVersion,
    User,
    VersionStatus,
)
from app.skillgraph.validator import parse_graph, validate_graph


class SkillError(Exception):
    def __init__(self, message: str, status: int = 422, details: dict | None = None):
        super().__init__(message)
        self.message, self.status, self.details = message, status, details or {}


def _report(graph: dict) -> dict:
    return validate_graph(graph, get_settings().extraction_confidence_warning).to_dict()


def create_skill(db: Session, user: User, graph: dict, change_note: str = "", source_video_id: str | None = None,
                 extraction_job_id: str | None = None) -> Skill:
    g, rep = parse_graph(graph)
    if g is None:
        raise SkillError("graph does not match the SkillGraph schema", 422, rep.to_dict())
    if db.scalar(select(Skill).where(Skill.org_id == user.org_id, Skill.slug == g.skill_id)):
        raise SkillError(f"a skill with id '{g.skill_id}' already exists in this organization", 409)
    skill = Skill(org_id=user.org_id, slug=g.skill_id, title=g.title, summary=g.summary, domain=g.domain,
                  difficulty=g.difficulty, created_by=user.id)
    db.add(skill)
    db.flush()
    add_version(db, user, skill, graph, change_note, source_video_id, extraction_job_id)
    return skill


def add_version(db: Session, user: User, skill: Skill, graph: dict, change_note: str = "",
                source_video_id: str | None = None, extraction_job_id: str | None = None) -> SkillVersion:
    g, rep = parse_graph(graph)
    if g is None:
        raise SkillError("graph does not match the SkillGraph schema", 422, rep.to_dict())
    if g.skill_id != skill.slug:
        raise SkillError("graph skill_id cannot change between versions")
    n = (db.scalar(select(func.max(SkillVersion.version_number)).where(SkillVersion.skill_id == skill.id)) or 0) + 1
    doc = g.dump()
    doc["version"] = f"{n}.0"
    v = SkillVersion(skill_id=skill.id, version_number=n, graph=doc, validation_report=_report(doc),
                     source_video_id=source_video_id, extraction_job_id=extraction_job_id,
                     created_by=user.id, change_note=change_note)
    db.add(v)
    db.flush()
    return v


def publish(db: Session, expert: User, skill: Skill, version: SkillVersion, acknowledged: list[str], comment: str) -> SkillVersion:
    if version.status == VersionStatus.PUBLISHED:
        raise SkillError("version is already published", 409)
    rep = _report(version.graph)
    version.validation_report = rep
    if not rep["ok"]:
        raise SkillError("skill graph has validation errors; fix them before publishing", 422, rep)
    needed = {f"{w['code']}:{w['step_id']}" for w in rep["warnings"]}
    missing = sorted(needed - set(acknowledged))
    if missing:
        raise SkillError("the approving expert must acknowledge every warning", 422, {"unacknowledged": missing, **rep})

    doc = dict(version.graph)
    doc["provenance"] = {**doc.get("provenance", {}), "reviewed_by": expert.id}
    version.graph = doc
    g, _ = parse_graph(doc)

    for old in db.scalars(select(SkillVersion).where(SkillVersion.skill_id == skill.id,
                                                     SkillVersion.status == VersionStatus.PUBLISHED)):
        old.status = VersionStatus.ARCHIVED
    version.status = VersionStatus.PUBLISHED
    version.approved_by = expert.id
    version.approved_at = datetime.now(UTC)
    skill.published_version_id = version.id
    skill.title, skill.summary, skill.difficulty = g.title, g.summary, g.difficulty

    # denormalize for querying and analytics
    version.steps.clear()
    db.flush()
    for i, s in enumerate(g.steps):
        version.steps.append(SkillStep(step_key=s.step_id, title=s.title, kind=s.kind, position=i,
                                       safety_critical=s.safety.critical, mandatory=s.mandatory,
                                       extraction_confidence=s.confidence))
        for t in s.transitions:
            db.add(SkillDependency(version_id=version.id, from_step=s.step_id, to_step=t.to,
                                   relation="sequence" if t.condition.type in ("verified", "always") else "branch",
                                   condition=t.condition.model_dump()))
        for p in s.prerequisites:
            db.add(SkillDependency(version_id=version.id, from_step=p, to_step=s.step_id, relation="prerequisite"))
        for e in s.evidence_refs:
            db.add(SkillEvidence(version_id=version.id, step_key=s.step_id, video_id=e.video_id, t_start=e.t_start,
                                 t_end=e.t_end, frame_paths=e.frame_paths, transcript_excerpt=e.transcript_excerpt))
    db.add(InstructorReview(org_id=expert.org_id, reviewer_id=expert.id, target_type="skill_version",
                            target_id=version.id, decision="approved", comment=comment,
                            acknowledged_warnings=sorted(needed)))
    db.flush()
    return version
