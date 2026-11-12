from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class LearningSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "learning_sessions"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("skill_versions.id"))
    mode: Mapped[str] = mapped_column(String(20), default="guided")  # guided | assessment
    state: Mapped[str] = mapped_column(String(30), default="CREATED", index=True)
    current_step: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[list] = mapped_column(JSON, default=list)  # step keys visited, in order
    verified_steps: Mapped[list] = mapped_column(JSON, default=list)
    recording_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    safety_briefing_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    assistance_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["SessionEvent"]] = relationship(order_by="SessionEvent.seq", cascade="all, delete-orphan")


class SessionEvent(IdMixin, TimestampMixin, Base):
    """Append-only log. Assessment scores are computed from these rows only."""

    __tablename__ = "session_events"

    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    step_key: Mapped[str | None] = mapped_column(String(64))
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str | None] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ActionObservation(IdMixin, TimestampMixin, Base):
    __tablename__ = "action_observations"

    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(64))
    evidence_type: Mapped[str] = mapped_column(String(30))  # visual | measurement | learner_confirmation | instructor_signoff
    source: Mapped[str] = mapped_column(String(30))  # camera | manual_entry | ai_vision | cv_detector | instructor
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    frame_path: Mapped[str | None] = mapped_column(String(500))


class ValidationResult(IdMixin, TimestampMixin, Base):
    __tablename__ = "validation_results"

    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(20))  # VERIFIED | UNCERTAIN | FAILED
    confidence: Mapped[float | None] = mapped_column(Float)
    method_results: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str] = mapped_column(Text, default="")
    detected_mistake_id: Mapped[str | None] = mapped_column(String(64))
    safety_violation: Mapped[bool] = mapped_column(Boolean, default=False)
    observation_ids: Mapped[list] = mapped_column(JSON, default=list)
