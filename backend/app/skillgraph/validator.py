"""Publish gate for skill graphs.

Errors block publication. Warnings must be acknowledged by the approving expert.
"""

from dataclasses import asdict, dataclass, field

import networkx as nx
from pydantic import ValidationError

from app.skillgraph.graph import flow_graph
from app.skillgraph.schema import SkillGraph

ELECTRICAL_HAZARDS = {"short_circuit", "reversed_polarity", "overheating", "fire", "electric_shock"}
# Phrases that suggest the procedure leaves the low-voltage training scope.
OUT_OF_SCOPE_TERMS = ("230v", "240v", "220v", "mains", "grid tie", "grid-tie", "ac panel", "consumer unit")


@dataclass
class Issue:
    code: str
    message: str
    step_id: str | None = None
    severity: str = "error"


@dataclass
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [asdict(i) for i in self.errors],
            "warnings": [asdict(i) for i in self.warnings],
        }


def parse_graph(doc: dict) -> tuple[SkillGraph | None, ValidationReport]:
    report = ValidationReport()
    try:
        return SkillGraph.model_validate(doc), report
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            report.errors.append(Issue("schema", f"{loc}: {err['msg']}"))
        return None, report


def validate_graph(doc: dict, confidence_warning: float = 0.6) -> ValidationReport:
    g, report = parse_graph(doc)
    if g is None:
        return report
    err, warn = report.errors.append, report.warnings.append
    ids = [s.step_id for s in g.steps]
    idset = set(ids)

    # identity and references
    for dup in {i for i in ids if ids.count(i) > 1}:
        err(Issue("duplicate_step", f"step id '{dup}' is used more than once", dup))
    if g.entry_step not in idset:
        err(Issue("missing_entry", f"entry_step '{g.entry_step}' does not exist"))
        return report

    skill_tools = set(g.required_tools)
    for s in g.steps:
        for t in s.transitions:
            if t.to not in idset:
                err(Issue("dangling_transition", f"transition to unknown step '{t.to}'", s.step_id))
            if t.condition.type.startswith("measurement_"):
                idx = t.condition.method_index
                methods = s.validation.methods
                if idx is None or not (0 <= idx < len(methods)) or methods[idx].type != "measurement":
                    err(Issue("bad_condition", "measurement condition must reference a measurement method", s.step_id))
                if t.condition.type in ("measurement_below", "measurement_above") and t.condition.value is None:
                    err(Issue("bad_condition", f"{t.condition.type} needs a value", s.step_id))
        for mk in s.common_mistakes:
            t = mk.trigger
            if t is None:
                continue
            methods = s.validation.methods
            if t.method_index >= len(methods):
                err(Issue("bad_trigger", f"mistake '{mk.id}' references missing method {t.method_index}", s.step_id))
                continue
            m = methods[t.method_index]
            if t.when in ("negative", "below_min", "above_max") and m.type != "measurement":
                err(Issue("bad_trigger", f"mistake '{mk.id}' uses '{t.when}' on a {m.type} method", s.step_id))
            if t.when == "contradicted":
                if m.type != "visual" or (t.criterion_id and t.criterion_id not in {c.id for c in m.criteria}):
                    err(Issue("bad_trigger", f"mistake '{mk.id}' references an unknown visual criterion", s.step_id))
        for p in s.prerequisites:
            if p not in idset:
                err(Issue("dangling_prerequisite", f"prerequisite '{p}' does not exist", s.step_id))
            if p == s.step_id:
                err(Issue("self_prerequisite", "step lists itself as prerequisite", s.step_id))
        for a in s.alternatives:
            if a not in idset:
                err(Issue("dangling_alternative", f"alternative '{a}' does not exist", s.step_id))
        if not s.terminal and not s.transitions:
            err(Issue("dead_end", "non-terminal step has no outgoing transitions", s.step_id))
        if s.terminal and s.transitions:
            warn(Issue("terminal_with_transitions", "terminal step has transitions that will never be followed", s.step_id, "warning"))
        if not s.instructions:
            warn(Issue("no_instructions", "step has no learner instructions", s.step_id, "warning"))
        for tool in s.required_tools:
            if tool not in skill_tools:
                err(Issue("missing_tool", f"tool '{tool}' is not listed in skill.required_tools", s.step_id))

        # safety rules
        types = {m.type for m in s.validation.methods}
        hazards = set(s.safety.hazards)
        if hazards & ELECTRICAL_HAZARDS and not s.safety.critical:
            err(Issue("hazard_not_critical", f"step with hazards {sorted(hazards & ELECTRICAL_HAZARDS)} must be safety-critical", s.step_id))
        if s.safety.critical:
            if types <= {"learner_confirmation"}:
                err(Issue("weak_safety_validation", "safety-critical step cannot rely on learner confirmation alone", s.step_id))
            if s.validation.policy == "any" and "learner_confirmation" in types:
                err(Issue("weak_safety_validation", "safety-critical step with policy 'any' could pass on confirmation alone", s.step_id))
            if not s.safety.requirements:
                err(Issue("missing_safety_requirements", "safety-critical step lists no safety requirements", s.step_id))
            if not s.mandatory:
                err(Issue("optional_safety_step", "safety-critical steps must be mandatory", s.step_id))
            if "reversed_polarity" in hazards and "measurement" not in types:
                err(Issue("polarity_needs_measurement", "polarity cannot be verified visually alone; add a measurement method", s.step_id))
        if s.kind in ("action", "test") and s.required_tools == [] and hazards & ELECTRICAL_HAZARDS:
            warn(Issue("no_tool_on_electrical_step", "electrical step lists no tools", s.step_id, "warning"))

        # extraction quality
        if s.confidence is not None and s.confidence < confidence_warning:
            warn(Issue("low_confidence", f"extraction confidence {s.confidence:.2f} is below {confidence_warning}", s.step_id, "warning"))
        if g.provenance.origin == "extracted" and not s.evidence_refs:
            warn(Issue("unverified_assumption", "generated step has no source evidence; it may be inferred, not observed", s.step_id, "warning"))

        text = " ".join([s.title, s.description, *s.instructions]).lower()
        for term in OUT_OF_SCOPE_TERMS:
            if term in text:
                err(Issue("out_of_scope_voltage", f"mentions '{term}'; MVP is limited to isolated low-voltage DC", s.step_id))

    if report.errors:
        return report

    # graph structure
    fg = flow_graph(g)
    reachable = nx.descendants(fg, g.entry_step) | {g.entry_step}
    for s in g.steps:
        if s.step_id not in reachable:
            err(Issue("unreachable", "step cannot be reached from the entry step", s.step_id))
    terminals = {s.step_id for s in g.steps if s.terminal}
    if not terminals:
        err(Issue("no_terminal", "skill has no terminal step"))
    else:
        for n in reachable:
            if not (nx.descendants(fg, n) | {n}) & terminals:
                err(Issue("no_exit", "no path from this step reaches a terminal step", n))

    # cycles are allowed only when they pass through a failure/branch edge (retry/troubleshoot loops)
    forward = nx.DiGraph(
        (u, v) for u, v, c in fg.edges(data="condition") if c in ("verified", "always", "measurement_in_range")
    )
    for cycle in nx.simple_cycles(forward):
        err(Issue("forward_cycle", f"steps {cycle} form a loop on success edges"))

    # prerequisites must be satisfiable: each prerequisite must be able to occur before the step
    for s in g.steps:
        for p in s.prerequisites:
            if p in reachable and s.step_id in reachable and not nx.has_path(fg, p, s.step_id):
                err(Issue("unsatisfiable_prerequisite", f"prerequisite '{p}' can never come before this step", s.step_id))

    # every electrical skill should include some measurement
    all_types = {m.type for s in g.steps for m in s.validation.methods}
    if any(set(s.safety.hazards) & ELECTRICAL_HAZARDS for s in g.steps) and "measurement" not in all_types:
        err(Issue("no_measurements", "electrical skill contains no measurement-based validation"))

    return report
