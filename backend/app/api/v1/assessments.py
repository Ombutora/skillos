from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import CompetencyOut, Page, ReportOut
from app.assessment.scoring import CRITERIA, LEVELS
from app.core.db import get_db
from app.core.deps import current_user, require, same_org
from app.models import AssessmentReport, Competency, LearningSession, Role, Skill, User

router = APIRouter(tags=["assessment"])


@router.get("/assessments", response_model=Page[ReportOut])
def list_reports(learner_id: str | None = None, skill_id: str | None = None, limit: int = 20, offset: int = 0,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(AssessmentReport).where(AssessmentReport.org_id == user.org_id)
    if user.role == Role.LEARNER:
        q = q.where(AssessmentReport.learner_id == user.id)
    elif learner_id:
        q = q.where(AssessmentReport.learner_id == learner_id)
    if skill_id:
        q = q.where(AssessmentReport.skill_id == skill_id)
    rows = db.scalars(q.order_by(AssessmentReport.created_at.desc())).all()
    return Page(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


@router.get("/assessments/criteria")
def criteria():
    return {"levels": LEVELS, "criteria": CRITERIA}


@router.get("/assessments/{assessment_id}", response_model=ReportOut)
def get_report(assessment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rep = same_org(db.get(AssessmentReport, assessment_id), user)
    if user.role == Role.LEARNER and rep.learner_id != user.id:
        raise HTTPException(404, "not found")
    return rep


@router.get("/users/{user_id}/competencies", response_model=list[CompetencyOut])
def competencies(user_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == Role.LEARNER and user_id != user.id:
        raise HTTPException(404, "not found")
    same_org(db.get(User, user_id), user)
    return db.scalars(select(Competency).where(Competency.learner_id == user_id)).all()


@router.get("/analytics/overview")
def overview(user: User = Depends(require(Role.ADMIN, Role.EXPERT)), db: Session = Depends(get_db)):
    org = user.org_id
    by_state = dict(db.execute(select(LearningSession.state, func.count()).where(LearningSession.org_id == org)
                               .group_by(LearningSession.state)).all())
    levels = dict(db.execute(select(Competency.level, func.count()).where(Competency.org_id == org)
                             .group_by(Competency.level)).all())
    reports = db.scalars(select(AssessmentReport).where(AssessmentReport.org_id == org)).all()
    mistakes: dict[str, int] = {}
    for r in reports:
        for m in r.metrics.get("mistake_ids", []):
            mistakes[m] = mistakes.get(m, 0) + 1
    return {
        "learners": db.scalar(select(func.count()).select_from(User).where(User.org_id == org, User.role == Role.LEARNER)),
        "skills": db.scalar(select(func.count()).select_from(Skill).where(Skill.org_id == org)),
        "published_skills": db.scalar(select(func.count()).select_from(Skill).where(Skill.org_id == org, Skill.published_version_id.is_not(None))),
        "sessions_by_state": by_state,
        "competency_levels": levels,
        "reports": len(reports),
        "safety_violations": sum(r.metrics.get("safety_violations", 0) for r in reports),
        "top_mistakes": sorted(mistakes.items(), key=lambda kv: -kv[1])[:10],
    }
