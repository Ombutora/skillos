"""API tests: auth, RBAC, org isolation, skills lifecycle, uploads, extraction gating."""

import io

from conftest import load, login


def test_register_login_refresh_me(client):
    r = client.post("/api/v1/auth/register", json={"email": "Owner@Example.com", "password": "a-long-password",
                                                    "full_name": "Owner", "organization_name": "Acme Solar"})
    assert r.status_code == 201
    tok = r.json()
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    assert me["email"] == "owner@example.com" and me["role"] == "admin"
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 200
    # refresh tokens are not access tokens
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok['refresh_token']}"}).status_code == 401
    assert client.post("/api/v1/auth/register", json={"email": "owner@example.com", "password": "a-long-password",
                                                       "full_name": "x", "organization_name": "Other"}).status_code == 409


def test_bad_login_and_weak_password(client, demo):
    assert client.post("/api/v1/auth/login", json={"email": "learner@demo.skillos.dev", "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "short", "full_name": "x",
                                                       "organization_name": "Org"}).status_code == 422


def test_unauthenticated_and_rate_limit(client, demo):
    assert client.get("/api/v1/skills").status_code == 401
    codes = [client.post("/api/v1/auth/login", json={"email": "x@y.co", "password": "nope"}).status_code for _ in range(22)]
    assert 429 in codes


def test_rbac(client, learner, admin):
    g = load("solar_components")
    g["skill_id"] = "another"
    assert client.post("/api/v1/skills", json={"graph": g}, headers=learner).status_code == 403
    assert client.post("/api/v1/users", json={"email": "n@x.co", "full_name": "N", "password": "long-enough-pw",
                                              "role": "learner"}, headers=learner).status_code == 403
    r = client.post("/api/v1/users", json={"email": "n@x.co", "full_name": "N", "password": "long-enough-pw",
                                           "role": "learner"}, headers=admin)
    assert r.status_code == 201


def test_org_isolation(client, demo, learner):
    r = client.post("/api/v1/auth/register", json={"email": "other@corp.co", "password": "a-long-password",
                                                    "full_name": "Other", "organization_name": "Other Corp"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    skill_id = client.get("/api/v1/skills", headers=learner).json()["items"][0]["id"]
    assert client.get(f"/api/v1/skills/{skill_id}", headers=other).status_code == 404
    assert client.get("/api/v1/skills", headers=other).json()["total"] == 0
    sess = client.post("/api/v1/sessions", json={"skill_id": skill_id}, headers=learner).json()
    assert client.get(f"/api/v1/sessions/{sess['id']}", headers=other).status_code == 404


def test_skill_lifecycle_and_publish_gate(client, expert, learner):
    g = load("solar_components")
    g["skill_id"] = "components_v2"
    g["steps"][0]["confidence"] = 0.4  # triggers a warning
    r = client.post("/api/v1/skills", json={"graph": g}, headers=expert)
    assert r.status_code == 201
    skill = r.json()
    # drafts are hidden from learners
    assert client.get(f"/api/v1/skills/{skill['id']}", headers=learner).status_code == 404

    # warnings must be acknowledged
    r = client.post(f"/api/v1/skills/{skill['id']}/publish", json={}, headers=expert)
    assert r.status_code == 422 and "low_confidence:id_panel" in r.json()["detail"]["unacknowledged"]

    # a broken edit becomes a new draft version that cannot be published
    bad = load("solar_components")
    bad["skill_id"] = "components_v2"
    bad["steps"][0]["transitions"] = [{"to": "ghost"}]
    v2 = client.put(f"/api/v1/skills/{skill['id']}", json={"graph": bad}, headers=expert).json()
    assert v2["version_number"] == 2 and not v2["validation_report"]["ok"]
    r = client.post(f"/api/v1/skills/{skill['id']}/publish?version_id={v2['id']}", json={}, headers=expert)
    assert r.status_code == 422

    v1 = client.get(f"/api/v1/skills/{skill['id']}", headers=expert).json()["versions"][0]
    r = client.post(f"/api/v1/skills/{skill['id']}/publish?version_id={v1['id']}",
                    json={"acknowledged_warnings": ["low_confidence:id_panel"]}, headers=expert)
    assert r.status_code == 200 and r.json()["status"] == "published"
    detail = client.get(f"/api/v1/skills/{skill['id']}", headers=learner).json()
    assert [v["id"] for v in detail["versions"]] == [v1["id"]]
    graph = client.get(f"/api/v1/skills/{skill['id']}/graph", headers=learner).json()
    assert graph["happy_path"][0] == "id_panel"


def test_invalid_schema_rejected(client, expert):
    r = client.post("/api/v1/skills", json={"graph": {"skill_id": "x"}}, headers=expert)
    assert r.status_code == 422


def test_video_upload_validation(client, expert, learner):
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1000
    files = {"file": ("demo.mp4", io.BytesIO(fake_mp4), "video/mp4")}
    assert client.post("/api/v1/videos/upload", files=files, data={"title": "t", "consent_confirmed": "true"},
                       headers=learner).status_code == 403
    files = {"file": ("evil.mp4", io.BytesIO(b"#!/bin/sh\nrm -rf /"), "video/mp4")}
    assert client.post("/api/v1/videos/upload", files=files, data={"title": "t", "consent_confirmed": "true"},
                       headers=expert).status_code == 415
    files = {"file": ("demo.mp4", io.BytesIO(fake_mp4), "video/mp4")}
    assert client.post("/api/v1/videos/upload", files=files, data={"title": "t", "consent_confirmed": "false"},
                       headers=expert).status_code == 422
    files = {"file": ("../../demo.mp4", io.BytesIO(fake_mp4), "video/mp4")}
    r = client.post("/api/v1/videos/upload", files=files, data={"title": "Install demo", "consent_confirmed": "true"},
                    headers=expert)
    assert r.status_code == 201
    v = r.json()
    assert v["original_filename"] == "demo.mp4" and v["content_type"] == "video/mp4"
    # no AI configured → explicit 503, no simulated result
    r = client.post(f"/api/v1/extraction/{v['id']}", headers=expert)
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]


def test_capabilities_report_missing_services(client, learner):
    caps = client.get("/api/v1/system/capabilities", headers=learner).json()
    assert caps["ai"] is False
    assert caps["detector"]["available"] is False


def test_extraction_compiler_keeps_gaps_visible():
    """The compiler must not invent validation the model did not propose."""
    from app.ai.extraction import compile_draft
    from app.skillgraph.validator import validate_graph

    step = {"title": "Connect battery to controller", "kind": "action", "description": "", "instructions": ["Connect red to BAT+"],
            "observed_evidence": ["red cable attached to BAT+ (segment 0)"], "inferred_purpose": "power the controller",
            "segment_indices": [0], "required_tools": ["Insulated Screwdriver"], "required_components": ["battery"],
            "safety_critical": True, "hazards": ["reversed_polarity"], "safety_requirements": ["battery first"],
            "visual_criteria": [{"description": "red cable on BAT+"}],
            "measurement": {"present": False, "quantity": "dc_voltage", "unit": "V", "min": None, "max": None,
                            "probe_points": "", "negative_means_reversed_polarity": False},
            "common_mistakes": [], "confidence": 0.9}
    draft = {"title": "Solar install", "summary": "", "difficulty": "beginner", "estimated_duration": 20,
             "required_tools": ["Insulated Screwdriver"], "required_components": ["battery"], "steps": [step], "uncertainties": []}
    segs = [{"t_start": 0.0, "t_end": 5.0, "frames": ["f1.jpg"], "transcript": "red to positive"}]
    g = compile_draft(draft, video_id="vid", job_id="job", segments=segs, model="m")
    s = g["steps"][0]
    assert s["evidence_refs"][0]["t_end"] == 5.0
    assert s["required_tools"] == ["insulated_screwdriver"]
    rep = validate_graph(g)
    assert "polarity_needs_measurement" in {e.code for e in rep.errors}
