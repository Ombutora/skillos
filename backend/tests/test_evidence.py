from conftest import load

from app.sessions.state_machine import ALLOWED, InvalidTransition, S, check
from app.skillgraph.schema import SkillGraph
from app.validation.evidence import (
    ConfirmationEvidence,
    MeasurementEvidence,
    VisualEvidence,
    Verdict,
    evaluate_step,
)

G = SkillGraph.model_validate(load("solar_installation"))
CONNECT = G.step("connect_battery")


def vis(i, **statuses):
    return VisualEvidence(method_index=i, observations=[
        {"criterion_id": k, "status": v[0], "confidence": v[1]} for k, v in statuses.items()])


GOOD_VIS = vis(0, red_on_bat_pos=("observed", 0.95), black_on_bat_neg=("observed", 0.9))


def test_verified_needs_all_methods():
    v = evaluate_step(CONNECT, [GOOD_VIS, MeasurementEvidence(method_index=1, value=12.6, unit="V")])
    assert v.verdict == Verdict.VERIFIED


def test_visual_alone_cannot_verify_polarity_step():
    v = evaluate_step(CONNECT, [GOOD_VIS])
    assert v.verdict == Verdict.UNCERTAIN
    assert "measurement" in v.message.lower()


def test_reversed_polarity_fails_with_safety_violation_and_correction():
    v = evaluate_step(CONNECT, [GOOD_VIS, MeasurementEvidence(method_index=1, value=-12.5, unit="V")])
    assert v.verdict == Verdict.FAILED
    assert v.safety_violation
    assert v.mistake.id == "reversed_battery_polarity"
    assert v.message.startswith("STOP.")
    assert "swap" in v.message


def test_not_visible_is_uncertain_not_success():
    v = evaluate_step(CONNECT, [vis(0, red_on_bat_pos=("observed", 0.95), black_on_bat_neg=("not_visible", 0.9)),
                                MeasurementEvidence(method_index=1, value=12.6, unit="V")])
    assert v.verdict == Verdict.UNCERTAIN


def test_low_confidence_is_uncertain():
    v = evaluate_step(CONNECT, [vis(0, red_on_bat_pos=("observed", 0.6), black_on_bat_neg=("observed", 0.95)),
                                MeasurementEvidence(method_index=1, value=12.6, unit="V")])
    assert v.verdict == Verdict.UNCERTAIN


def test_confident_contradiction_fails():
    v = evaluate_step(CONNECT, [vis(0, red_on_bat_pos=("contradicted", 0.92), black_on_bat_neg=("observed", 0.9))])
    assert v.verdict == Verdict.FAILED
    assert v.mistake.id == "red_on_wrong_terminal"


def test_low_confidence_contradiction_is_uncertain():
    v = evaluate_step(CONNECT, [vis(0, red_on_bat_pos=("contradicted", 0.4), black_on_bat_neg=("observed", 0.9)),
                                MeasurementEvidence(method_index=1, value=12.6, unit="V")])
    assert v.verdict == Verdict.UNCERTAIN


def test_detector_alone_never_verifies():
    s = G.step("identify_components")
    ev = VisualEvidence(method_index=0, source="cv_detector", observations=[
        {"criterion_id": c.id, "status": "observed", "confidence": 0.99} for c in s.validation.methods[0].criteria])
    assert evaluate_step(s, [ev]).verdict == Verdict.UNCERTAIN


def test_wrong_unit_is_uncertain():
    v = evaluate_step(G.step("check_battery_voltage"), [MeasurementEvidence(method_index=0, value=12.6, unit="A")])
    assert v.verdict == Verdict.UNCERTAIN


def test_below_range_matches_mistake():
    v = evaluate_step(G.step("check_battery_voltage"), [MeasurementEvidence(method_index=0, value=10.9, unit="V")])
    assert v.verdict == Verdict.FAILED and v.mistake.id == "battery_discharged"


def test_no_evidence_is_uncertain():
    assert evaluate_step(CONNECT, []).verdict == Verdict.UNCERTAIN


def test_runtime_guard_on_confirmation_only_critical_step():
    s = G.step("isolate_system").model_copy(deep=True)
    s.validation.policy = "any"
    v = evaluate_step(s, [ConfirmationEvidence(method_index=1, confirmed=True)])
    assert v.verdict == Verdict.UNCERTAIN


def test_state_machine_rejects_skips():
    check("IN_PROGRESS", "VALIDATING")
    for bad in [("IN_PROGRESS", "COMPLETED"), ("BLOCKED_BY_SAFETY", "IN_PROGRESS"), ("COMPLETED", "IN_PROGRESS"),
                ("CREATED", "IN_PROGRESS"), ("VALIDATING", "COMPLETED")]:
        try:
            check(*bad)
            raise AssertionError(f"{bad} should be rejected")
        except InvalidTransition:
            pass
    assert ALLOWED[S.COMPLETED] == set()
