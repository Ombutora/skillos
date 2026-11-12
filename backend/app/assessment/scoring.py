"""Competency scoring computed only from the session event log.

Every metric carries its numerator and denominator so a reviewer can trace it.
A metric with no evidence is reported as not assessed (None), never guessed.
"""

from dataclasses import dataclass

from app.skillgraph.schema import SkillGraph

LEVELS = ["NOVICE", "DEVELOPING", "COMPETENT", "PROFICIENT", "EXPERT"]

# Explicit criteria behind each session level. Shown to users verbatim.
CRITERIA = {
    "DEVELOPING": "Completed the procedure (guided or independent).",
    "COMPETENT": "Completed with every safety-critical step verified, no safety violations, at most 3 failed checks, and no instructor override on a safety-critical step.",
    "PROFICIENT": "Completed in assessment mode with no assistance, no safety violations, at most 1 failed check and every mandatory step verified.",
    "EXPERT": "The last 3 assessment-mode attempts were all PROFICIENT, spread over at least 2 different days.",
}


@dataclass
class Ratio:
    num: int
    den: int

    def as_dict(self) -> dict:
        return {"numerator": self.num, "denominator": self.den,
                "value": round(self.num / self.den, 4) if self.den else None}


def compute_metrics(events: list[dict], graph: SkillGraph, mode: str) -> dict:
    """`events` are dicts with type, step_key, data, created_at (ISO) in sequence order."""
    path: list[str] = [e["step_key"] for e in events if e["type"] == "step_entered"]
    unique_path = list(dict.fromkeys(path))
    steps = {s.step_id: s for s in graph.steps}
    validations = [e for e in events if e["type"] == "validation"]
    signoffs = [e for e in events if e["type"] == "instructor_signoff" and e["data"].get("approved")]

    verified = {e["step_key"] for e in validations if e["data"]["verdict"] == "VERIFIED"} | {e["step_key"] for e in signoffs}
    mandatory = [s for s in unique_path if steps[s].mandatory]
    critical = [s for s in unique_path if steps[s].safety.critical]

    safety_violation_steps = {e["step_key"] for e in validations if e["data"].get("safety_violation")}
    critical_clean = [s for s in critical if s in verified and s not in safety_violation_steps]

    failed = [e for e in validations if e["data"]["verdict"] == "FAILED"]
    failed_steps = list(dict.fromkeys(e["step_key"] for e in failed))
    recovered = [s for s in failed_steps if s in verified]

    evidence_events = [e for e in events if e["type"] == "evidence"]
    out_of_seq = [e for e in events if e["type"] == "out_of_sequence"]

    # Tool use is only assessed on steps that require a tool and were verified by measured/observed evidence.
    tool_den = tool_num = 0
    for s in unique_path:
        st = steps[s]
        if not st.required_tools or s not in verified:
            continue
        step_vals = [e for e in validations if e["step_key"] == s]
        strong = any(m.type in ("measurement", "visual") for m in st.validation.methods)
        if not strong:
            continue
        tool_den += 1
        unit_errors = any("Expected a reading in" in (e["data"].get("message") or "") for e in step_vals)
        if not unit_errors:
            tool_num += 1

    assistance = [e for e in events if e["type"] == "assistance"]
    uncertain = [e for e in validations if e["data"]["verdict"] == "UNCERTAIN"]
    critical_overrides = [e for e in signoffs if e["data"].get("critical")]

    times = [e["created_at"] for e in events if e.get("created_at")]
    duration_min = None
    if len(times) >= 2:
        from datetime import datetime
        t0, t1 = datetime.fromisoformat(times[0]), datetime.fromisoformat(times[-1])
        duration_min = round((t1 - t0).total_seconds() / 60, 2)

    completed = any(e["type"] == "state_changed" and e.get("to_state") == "COMPLETED" for e in events)

    return {
        "completed": completed,
        "mode": mode,
        "task_completion": Ratio(len([s for s in mandatory if s in verified]), len(mandatory)).as_dict(),
        "correct_sequence": Ratio(len(evidence_events), len(evidence_events) + len(out_of_seq)).as_dict(),
        "safety_compliance": Ratio(len(critical_clean), len(critical)).as_dict(),
        "tool_selection": Ratio(tool_num, tool_den).as_dict(),
        "mistakes": len(failed),
        "mistake_ids": [e["data"].get("mistake") for e in failed if e["data"].get("mistake")],
        "safety_violations": len([e for e in validations if e["data"].get("safety_violation")]),
        "recovery": Ratio(len(recovered), len(failed_steps)).as_dict(),
        "assistance_requests": len(assistance),
        "instructor_signoffs": len(signoffs),
        "critical_instructor_overrides": len(critical_overrides),
        "uncertain_validations": len(uncertain),
        "out_of_sequence_attempts": len(out_of_seq),
        "duration_minutes": duration_min,
        "estimated_minutes": graph.estimated_duration,
        "path": path,
        "branches_taken": [e["data"]["to"] for e in events if e["type"] == "branched"],
    }


def session_level(m: dict) -> tuple[str, list[dict]]:
    trace: list[dict] = []

    def rule(name: str, ok: bool, detail: str) -> bool:
        trace.append({"criterion": name, "passed": ok, "detail": detail})
        return ok

    if not rule("completed", m["completed"], "procedure reached a terminal step"):
        return "NOVICE", trace
    level = "DEVELOPING"
    sc = m["safety_compliance"]
    competent = all([
        rule("all_critical_verified", sc["denominator"] == 0 or sc["numerator"] == sc["denominator"], f"{sc['numerator']}/{sc['denominator']} safety-critical steps verified cleanly"),
        rule("no_safety_violations", m["safety_violations"] == 0, f"{m['safety_violations']} safety violations"),
        rule("failed_checks_le_3", m["mistakes"] <= 3, f"{m['mistakes']} failed checks"),
        rule("no_critical_override", m["critical_instructor_overrides"] == 0, f"{m['critical_instructor_overrides']} instructor overrides on safety-critical steps"),
    ])
    if not competent:
        return level, trace
    level = "COMPETENT"
    tc = m["task_completion"]
    proficient = all([
        rule("assessment_mode", m["mode"] == "assessment", f"mode={m['mode']}"),
        rule("no_assistance", m["assistance_requests"] == 0 and m["instructor_signoffs"] == 0, f"{m['assistance_requests']} assistance, {m['instructor_signoffs']} sign-offs"),
        rule("failed_checks_le_1", m["mistakes"] <= 1, f"{m['mistakes']} failed checks"),
        rule("all_mandatory_verified", tc["numerator"] == tc["denominator"], f"{tc['numerator']}/{tc['denominator']} mandatory steps"),
    ])
    return ("PROFICIENT" if proficient else level), trace


def profile_level(history: list[dict]) -> tuple[str, dict]:
    """`history`: completed-or-not reports, oldest first, each with mode, session_level, created_at."""
    completed = [h for h in history if h["session_level"] != "NOVICE"]
    assessments = [h for h in history if h["mode"] == "assessment"]
    guided_done = [h for h in completed if h["mode"] == "guided"]
    independent_done = [h for h in completed if h["mode"] == "assessment"]
    evidence = {
        "attempts": len(history),
        "completions": len(completed),
        "guided_completions": len(guided_done),
        "independent_completions": len(independent_done),
        "first_attempt_success": bool(history) and history[0]["session_level"] in ("COMPETENT", "PROFICIENT"),
        "criteria": CRITERIA,
    }
    level = "NOVICE"
    if completed:
        level = "DEVELOPING"
    if any(h["session_level"] in ("COMPETENT", "PROFICIENT") for h in completed):
        level = "COMPETENT"
    if assessments and assessments[-1]["session_level"] == "PROFICIENT":
        level = "PROFICIENT"
    last3 = assessments[-3:]
    days = {h["created_at"][:10] for h in last3}
    if len(last3) == 3 and all(h["session_level"] == "PROFICIENT" for h in last3) and len(days) >= 2:
        level = "EXPERT"
    evidence["basis"] = f"level {level} per criteria; latest assessment-mode result: {assessments[-1]['session_level'] if assessments else 'none'}"
    return level, evidence
