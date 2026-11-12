from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.schemas import Page, PublishIn, SkillCreateIn, SkillDetailOut, SkillOut, SkillUpdateIn, VersionOut
from app.core.audit import audit
from app.core.db import get_db
from app.core.deps import current_user, require, same_org
from app.models import Role, Skill, SkillVersion, User
from app.skillgraph import service
from app.skillgraph.graph import happy_path, to_networkx
from app.skillgraph.schema import SkillGraph
from app.skillgraph.validator import validate_graph

router = APIRouter(prefix="/skills", tags=["skills"])
EDITORS = (Role.ADMIN, Role.EXPERT)


def _err(e: service.SkillError):
    raise HTTPException(e.status, {"message": e.message, **e.details})


@router.get("", response_model=Page[SkillOut])
def list_skills(q: str | None = None, domain: str | None = None, difficulty: str | None = None,
                published_only: bool = False, limit: int = 20, offset: int = 0,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    stmt = select(Skill).where(Skill.org_id == user.org_id)
    if user.role == Role.LEARNER or published_only:
        stmt = stmt.where(Skill.published_version_id.is_not(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Skill.title.ilike(like), Skill.summary.ilike(like)))
    if domain:
        stmt = stmt.where(Skill.domain == domain)
    if difficulty:
        stmt = stmt.where(Skill.difficulty == difficulty)
    rows = db.scalars(stmt.order_by(Skill.title)).all()
    return Page(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


@router.post("", response_model=SkillDetailOut, status_code=201)
def create_skill(body: SkillCreateIn, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    try:
        skill = service.create_skill(db, user, body.graph, body.change_note)
    except service.SkillError as e:
        _err(e)
    audit(db, user, "skill.created", "skill", skill.id)
    db.commit()
    db.refresh(skill)
    return skill


@router.post("/validate")
def validate(body: SkillCreateIn, user: User = Depends(require(*EDITORS))):
    """Dry-run the publish gate on a graph without saving it."""
    return validate_graph(body.graph).to_dict()


def _load(db: Session, skill_id: str, user: User) -> Skill:
    skill = same_org(db.get(Skill, skill_id), user)
    if user.role == Role.LEARNER and not skill.published_version_id:
        raise HTTPException(404, "not found")
    return skill


@router.get("/{skill_id}", response_model=SkillDetailOut)
def get_skill(skill_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    skill = _load(db, skill_id, user)
    out = SkillDetailOut.model_validate(skill)
    if user.role == Role.LEARNER:
        out.versions = [v for v in out.versions if v.id == skill.published_version_id]
    return out


@router.get("/{skill_id}/graph")
def get_graph(skill_id: str, version_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Nodes/edges view for the graph editor and learner overview."""
    skill = _load(db, skill_id, user)
    vid = version_id if user.role != Role.LEARNER and version_id else skill.published_version_id or skill.versions[-1].id
    v = db.get(SkillVersion, vid)
    if v is None or v.skill_id != skill.id:
        raise HTTPException(404, "version not found")
    g = SkillGraph.model_validate(v.graph)
    nx_g = to_networkx(g)
    return {
        "version_id": v.id,
        "nodes": [{"id": n, **d} for n, d in nx_g.nodes(data=True)],
        "edges": [{"source": a, "target": b, **d} for a, b, d in nx_g.edges(data=True)],
        "happy_path": happy_path(g),
    }


@router.put("/{skill_id}", response_model=VersionOut)
def update_skill(skill_id: str, body: SkillUpdateIn, user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    """Saves an edited graph as a new draft version. Published versions are immutable."""
    skill = same_org(db.get(Skill, skill_id), user)
    try:
        v = service.add_version(db, user, skill, body.graph, body.change_note)
    except service.SkillError as e:
        _err(e)
    audit(db, user, "skill.version_created", "skill_version", v.id)
    db.commit()
    return v


@router.post("/{skill_id}/publish", response_model=VersionOut)
def publish(skill_id: str, body: PublishIn, version_id: str | None = None,
            user: User = Depends(require(*EDITORS)), db: Session = Depends(get_db)):
    skill = same_org(db.get(Skill, skill_id), user)
    v = db.get(SkillVersion, version_id) if version_id else skill.versions[-1]
    if v is None or v.skill_id != skill.id:
        raise HTTPException(404, "version not found")
    try:
        service.publish(db, user, skill, v, body.acknowledged_warnings, body.comment)
    except service.SkillError as e:
        db.commit()  # keep the refreshed validation report
        _err(e)
    audit(db, user, "skill.published", "skill_version", v.id, version=v.version_number)
    db.commit()
    return v
