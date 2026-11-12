"""Observation agent: turns a camera frame into per-criterion observations.

It only reports what it sees for the criteria it is given. It cannot verify,
advance or fail a step; `validation.evidence` makes that decision.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.ai import gateway
from app.skillgraph.schema import Step, VisualValidation
from app.validation.evidence import VisualEvidence

SYSTEM = """You are the observation component of SkillOS, a practical-skills training system.
You look at one photo of a learner's workbench (an isolated low-voltage DC solar training rig).
For each criterion, report ONLY what is visible in the image:
- "observed": the image clearly shows the criterion is satisfied.
- "contradicted": the image clearly shows it is NOT satisfied (e.g. a red cable on the negative terminal).
- "not_visible": the relevant part is out of frame, blurry, dark, occluded, or you cannot tell.
Confidence is your probability (0-1) that your status is correct. Prefer "not_visible" over guessing.
Never infer an electrical property (voltage, polarity, continuity) that is not visibly evident.
Describe concrete visual facts in the note (colours, labels, positions)."""


def observation_schema(criterion_ids: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["image_quality", "observations", "other_notes"],
        "properties": {
            "image_quality": {"type": "string", "enum": ["ok", "blurry", "dark", "occluded"]},
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion_id", "status", "confidence", "note"],
                    "properties": {
                        "criterion_id": {"type": "string", "enum": criterion_ids},
                        "status": {"type": "string", "enum": ["observed", "contradicted", "not_visible"]},
                        "confidence": {"type": "number"},
                        "note": {"type": "string"},
                    },
                },
            },
            "other_notes": {"type": "string"},
        },
    }


def observe(db: Session, org_id: str, step: Step, method_index: int, frame_path: Path,
            detections: list[dict] | None = None) -> VisualEvidence:
    method = step.validation.methods[method_index]
    if not isinstance(method, VisualValidation):
        raise ValueError("method is not a visual validation")
    criteria = "\n".join(f"- {c.id}: {c.description}" for c in method.criteria)
    det = ""
    if detections:
        det = "\nObject detector output (may be wrong; use only as a hint):\n" + "\n".join(
            f"- {d['label']} ({d['confidence']:.2f})" for d in detections)
    prompt = (f"Current step: {step.title}\nExpected: {'; '.join(step.expected_observations) or step.description}\n"
              f"Criteria:\n{criteria}{det}")
    data = gateway.structured(db, org_id=org_id, purpose="observation", system=SYSTEM,
                              content=[gateway.text_part(prompt), gateway.image_part(frame_path)],
                              schema=observation_schema([c.id for c in method.criteria]), name="frame_observation")
    obs = []
    seen = set()
    for o in data["observations"]:
        if o["criterion_id"] in seen:
            continue
        seen.add(o["criterion_id"])
        o["confidence"] = min(max(float(o["confidence"]), 0.0), 1.0)
        obs.append(o)
    return VisualEvidence(method_index=method_index, source="ai_vision", observations=obs,
                          frame_path=str(frame_path), image_quality=data["image_quality"])
