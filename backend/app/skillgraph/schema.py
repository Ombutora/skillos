"""SkillGraph document schema (v1).

A skill is a directed graph of steps. Edges are `transitions` with conditions,
which is what gives branching (e.g. a failed system test routes to a
troubleshooting branch instead of completing).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "skillos.skillgraph/1"
StepId = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- validation methods ----------

class VisualCriterion(Strict):
    id: StepId
    description: str
    # Labels a detector may report as supporting evidence. Detection alone never verifies a step.
    detector_labels: list[str] = []


class VisualValidation(Strict):
    type: Literal["visual"] = "visual"
    criteria: list[VisualCriterion] = Field(min_length=1)
    min_confidence: float | None = Field(default=None, ge=0, le=1)  # None → org/system default
    camera_guidance: str = ""


class MeasurementValidation(Strict):
    type: Literal["measurement"] = "measurement"
    quantity: Literal["dc_voltage", "dc_current", "resistance", "continuity"]
    unit: Literal["V", "A", "ohm", "bool"]
    min: float | None = None
    max: float | None = None
    probe_points: str = ""  # e.g. "controller BAT+ (red probe) to BAT- (black probe)"
    # A negative dc_voltage across the probes means reversed polarity.
    negative_means_reversed_polarity: bool = False
    tool: str = "multimeter"

    @model_validator(mode="after")
    def _range(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("measurement min must be <= max")
        if self.quantity != "continuity" and self.min is None and self.max is None:
            raise ValueError("measurement needs at least one of min/max")
        return self


class ConfirmationValidation(Strict):
    type: Literal["learner_confirmation"] = "learner_confirmation"
    prompt: str


class InstructorSignoffValidation(Strict):
    type: Literal["instructor_signoff"] = "instructor_signoff"
    prompt: str = ""


ValidationMethod = Annotated[
    VisualValidation | MeasurementValidation | ConfirmationValidation | InstructorSignoffValidation,
    Field(discriminator="type"),
]


class StepValidation(Strict):
    methods: list[ValidationMethod] = Field(min_length=1)
    # all: every method must verify. any: one verifying method is enough.
    policy: Literal["all", "any"] = "all"


# ---------- transitions ----------

class Condition(Strict):
    type: Literal["always", "verified", "failed", "measurement_in_range", "measurement_below", "measurement_above"]
    # For measurement_* conditions: which measurement method (index into validation.methods).
    method_index: int | None = None
    value: float | None = None


class Transition(Strict):
    to: StepId
    condition: Condition = Condition(type="verified")
    label: str = ""


# ---------- step ----------

class MistakeTrigger(Strict):
    """Deterministic rule that identifies this mistake from evidence."""

    method_index: int = Field(ge=0)
    when: Literal["negative", "below_min", "above_max", "contradicted", "not_confirmed"]
    criterion_id: str | None = None  # for 'contradicted'


class CommonMistake(Strict):
    id: StepId
    description: str
    detection: str = ""  # how the mistake shows up in evidence
    correction: str
    safety_hazard: bool = False
    trigger: MistakeTrigger | None = None


class Safety(Strict):
    critical: bool = False
    requirements: list[str] = []
    hazards: list[str] = []  # short_circuit | reversed_polarity | overheating | fire | ...


class EvidenceRef(Strict):
    video_id: str | None = None
    t_start: float | None = None
    t_end: float | None = None
    frame_paths: list[str] = []
    transcript_excerpt: str = ""


class Annotation(Strict):
    author_id: str | None = None
    text: str
    created_at: str | None = None


class Step(Strict):
    step_id: StepId
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    kind: Literal["action", "inspection", "measurement", "test", "decision", "safety_check", "identification"]
    instructions: list[str] = []
    prerequisites: list[StepId] = []
    required_tools: list[str] = []
    required_components: list[str] = []
    expected_observations: list[str] = []
    validation: StepValidation
    safety: Safety = Safety()
    common_mistakes: list[CommonMistake] = []
    transitions: list[Transition] = []
    alternatives: list[StepId] = []  # alternative procedures that satisfy the same goal
    terminal: bool = False
    mandatory: bool = True
    reference_images: list[str] = []
    evidence_refs: list[EvidenceRef] = []
    confidence: float | None = Field(default=None, ge=0, le=1)  # extraction confidence, None = authored by hand
    expert_annotations: list[Annotation] = []


class Provenance(Strict):
    origin: Literal["authored", "extracted"] = "authored"
    source_video_id: str | None = None
    extraction_job_id: str | None = None
    model: str | None = None
    reviewed_by: str | None = None


class SkillGraph(Strict):
    schema_: Literal["skillos.skillgraph/1"] = Field(default=SCHEMA_VERSION, alias="schema")
    skill_id: StepId
    title: str
    version: str = "1.0"
    domain: str = "solar"
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    estimated_duration: int = Field(gt=0, description="minutes")
    summary: str = ""
    required_tools: list[str] = []
    required_components: list[str] = []
    entry_step: StepId
    steps: list[Step] = Field(min_length=1)
    provenance: Provenance = Provenance()

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def step(self, step_id: str) -> Step:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        raise KeyError(step_id)

    def dump(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)
