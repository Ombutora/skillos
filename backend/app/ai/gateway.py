"""Single entry point for OpenAI calls.

- Uses the Responses API with strict JSON-schema structured outputs.
- Every call is logged to ai_call_logs (status, latency, sizes; no raw images).
- When no key/model is configured it raises AINotConfigured. Callers surface
  that to the user; nothing is ever simulated.
"""

import base64
import json
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AICallLog


class AIError(Exception):
    status = 502


class AINotConfigured(AIError):
    status = 503

    def __init__(self):
        super().__init__("AI is not configured: set OPENAI_API_KEY and OPENAI_MODEL (see README → Configuration).")


class AIInvalidOutput(AIError):
    pass


def ai_available() -> bool:
    s = get_settings()
    return bool(s.openai_api_key and s.openai_model)


def _client():
    from openai import OpenAI

    return OpenAI(api_key=get_settings().openai_api_key, timeout=90, max_retries=2)


def image_part(path: str | Path, detail: str = "auto") -> dict:
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode()
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}", "detail": detail}


def text_part(text: str) -> dict:
    return {"type": "input_text", "text": text}


def structured(db: Session | None, *, org_id: str | None, purpose: str, system: str, content: list[dict],
               schema: dict, name: str) -> dict:
    s = get_settings()
    if not ai_available():
        _log(db, org_id, purpose, None, "not_configured", 0, {}, {}, None)
        raise AINotConfigured()
    started = time.monotonic()
    req_summary = {"name": name, "parts": [p["type"] for p in content],
                   "text_chars": sum(len(p.get("text", "")) for p in content)}
    try:
        resp = _client().responses.create(
            model=s.openai_model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        )
        raw = resp.output_text
    except Exception as e:  # network, auth, rate limit, refusal
        _log(db, org_id, purpose, s.openai_model, "error", _ms(started), req_summary, {}, str(e)[:2000])
        raise AIError(f"AI request failed: {e.__class__.__name__}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _log(db, org_id, purpose, s.openai_model, "invalid_output", _ms(started), req_summary, {"chars": len(raw or "")}, str(e))
        raise AIInvalidOutput("AI returned output that is not valid JSON") from e
    _log(db, org_id, purpose, s.openai_model, "ok", _ms(started), req_summary, {"keys": sorted(data)}, None)
    return data


def text(db: Session | None, *, org_id: str | None, purpose: str, system: str, content: list[dict]) -> str:
    s = get_settings()
    if not ai_available():
        _log(db, org_id, purpose, None, "not_configured", 0, {}, {}, None)
        raise AINotConfigured()
    started = time.monotonic()
    try:
        resp = _client().responses.create(model=s.openai_model, input=[{"role": "system", "content": system},
                                                                        {"role": "user", "content": content}])
    except Exception as e:
        _log(db, org_id, purpose, s.openai_model, "error", _ms(started), {}, {}, str(e)[:2000])
        raise AIError(f"AI request failed: {e.__class__.__name__}") from e
    _log(db, org_id, purpose, s.openai_model, "ok", _ms(started), {}, {"chars": len(resp.output_text)}, None)
    return resp.output_text


def transcribe(db: Session | None, org_id: str | None, audio_path: Path) -> dict:
    """Returns {"text": str, "segments": [{"start","end","text"}]}; segments may be empty."""
    s = get_settings()
    if not s.openai_api_key or not s.openai_transcription_model:
        _log(db, org_id, "transcription", None, "not_configured", 0, {}, {}, None)
        raise AINotConfigured()
    started = time.monotonic()
    try:
        with open(audio_path, "rb") as f:
            kwargs = {"model": s.openai_transcription_model, "file": f}
            if "whisper" in s.openai_transcription_model:
                kwargs |= {"response_format": "verbose_json", "timestamp_granularities": ["segment"]}
            r = _client().audio.transcriptions.create(**kwargs)
    except Exception as e:
        _log(db, org_id, "transcription", s.openai_transcription_model, "error", _ms(started), {}, {}, str(e)[:2000])
        raise AIError(f"transcription failed: {e.__class__.__name__}") from e
    segs = [{"start": g.start, "end": g.end, "text": g.text} for g in (getattr(r, "segments", None) or [])]
    _log(db, org_id, "transcription", s.openai_transcription_model, "ok", _ms(started), {}, {"segments": len(segs)}, None)
    return {"text": r.text, "segments": segs}


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _log(db, org_id, purpose, model, status, latency, req, resp, error):
    if db is None:
        return
    db.add(AICallLog(org_id=org_id, purpose=purpose, model=model, status=status, latency_ms=latency,
                     request_summary=req, response_summary=resp, error=error))
    db.flush()
