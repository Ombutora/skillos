import enum

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class Role(str, enum.Enum):
    ADMIN = "admin"
    EXPERT = "expert"
    LEARNER = "learner"


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Retention policy for learner recordings, in days. None keeps nothing beyond the session.
    recording_retention_days: Mapped[int | None] = mapped_column(default=30)

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    organization: Mapped[Organization] = relationship(back_populates="users")


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class AICallLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_call_logs"

    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(50))  # extraction | observation | instruction | report
    model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # ok | error | invalid_output | not_configured
    latency_ms: Mapped[int | None]
    request_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    response_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(2000))
