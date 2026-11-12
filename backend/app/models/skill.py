import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class VersionStatus(str, enum.Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Skill(IdMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("org_id", "slug"),)

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(100), default="solar")
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    published_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("skill_versions.id", use_alter=True, name="fk_skill_published_version")
    )

    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill", foreign_keys="SkillVersion.skill_id", order_by="SkillVersion.version_number"
    )


class SkillVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version_number"),)

    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(
        Enum(VersionStatus, native_enum=False, length=20), default=VersionStatus.DRAFT
    )
    graph: Mapped[dict] = mapped_column(JSON)  # SkillGraph document, source of truth
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)
    source_video_id: Mapped[str | None] = mapped_column(ForeignKey("uploaded_videos.id"))
    extraction_job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_jobs.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_note: Mapped[str] = mapped_column(Text, default="")

    skill: Mapped[Skill] = relationship(back_populates="versions", foreign_keys=[skill_id])
    steps: Mapped[list["SkillStep"]] = relationship(cascade="all, delete-orphan")


class SkillStep(IdMixin, Base):
    """Denormalized from the graph on publish, for querying and analytics."""

    __tablename__ = "skill_steps"
    __table_args__ = (UniqueConstraint("version_id", "step_key"),)

    version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    position: Mapped[int] = mapped_column(Integer)
    safety_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)


class SkillDependency(IdMixin, Base):
    __tablename__ = "skill_dependencies"

    version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.id"), index=True)
    from_step: Mapped[str] = mapped_column(String(64))
    to_step: Mapped[str] = mapped_column(String(64))
    relation: Mapped[str] = mapped_column(String(30))  # sequence | prerequisite | branch
    condition: Mapped[dict] = mapped_column(JSON, default=dict)


class SkillEvidence(IdMixin, TimestampMixin, Base):
    """Source evidence (video clip / frames / transcript) backing a step."""

    __tablename__ = "skill_evidence"

    version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[str | None] = mapped_column(ForeignKey("uploaded_videos.id"))
    t_start: Mapped[float | None] = mapped_column(Float)
    t_end: Mapped[float | None] = mapped_column(Float)
    frame_paths: Mapped[list] = mapped_column(JSON, default=list)
    transcript_excerpt: Mapped[str] = mapped_column(Text, default="")


class InstructorReview(IdMixin, TimestampMixin, Base):
    __tablename__ = "instructor_reviews"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(String(30))  # skill_version | session | assessment
    target_id: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(30))  # approved | changes_requested | signed_off | rejected
    comment: Mapped[str] = mapped_column(Text, default="")
    acknowledged_warnings: Mapped[list] = mapped_column(JSON, default=list)
