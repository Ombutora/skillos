import pytest
from conftest import load

from app.skillgraph.graph import happy_path, to_networkx
from app.skillgraph.validator import validate_graph


def codes(graph):
    r = validate_graph(graph)
    return {e.code for e in r.errors}, {w.code for w in r.warnings}


@pytest.mark.parametrize("name", ["solar_installation", "solar_troubleshooting", "solar_components"])
def test_seed_modules_are_publishable(name):
    errors, _ = codes(load(name))
    assert errors == set()


def step(g, sid):
    return next(s for s in g["steps"] if s["step_id"] == sid)


def test_schema_errors_are_reported_not_raised():
    errors, _ = codes({"title": "x"})
    assert errors == {"schema"}


def test_dangling_transition():
    g = load("solar_installation")
    step(g, "inspect_battery")["transitions"] = [{"to": "nope"}]
    assert "dangling_transition" in codes(g)[0]


def test_critical_step_cannot_rely_on_confirmation_only():
    g = load("solar_installation")
    step(g, "isolate_system")["validation"] = {"methods": [{"type": "learner_confirmation", "prompt": "done"}]}
    assert "weak_safety_validation" in codes(g)[0]


def test_polarity_hazard_requires_measurement():
    g = load("solar_installation")
    s = step(g, "connect_battery")
    s["validation"]["methods"] = [s["validation"]["methods"][0]]
    s["common_mistakes"] = []
    assert "polarity_needs_measurement" in codes(g)[0]


def test_electrical_hazard_must_be_safety_critical():
    g = load("solar_installation")
    step(g, "connect_load")["safety"]["critical"] = False
    assert "hazard_not_critical" in codes(g)[0]


def test_mains_voltage_is_out_of_scope():
    g = load("solar_installation")
    step(g, "test_system")["instructions"].append("Connect the inverter to 230V mains.")
    assert "out_of_scope_voltage" in codes(g)[0]


def test_tool_must_be_declared_at_skill_level():
    g = load("solar_installation")
    step(g, "connect_load")["required_tools"].append("soldering_iron")
    assert "missing_tool" in codes(g)[0]


def test_unreachable_and_no_terminal():
    g = load("solar_components")
    g["steps"][-1]["terminal"] = False
    g["steps"][-1]["transitions"] = [{"to": "id_panel", "condition": {"type": "failed"}}]
    errors, _ = codes(g)
    assert "no_terminal" in errors


def test_forward_cycle_rejected_but_failure_loop_allowed():
    g = load("solar_installation")
    # failure loop test_system -> ts_inspect_wiring -> test_system is valid
    assert "forward_cycle" not in codes(g)[0]
    step(g, "handover")["terminal"] = False
    step(g, "handover")["transitions"] = [{"to": "test_system"}]
    errors, _ = codes(g)
    assert "forward_cycle" in errors or "no_terminal" in errors


def test_bad_mistake_trigger():
    g = load("solar_installation")
    step(g, "connect_battery")["common_mistakes"][0]["trigger"] = {"method_index": 0, "when": "negative"}
    assert "bad_trigger" in codes(g)[0]


def test_extracted_graph_warnings():
    g = load("solar_components")
    g["provenance"] = {"origin": "extracted"}
    g["steps"][0]["confidence"] = 0.3
    errors, warnings = codes(g)
    assert not errors
    assert {"low_confidence", "unverified_assumption"} <= warnings


def test_graph_supports_branching():
    from app.skillgraph.schema import SkillGraph

    g = SkillGraph.model_validate(load("solar_installation"))
    nxg = to_networkx(g)
    assert nxg.has_edge("test_system", "ts_inspect_wiring")
    assert nxg.edges["test_system", "ts_inspect_wiring"]["condition"] == "failed"
    assert "tool:multimeter" in nxg
    assert happy_path(g)[-1] == "handover"
