from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    # Self-registration creates a new organization and makes the user its admin.
    # Experts and learners are then added by that admin (POST /users).
    organization_name: str = Field(min_length=2, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: str
    email: str
    full_name: str
    role: str
    org_id: str


class UserCreateIn(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=10)
    role: str = Field(pattern="^(admin|expert|learner)$")


# ---------- skills ----------

class SkillCreateIn(BaseModel):
    graph: dict
    change_note: str = ""


class SkillUpdateIn(BaseModel):
    graph: dict
    change_note: str = ""


class PublishIn(BaseModel):
    acknowledged_warnings: list[str] = []  # warning codes (code:step_id) the expert has reviewed
    comment: str = ""


class SkillOut(ORM):
    id: str
    slug: str
    title: str
    summary: str
    domain: str
    difficulty: str
    published_version_id: str | None
    created_at: datetime


class VersionOut(ORM):
    id: str
    version_number: int
    status: str
    graph: dict
    validation_report: dict
    source_video_id: str | None
    approved_by: str | None
    approved_at: datetime | None
    change_note: str
    created_at: datetime


class SkillDetailOut(SkillOut):
    versions: list[VersionOut]


# ---------- videos / jobs ----------

class VideoOut(ORM):
    id: str
    title: str
    original_filename: str
    content_type: str
    size_bytes: int
    duration_s: float | None
    metadata_: dict = Field(serialization_alias="metadata")
    created_at: datetime


class JobOut(ORM):
    id: str
    video_id: str
    kind: str
    status: str
    stage: str
    progress: float
    result: dict
    error: str | None
    created_at: datetime


# ---------- sessions ----------

class SessionCreateIn(BaseModel):
    skill_id: str
    mode: str = Field(default="guided", pattern="^(guided|assessment)$")


class AcknowledgeIn(BaseModel):
    safety_briefing_ack: bool
    recording_consent: bool


class EvidenceIn(BaseModel):
    step_id: str
    items: list[dict] = Field(min_length=1, max_length=10)


class AssistIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class SignoffIn(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=2000)


class EscalateIn(BaseModel):
    reason: str = Field(default="learner requested instructor", max_length=500)


class SessionOut(ORM):
    id: str
    skill_id: str
    version_id: str
    learner_id: str
    mode: str
    state: str
    current_step: str | None
    path: list
    verified_steps: list
    recording_consent: bool
    assistance_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ValidationOut(ORM):
    id: str
    step_key: str
    verdict: str
    confidence: float | None
    method_results: list
    message: str
    detected_mistake_id: str | None
    safety_violation: bool
    created_at: datetime


class EvidenceResultOut(BaseModel):
    validation: ValidationOut
    session: SessionOut
    next_action: str | None
    detections: list[dict] | None = None  # detector hints (observe endpoint only)
    observations: list[dict] | None = None  # observation-agent output (observe endpoint only)


class ReportOut(ORM):
    id: str
    session_id: str
    learner_id: str
    skill_id: str
    version_id: str
    mode: str
    metrics: dict
    session_level: str
    rule_trace: list
    narrative: str
    created_at: datetime


class CompetencyOut(ORM):
    skill_id: str
    level: str
    attempts: int
    completions: int
    evidence: dict
    updated_at: datetime
