from app.assessment.scoring import profile_level


def h(mode, level, day):
    return {"mode": mode, "session_level": level, "created_at": f"2026-11-{day:02d}T10:00:00+00:00"}


def test_repeated_guided_completion_is_not_expertise():
    assert profile_level([h("guided", "COMPETENT", d) for d in range(1, 10)])[0] == "COMPETENT"


def test_expert_needs_three_proficient_assessments_on_two_days():
    same_day = [h("assessment", "PROFICIENT", 1)] * 3
    assert profile_level(same_day)[0] == "PROFICIENT"
    spread = [h("assessment", "PROFICIENT", d) for d in (1, 1, 2)]
    assert profile_level(spread)[0] == "EXPERT"


def test_latest_assessment_regression_drops_proficient():
    hist = [h("assessment", "PROFICIENT", 1), h("assessment", "DEVELOPING", 3)]
    level, ev = profile_level(hist)
    assert level == "COMPETENT"
    assert ev["independent_completions"] == 2


def test_no_attempts_is_novice():
    assert profile_level([])[0] == "NOVICE"
