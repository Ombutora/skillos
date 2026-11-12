"""Deterministic evidence evaluation.

Takes a step definition and the evidence submitted for it, and returns
VERIFIED, UNCERTAIN or FAILED. Nothing here calls an AI model. Vision-model
output arrives as structured per-criterion observations and is judged
against thresholds like any other evidence.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.skillgraph.schema import (
    CommonMistake,
    ConfirmationValidation,
    InstructorSignoffValidation,
    MeasurementValidation,
    Step,
    VisualValidation,
)


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    FAILED = "FAILED"


# ---------- evidence payloads ----------

class _E(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method_index: int = Field(ge=0)


class MeasurementEvidence(_E):
    type: Literal["measurement"] = "measurement"
    value: float | bool
    unit: Literal["V", "A", "ohm", "bool"]
    photo_path: str | None = None


class CriterionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    status: Literal["observed", "contradicted", "not_visible"]
    confidence: float = Field(ge=0, le=1)
    note: str = ""


class VisualEvidence(_E):
    type: Literal["visual"] = "visual"
    source: Literal["ai_vision", "cv_detector", "instructor"] = "ai_vision"
    observations: list[CriterionObservation] = []
    frame_path: str | None = None
    image_quality: Literal["ok", "blurry", "dark", "occluded", "unknown"] = "unknown"


class ConfirmationEvidence(_E):
    type: Literal["learner_confirmation"] = "learner_confirmation"
    confirmed: bool


class SignoffEvidence(_E):
    type: Literal["instructor_signoff"] = "instructor_signoff"
    instructor_id: str
    approved: bool
    comment: str = ""


Evidence = Annotated[
    MeasurementEvidence | VisualEvidence | ConfirmationEvidence | SignoffEvidence, Field(discriminator="type")
]


# ---------- results ----------

@dataclass
class MethodResult:
    method_index: int
    method_type: str
    verdict: Verdict
    message: str
    confidence: float | None = None
    value: float | bool | None = None
    trigger: str | None = None  # which mistake-trigger condition fired
    criterion_id: str | None = None


@dataclass
class StepVerdict:
    verdict: Verdict
    message: str
    methods: list[MethodResult] = field(default_factory=list)
    mistake: CommonMistake | None = None
    safety_violation: bool = False
    next_action: str | None = None  # what the learner should do now

    @property
    def confidence(self) -> float | None:
        cs = [m.confidence for m in self.methods if m.confidence is not None]
        return min(cs) if cs else None

    def methods_dict(self) -> list[dict]:
        out = []
        for m in self.methods:
            d = asdict(m)
            d["verdict"] = m.verdict.value
            out.append(d)
        return out


# ---------- per-method evaluation ----------

def _measurement(i: int, m: MeasurementValidation, ev: MeasurementEvidence) -> MethodResult:
    r = lambda v, msg, trig=None: MethodResult(i, "measurement", v, msg, 1.0, ev.value, trig)  # noqa: E731
    if ev.unit != m.unit:
        return MethodResult(i, "measurement", Verdict.UNCERTAIN, f"Expected a reading in {m.unit}, got {ev.unit}. Re-measure in {m.unit}.", None, ev.value)
    if m.quantity == "continuity":
        expected = True if m.min is None else bool(m.min)
        ok = bool(ev.value) == expected
        return r(Verdict.VERIFIED if ok else Verdict.FAILED, "Continuity as expected." if ok else "Continuity reading not as expected.", None if ok else "below_min")
    v = float(ev.value)
    if m.negative_means_reversed_polarity and v < 0:
        return r(Verdict.FAILED, f"Reading of {v:g} {m.unit} is negative: polarity is reversed at {m.probe_points or 'the probe points'}.", "negative")
    if m.min is not None and v < m.min:
        return r(Verdict.FAILED, f"Reading {v:g} {m.unit} is below the expected minimum {m.min:g} {m.unit}.", "below_min")
    if m.max is not None and v > m.max:
        return r(Verdict.FAILED, f"Reading {v:g} {m.unit} is above the expected maximum {m.max:g} {m.unit}.", "above_max")
    return r(Verdict.VERIFIED, f"Reading {v:g} {m.unit} is within the expected range.")


def _visual(i: int, m: VisualValidation, ev: VisualEvidence, threshold: float) -> MethodResult:
    thr = m.min_confidence if m.min_confidence is not None else threshold
    by_id = {o.criterion_id: o for o in ev.observations}
    unseen, low, confs = [], [], []
    for c in m.criteria:
        o = by_id.get(c.id)
        if o is None or o.status == "not_visible":
            unseen.append(c.description)
            continue
        if o.status == "contradicted":
            if o.confidence >= thr:
                return MethodResult(i, "visual", Verdict.FAILED, f"Observed problem: {c.description} is not satisfied. {o.note}".strip(), o.confidence, None, "contradicted", c.id)
            low.append(c.description)
            continue
        if o.confidence < thr:
            low.append(c.description)
        confs.append(o.confidence)

    if ev.source == "cv_detector":
        return MethodResult(i, "visual", Verdict.UNCERTAIN, "Components were detected, but detection alone does not confirm the action. A visual check of the action itself is needed.", min(confs) if confs else None)
    if unseen:
        quality = "" if ev.image_quality in ("ok", "unknown") else f" The image looks {ev.image_quality}."
        return MethodResult(i, "visual", Verdict.UNCERTAIN, f"Cannot see: {'; '.join(unseen)}.{quality} Move the camera closer or adjust the angle.", min(confs) if confs else None)
    if low:
        return MethodResult(i, "visual", Verdict.UNCERTAIN, f"Not confident enough about: {'; '.join(low)}. Provide a clearer view.", min(confs) if confs else None)
    return MethodResult(i, "visual", Verdict.VERIFIED, "All visual criteria observed.", min(confs))


def _confirmation(i: int, ev: ConfirmationEvidence) -> MethodResult:
    if ev.confirmed:
        return MethodResult(i, "learner_confirmation", Verdict.VERIFIED, "Learner confirmed.", None)
    return MethodResult(i, "learner_confirmation", Verdict.FAILED, "Learner reported the check did not pass.", None, None, "not_confirmed")


def _signoff(i: int, ev: SignoffEvidence) -> MethodResult:
    v = Verdict.VERIFIED if ev.approved else Verdict.FAILED
    return MethodResult(i, "instructor_signoff", v, ("Instructor signed off. " if ev.approved else "Instructor rejected. ") + ev.comment, None)


# ---------- step evaluation ----------

def _match_mistake(step: Step, results: list[MethodResult]) -> CommonMistake | None:
    for mk in step.common_mistakes:
        t = mk.trigger
        if not t:
            continue
        for r in results:
            if r.method_index == t.method_index and r.trigger == t.when and (t.criterion_id in (None, r.criterion_id)):
                return mk
    # A negative polarity reading also satisfies a 'below_min' trigger.
    for mk in step.common_mistakes:
        t = mk.trigger
        if t and t.when == "below_min":
            for r in results:
                if r.method_index == t.method_index and r.trigger == "negative":
                    return mk
    return None


def evaluate_step(step: Step, evidence: list, visual_threshold: float = 0.8) -> StepVerdict:
    """`evidence` holds the latest evidence item per method index for this attempt."""
    latest: dict[int, object] = {}
    for ev in evidence:
        latest[ev.method_index] = ev

    results: list[MethodResult] = []
    for i, m in enumerate(step.validation.methods):
        ev = latest.get(i)
        expected = m.type
        if ev is None:
            hint = {
                "measurement": f"Take a {getattr(m, 'quantity', '')} measurement: {getattr(m, 'probe_points', '')}".strip(),
                "visual": "Point the camera at the work area.",
                "learner_confirmation": getattr(m, "prompt", "Confirm the check."),
                "instructor_signoff": "Ask an instructor to sign off.",
            }[expected]
            results.append(MethodResult(i, expected, Verdict.UNCERTAIN, f"Evidence needed. {hint}"))
            continue
        if ev.type != expected:
            results.append(MethodResult(i, expected, Verdict.UNCERTAIN, f"Expected {expected} evidence, got {ev.type}."))
            continue
        if isinstance(m, MeasurementValidation):
            results.append(_measurement(i, m, ev))
        elif isinstance(m, VisualValidation):
            results.append(_visual(i, m, ev, visual_threshold))
        elif isinstance(m, ConfirmationValidation):
            results.append(_confirmation(i, ev))
        elif isinstance(m, InstructorSignoffValidation):
            results.append(_signoff(i, ev))

    verdicts = [r.verdict for r in results]
    if Verdict.FAILED in verdicts:
        verdict = Verdict.FAILED
    elif step.validation.policy == "all":
        verdict = Verdict.VERIFIED if all(v == Verdict.VERIFIED for v in verdicts) else Verdict.UNCERTAIN
    else:
        verdict = Verdict.VERIFIED if Verdict.VERIFIED in verdicts else Verdict.UNCERTAIN

    # Runtime guard, on top of the publish-time rule: a critical step never verifies on self-report alone.
    if verdict == Verdict.VERIFIED and step.safety.critical:
        strong = [r for r in results if r.verdict == Verdict.VERIFIED and r.method_type != "learner_confirmation"]
        if not strong:
            verdict = Verdict.UNCERTAIN
            results.append(MethodResult(-1, "safety_guard", Verdict.UNCERTAIN, "Safety-critical step needs measured or observed evidence, not only confirmation."))

    mistake = _match_mistake(step, results) if verdict == Verdict.FAILED else None
    safety_violation = verdict == Verdict.FAILED and (step.safety.critical or bool(mistake and mistake.safety_hazard))

    if verdict == Verdict.VERIFIED:
        msg, nxt = f"{step.title}: verified.", "continue"
    elif verdict == Verdict.FAILED:
        reason = next(r.message for r in results if r.verdict == Verdict.FAILED)
        if mistake:
            msg = f"{mistake.description}. {reason} {mistake.correction}"
        else:
            msg = reason
        if safety_violation:
            msg = "STOP. " + msg
        nxt = "correct_and_resubmit"
    else:
        msg = " ".join(r.message for r in results if r.verdict == Verdict.UNCERTAIN)
        nxt = "provide_more_evidence"
    return StepVerdict(verdict, msg.strip(), results, mistake, safety_violation, nxt)
