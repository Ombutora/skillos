from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class AssessmentReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "assessment_reports"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), unique=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.id"))
    mode: Mapped[str] = mapped_column(String(20))
    metrics: Mapped[dict] = mapped_column(JSON)  # every metric with numerator/denominator
    session_level: Mapped[str] = mapped_column(String(20))
    rule_trace: Mapped[list] = mapped_column(JSON, default=list)  # which criteria passed/failed
    narrative: Mapped[str] = mapped_column(Text, default="")  # optional AI summary; never the source of numbers


class Competency(IdMixin, TimestampMixin, Base):
    __tablename__ = "competencies"
    __table_args__ = (UniqueConstraint("learner_id", "skill_id"),)

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"))
    level: Mapped[str] = mapped_column(String(20), default="NOVICE")
    attempts: Mapped[int] = mapped_column(default=0)
    completions: Mapped[int] = mapped_column(default=0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # rule trace behind the level
