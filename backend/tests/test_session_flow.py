"""End-to-end learner sessions on the seeded solar modules.

The observation agent (OpenAI vision) is replaced with a stub returning fixed per-criterion
observations, so these tests exercise the real upload → validation → state machine path
without network access. The stub is test-only.
"""

import io

import pytest

from app.api.v1 import sessions as sessions_api
from app.skillgraph.schema import VisualValidation
from app.validation.evidence import VisualEvidence

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
API = "/api/v1"


@pytest.fixture
def vision(monkeypatch):
    """Queue of {criterion_id: (status, confidence)}; empty dict = everything observed at 0.95."""
    queue: list[dict] = []

    def fake_observe(db, org_id, step, method_index, frame_path, detections=None):
        m = step.validation.methods[method_index]
        assert isinstance(m, VisualValidation)
        spec = queue.pop(0) if queue else {}
        obs = [{"criterion_id": c.id, "status": spec.get(c.id, ("observed", 0.95))[0],
                "confidence": spec.get(c.id, ("observed", 0.95))[1]} for c in m.criteria]
        return VisualEvidence(method_index=method_index, observations=obs, frame_path=str(frame_path), image_quality="ok")

    monkeypatch.setattr(sessions_api.observation, "observe", fake_observe)
    return queue


class Run:
    def __init__(self, client, headers, skill_slug, mode="guided", consent=True):
        self.c, self.h = client, headers
        skills = client.get(f"{API}/skills", headers=headers).json()["items"]
        title_key = {"solar_installation_001": "Installation", "solar_troubleshooting_001": "Troubleshooting",
                     "solar_components_001": "Identification"}[skill_slug]
        self.skill = next(s for s in skills if title_key in s["title"])
        self.id = client.post(f"{API}/sessions", json={"skill_id": self.skill["id"], "mode": mode}, headers=headers).json()["id"]
        r = client.post(f"{API}/sessions/{self.id}/start", headers=headers)
        assert r.status_code == 200, r.text
        assert "low-voltage" in r.json()["briefing"]["scope"]
        r = client.post(f"{API}/sessions/{self.id}/acknowledge", json={"safety_briefing_ack": True, "recording_consent": consent}, headers=headers)
        assert r.status_code == 200, r.text

    @property
    def state(self):
        return self.c.get(f"{API}/sessions/{self.id}", headers=self.h).json()["session"]

    def observe(self, step, mi=0, expect=200):
        r = self.c.post(f"{API}/sessions/{self.id}/observe", data={"step_id": step, "method_index": str(mi)},
                        files={"frame": ("f.jpg", io.BytesIO(JPEG), "image/jpeg")}, headers=self.h)
        assert r.status_code == expect, r.text
        return r.json()

    def measure(self, step, value, mi=0, unit="V", expect=200):
        r = self.c.post(f"{API}/sessions/{self.id}/evidence",
                        json={"step_id": step, "items": [{"type": "measurement", "method_index": mi, "value": value, "unit": unit}]},
                        headers=self.h)
        assert r.status_code == expect, r.text
        return r.json()

    def confirm(self, step, mi):
        r = self.c.post(f"{API}/sessions/{self.id}/evidence",
                        json={"step_id": step, "items": [{"type": "learner_confirmation", "method_index": mi, "confirmed": True}]},
                        headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()

    def report(self):
        r = self.c.post(f"{API}/sessions/{self.id}/complete", headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()


def install_until_connect(run: Run):
    assert run.observe("identify_components")["validation"]["verdict"] == "VERIFIED"
    run.observe("inspect_battery")
    assert run.confirm("inspect_battery", 1)["validation"]["verdict"] == "VERIFIED"
    assert run.measure("check_battery_voltage", 12.7)["validation"]["verdict"] == "VERIFIED"
    run.observe("isolate_system")
    assert run.confirm("isolate_system", 1)["session"]["current_step"] == "connect_battery"


def finish_install(run: Run, vision, fail_test_once=False):
    run.observe("connect_load")
    run.observe("connect_panel")
    assert run.measure("connect_panel", 18.4, mi=1)["session"]["current_step"] == "test_system"
    if fail_test_once:
        vision.append({"led_lit": ("contradicted", 0.95)})
        r = run.observe("test_system")
        assert r["validation"]["verdict"] == "FAILED"
        assert r["session"]["current_step"] == "ts_inspect_wiring"  # troubleshooting branch, not completion
        run.observe("ts_inspect_wiring")
        assert run.confirm("ts_inspect_wiring", 1)["session"]["current_step"] == "test_system"
    run.observe("test_system")
    assert run.measure("test_system", 12.4, mi=1)["session"]["current_step"] == "handover"
    r = run.observe("handover")
    assert r["session"]["state"] == "COMPLETED"


def test_hackathon_demo_flow(client, learner, vision):
    """Reversed polarity is detected, blocks the session, is corrected, and shows up in the report."""
    run = Run(client, learner, "solar_installation_001")
    install_until_connect(run)

    run.observe("connect_battery")
    r = run.measure("connect_battery", -12.6, mi=1)
    v = r["validation"]
    assert v["verdict"] == "FAILED" and v["safety_violation"] and v["detected_mistake_id"] == "reversed_battery_polarity"
    assert r["session"]["state"] == "BLOCKED_BY_SAFETY"
    # cannot skip ahead while blocked
    assert run.observe("connect_load", expect=409)
    # learner corrects the wiring; the measurement now verifies (visual evidence from this attempt still counts)
    r = run.measure("connect_battery", 12.6, mi=1)
    assert r["validation"]["verdict"] == "VERIFIED" and r["session"]["current_step"] == "connect_load"

    finish_install(run, vision, fail_test_once=True)
    rep = run.report()
    m = rep["metrics"]
    assert m["completed"] and m["mistakes"] == 2 and m["safety_violations"] == 1
    assert m["mistake_ids"] == ["reversed_battery_polarity"]
    assert m["recovery"]["value"] == 1.0
    assert m["branches_taken"] == ["ts_inspect_wiring"]
    assert m["task_completion"]["value"] == 1.0
    assert m["safety_compliance"]["numerator"] < m["safety_compliance"]["denominator"]
    assert rep["session_level"] == "DEVELOPING"  # completed, but had a safety violation
    assert any(t["criterion"] == "no_safety_violations" and not t["passed"] for t in rep["rule_trace"])


def test_unclear_camera_view_returns_uncertain(client, learner, vision):
    run = Run(client, learner, "solar_installation_001")
    vision.append({"panel_visible": ("not_visible", 0.9)})
    r = run.observe("identify_components")
    assert r["validation"]["verdict"] == "UNCERTAIN"
    assert r["session"]["state"] == "AWAITING_EVIDENCE"
    assert r["session"]["current_step"] == "identify_components"
    assert "Cannot see" in r["validation"]["message"]
    # a clearer frame then verifies
    assert run.observe("identify_components")["validation"]["verdict"] == "VERIFIED"


def test_clients_cannot_self_assert_visual_evidence(client, learner):
    run = Run(client, learner, "solar_installation_001")
    r = client.post(f"{API}/sessions/{run.id}/evidence", headers=learner, json={"step_id": "identify_components", "items": [
        {"type": "visual", "method_index": 0, "observations": [{"criterion_id": "panel_visible", "status": "observed", "confidence": 1}]}]})
    assert r.status_code == 403


def test_out_of_sequence_is_rejected_and_scored(client, learner, vision):
    run = Run(client, learner, "solar_installation_001")
    r = run.measure("connect_battery", 12.6, mi=1, expect=409)
    assert r["detail"]["code"] == "out_of_sequence"
    events = client.get(f"{API}/sessions/{run.id}/events", headers=learner).json()
    assert any(e["type"] == "out_of_sequence" for e in events)


def test_camera_requires_consent(client, learner, vision):
    run = Run(client, learner, "solar_installation_001", consent=False)
    run.observe("identify_components", expect=403)


def test_briefing_must_be_acknowledged(client, learner):
    skills = client.get(f"{API}/skills", headers=learner).json()["items"]
    sid = client.post(f"{API}/sessions", json={"skill_id": skills[0]["id"]}, headers=learner).json()["id"]
    client.post(f"{API}/sessions/{sid}/start", headers=learner)
    r = client.post(f"{API}/sessions/{sid}/acknowledge", json={"safety_briefing_ack": False, "recording_consent": True}, headers=learner)
    assert r.status_code == 422


def test_report_only_after_completion(client, learner):
    run = Run(client, learner, "solar_installation_001")
    assert client.post(f"{API}/sessions/{run.id}/complete", headers=learner).status_code == 409


def test_other_learner_cannot_act(client, learner, vision):
    from conftest import login

    run = Run(client, learner, "solar_installation_001")
    other = login(client, "learner2@demo.skillos.dev")
    assert client.get(f"{API}/sessions/{run.id}", headers=other).status_code == 404


def test_clean_assessment_run_is_proficient_and_profile_updates(client, learner, vision):
    run = Run(client, learner, "solar_installation_001", mode="assessment")
    install_until_connect(run)
    run.observe("connect_battery")
    run.measure("connect_battery", 12.6, mi=1)
    finish_install(run, vision)
    rep = run.report()
    assert rep["session_level"] == "PROFICIENT"
    assert rep["metrics"]["safety_compliance"]["value"] == 1.0
    assert rep["metrics"]["tool_selection"]["denominator"] > 0
    me = client.get(f"{API}/auth/me", headers=learner).json()
    comps = client.get(f"{API}/users/{me['id']}/competencies", headers=learner).json()
    assert comps[0]["level"] == "PROFICIENT" and comps[0]["evidence"]["independent_completions"] == 1


def test_assistance_prevents_proficient(client, learner, vision):
    run = Run(client, learner, "solar_installation_001", mode="assessment")
    r = client.post(f"{API}/sessions/{run.id}/assist", json={"question": "Which terminal first?"}, headers=learner)
    assert r.json()["source"] == "approved_skill_text"  # AI not configured: labelled fallback, not a fake answer
    install_until_connect(run)
    run.observe("connect_battery")
    run.measure("connect_battery", 12.6, mi=1)
    finish_install(run, vision)
    assert run.report()["session_level"] == "COMPETENT"


def test_human_review_signoff(client, learner, expert, vision):
    run = Run(client, learner, "solar_components_001")
    vision.append({"panel_shown": ("not_visible", 0.9)})
    run.observe("id_panel")
    client.post(f"{API}/sessions/{run.id}/escalate", json={"reason": "camera broken"}, headers=learner)
    assert run.state["state"] == "NEEDS_HUMAN_REVIEW"
    # learners cannot sign off their own work
    assert client.post(f"{API}/sessions/{run.id}/signoff", json={"approved": True}, headers=learner).status_code == 403
    r = client.post(f"{API}/sessions/{run.id}/signoff", json={"approved": True, "comment": "seen in person"}, headers=expert)
    assert r.status_code == 200 and r.json()["current_step"] == "id_battery"


def test_troubleshooting_diagnosis_is_not_a_mistake(client, learner, vision):
    run = Run(client, learner, "solar_troubleshooting_001")
    vision.append({"led_off": ("observed", 0.95)})
    run.observe("confirm_symptom")
    run.measure("measure_battery", 12.5)
    r = run.measure("check_controller_polarity", -12.5)  # the injected fault
    assert r["validation"]["verdict"] == "VERIFIED"
    assert r["session"]["current_step"] == "fix_battery_polarity"
    run.measure("fix_battery_polarity", 12.5)
    run.observe("inspect_load_wiring")
    run.confirm("inspect_load_wiring", 1)
    run.measure("check_panel", 18.0)
    run.observe("retest")
    assert run.measure("retest", 12.4, mi=1)["session"]["state"] == "COMPLETED"
    rep = run.report()
    assert rep["metrics"]["mistakes"] == 0 and rep["metrics"]["safety_violations"] == 0
    assert "fix_battery_polarity" in rep["metrics"]["branches_taken"]


def test_low_battery_branch(client, learner, vision):
    run = Run(client, learner, "solar_troubleshooting_001")
    run.observe("confirm_symptom")
    r = run.measure("measure_battery", 10.9)
    assert r["session"]["current_step"] == "diagnose_low_battery"
    assert run.confirm("diagnose_low_battery", 0)["session"]["state"] == "COMPLETED"


def test_same_skill_trains_learners_consistently(client, learner, vision):
    """Reproducibility: identical evidence yields identical verdicts and scores for different learners."""
    from conftest import login

    reports = []
    for h in (learner, login(client, "learner2@demo.skillos.dev")):
        run = Run(client, h, "solar_installation_001", mode="assessment")
        install_until_connect(run)
        run.observe("connect_battery")
        run.measure("connect_battery", 12.6, mi=1)
        finish_install(run, vision)
        reports.append(run.report())
    a, b = (r["metrics"] for r in reports)
    for k in ("task_completion", "correct_sequence", "safety_compliance", "tool_selection", "mistakes", "path"):
        assert a[k] == b[k]
    assert reports[0]["session_level"] == reports[1]["session_level"]


def test_websocket_pushes_validation(client, learner, vision):
    run = Run(client, learner, "solar_installation_001")
    token = learner["Authorization"].split()[1]
    with client.websocket_connect(f"{API}/sessions/{run.id}/ws?token={token}") as ws:
        run.observe("identify_components")
        msg = ws.receive_json()
        assert msg["type"] == "validation"
        assert msg["validation"]["verdict"] == "VERIFIED"
        assert msg["session"]["current_step"] == "inspect_battery"


def test_websocket_rejects_bad_token(client, learner):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    run = Run(client, learner, "solar_installation_001")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{API}/sessions/{run.id}/ws?token=bogus") as ws:
            ws.receive_json()
