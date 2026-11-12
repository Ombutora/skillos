"""Skill extraction agent + deterministic compiler.

The model fills an `ExtractionDraft` (strict schema) where what was SEEN
(`observed_evidence`) is kept apart from what is INFERRED (`inferred_purpose`).
`compile_draft` then builds a SkillGraph without inventing validation the
model did not propose; gaps surface as validator errors for the expert.
"""

import hashlib
import re

from sqlalchemy.orm import Session

from app.ai import gateway

HAZARDS = ["short_circuit", "reversed_polarity", "overheating", "fire", "electric_shock"]
KINDS = ["action", "inspection", "measurement", "test", "decision", "safety_check", "identification"]

SYSTEM = """You are the skill extraction component of SkillOS. You receive keyframes from an expert's
demonstration video (grouped into segments with timestamps) and the speech transcript.
Produce a machine-readable procedure, not a summary.
Rules:
- One step per distinct practical action. Order steps as performed.
- observed_evidence: only things visible in frames or said in the transcript, citing segment numbers.
- inferred_purpose: your interpretation. Keep it separate from observations.
- If an action is implied but not shown, still include it only if necessary and set confidence below 0.5.
- Mark safety_critical for any step involving electrical connection, polarity or battery terminals.
- For polarity or voltage checks, propose a measurement (dc_voltage, V, expected range).
- Visual criteria must be checkable from a single photo.
- The domain is isolated low-voltage DC solar training rigs."""


def _nullable(t: str) -> dict:
    return {"type": [t, "null"]}


DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "summary", "difficulty", "estimated_duration", "required_tools", "required_components", "steps", "uncertainties"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
        "estimated_duration": {"type": "integer"},
        "required_tools": {"type": "array", "items": {"type": "string"}},
        "required_components": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "kind", "description", "instructions", "observed_evidence", "inferred_purpose",
                         "segment_indices", "required_tools", "required_components", "safety_critical", "hazards",
                         "safety_requirements", "visual_criteria", "measurement", "common_mistakes", "confidence"],
            "properties": {
                "title": {"type": "string"},
                "kind": {"type": "string", "enum": KINDS},
                "description": {"type": "string"},
                "instructions": {"type": "array", "items": {"type": "string"}},
                "observed_evidence": {"type": "array", "items": {"type": "string"}},
                "inferred_purpose": {"type": "string"},
                "segment_indices": {"type": "array", "items": {"type": "integer"}},
                "required_tools": {"type": "array", "items": {"type": "string"}},
                "required_components": {"type": "array", "items": {"type": "string"}},
                "safety_critical": {"type": "boolean"},
                "hazards": {"type": "array", "items": {"type": "string", "enum": HAZARDS}},
                "safety_requirements": {"type": "array", "items": {"type": "string"}},
                "visual_criteria": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["description"],
                    "properties": {"description": {"type": "string"}}}},
                "measurement": {
                    "type": "object", "additionalProperties": False,
                    "required": ["present", "quantity", "unit", "min", "max", "probe_points", "negative_means_reversed_polarity"],
                    "properties": {
                        "present": {"type": "boolean"},
                        "quantity": {"type": "string", "enum": ["dc_voltage", "dc_current", "resistance", "continuity"]},
                        "unit": {"type": "string", "enum": ["V", "A", "ohm", "bool"]},
                        "min": _nullable("number"), "max": _nullable("number"),
                        "probe_points": {"type": "string"},
                        "negative_means_reversed_polarity": {"type": "boolean"},
                    }},
                "common_mistakes": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["description", "correction"],
                    "properties": {"description": {"type": "string"}, "correction": {"type": "string"}}}},
                "confidence": {"type": "number"},
            },
        }},
    },
}


def _slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:n] or "step"


def _tool(name: str) -> str:
    return _slug(name, 40)


def compile_draft(draft: dict, *, video_id: str | None, job_id: str | None, segments: list[dict], model: str | None) -> dict:
    """Deterministically turn an ExtractionDraft into a SkillGraph document."""
    title = draft["title"].strip() or "Extracted skill"
    skill_id = f"{_slug(title, 40)}_{hashlib.sha1((job_id or title).encode()).hexdigest()[:6]}"
    steps, used = [], set()
    tools = {_tool(t) for t in draft["required_tools"]}
    for i, s in enumerate(draft["steps"]):
        sid = _slug(s["title"], 50)
        while sid in used:
            sid = f"{sid[:56]}_{i}"
        used.add(sid)
        methods = []
        if s["visual_criteria"]:
            methods.append({"type": "visual", "criteria": [
                {"id": f"c{j + 1}", "description": c["description"]} for j, c in enumerate(s["visual_criteria"])]})
        m = s["measurement"]
        if m["present"] and (m["min"] is not None or m["max"] is not None or m["quantity"] == "continuity"):
            methods.append({"type": "measurement", "quantity": m["quantity"], "unit": m["unit"], "min": m["min"],
                            "max": m["max"], "probe_points": m["probe_points"],
                            "negative_means_reversed_polarity": m["negative_means_reversed_polarity"]})
        if not methods:
            methods.append({"type": "learner_confirmation", "prompt": f"I have completed: {s['title']}"})
        step_tools = [_tool(t) for t in s["required_tools"]]
        tools |= set(step_tools)
        refs = []
        for k in s["segment_indices"]:
            if 0 <= k < len(segments):
                seg = segments[k]
                refs.append({"video_id": video_id, "t_start": seg["t_start"], "t_end": seg["t_end"],
                             "frame_paths": seg["frames"][:3], "transcript_excerpt": seg.get("transcript", "")[:500]})
        conf = min(max(float(s["confidence"]), 0.0), 1.0)
        steps.append({
            "step_id": sid, "title": s["title"][:200], "kind": s["kind"], "description": s["description"],
            "instructions": s["instructions"], "required_tools": step_tools,
            "required_components": [_tool(c) for c in s["required_components"]],
            "expected_observations": s["observed_evidence"],
            "validation": {"policy": "all", "methods": methods},
            "safety": {"critical": bool(s["safety_critical"] or s["hazards"]), "hazards": s["hazards"],
                       "requirements": s["safety_requirements"]},
            "common_mistakes": [{"id": f"m{j + 1}", "description": c["description"], "correction": c["correction"]}
                                for j, c in enumerate(s["common_mistakes"])],
            "evidence_refs": refs, "confidence": conf,
            "expert_annotations": [{"text": f"AI inference: {s['inferred_purpose']}"}] if s["inferred_purpose"] else [],
        })
    for a, b in zip(steps, steps[1:], strict=False):
        a["transitions"] = [{"to": b["step_id"]}]
    if steps:
        steps[-1]["terminal"] = True
    return {
        "schema": "skillos.skillgraph/1", "skill_id": skill_id, "title": title, "summary": draft["summary"],
        "difficulty": draft["difficulty"], "estimated_duration": max(1, int(draft["estimated_duration"])),
        "required_tools": sorted(tools), "required_components": sorted({_tool(c) for c in draft["required_components"]}),
        "entry_step": steps[0]["step_id"] if steps else "missing",
        "steps": steps,
        "provenance": {"origin": "extracted", "source_video_id": video_id, "extraction_job_id": job_id, "model": model},
    }


def extract(db: Session, org_id: str, segments: list[dict], transcript: str) -> dict:
    """segments: [{t_start, t_end, frames: [paths], transcript}] — at most a few frames each."""
    content = [gateway.text_part(f"Full transcript (may be empty):\n{transcript[:12000]}")]
    for i, seg in enumerate(segments):
        content.append(gateway.text_part(f"Segment {i}: {seg['t_start']:.1f}s–{seg['t_end']:.1f}s. Speech: {seg.get('transcript', '')[:600]}"))
        for f in seg["frames"][:2]:
            content.append(gateway.image_part(f, detail="low"))
    return gateway.structured(db, org_id=org_id, purpose="extraction", system=SYSTEM, content=content,
                              schema=DRAFT_SCHEMA, name="extraction_draft")
