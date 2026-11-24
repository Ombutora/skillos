"""Single entry point for model calls.

Providers (SKILLOS_AI_PROVIDER):
- "openai": OpenAI Responses API with strict JSON-schema structured outputs.
- "hf": Hugging Face Inference Providers through its OpenAI-compatible router
  (chat completions). Open models do not always honour the schema, so a reply
  that fails validation gets one corrective retry.

For both providers every structured reply is validated against its JSON schema
before it is returned, so callers can rely on enums and required keys.

Transcription is configured separately: local Whisper (faster-whisper) when
SKILLOS_WHISPER_MODEL is set, otherwise OpenAI when its transcription model is set.

Every call is logged to ai_call_logs (status, latency, sizes; no raw images).
When nothing is configured it raises AINotConfigured. Callers surface that to
the user; nothing is ever simulated.
"""

import base64
import json
import re
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AICallLog


class AIError(Exception):
    status = 502


class AINotConfigured(AIError):
    status = 503

    def __init__(self, message: str | None = None):
        super().__init__(message or _not_configured_message())


class AIInvalidOutput(AIError):
    pass


def _not_configured_message() -> str:
    if provider() == "hf":
        return "AI is not configured: set HF_TOKEN and SKILLOS_HF_MODEL (see README → Configuration)."
    return "AI is not configured: set OPENAI_API_KEY and OPENAI_MODEL (see README → Configuration)."


def provider() -> str:
    return get_settings().ai_provider


def model_name() -> str | None:
    s = get_settings()
    return s.hf_model if s.ai_provider == "hf" else s.openai_model


def ai_available() -> bool:
    s = get_settings()
    if s.ai_provider == "hf":
        return bool(s.hf_token and s.hf_model)
    return bool(s.openai_api_key and s.openai_model)


def transcription_backend() -> str | None:
    """"whisper" (local), "openai", or None when transcription is not configured."""
    s = get_settings()
    if s.whisper_model:
        return "whisper"
    if s.openai_api_key and s.openai_transcription_model:
        return "openai"
    return None


def _client():
    from openai import OpenAI

    s = get_settings()
    if s.ai_provider == "hf":
        return OpenAI(api_key=s.hf_token, base_url=s.hf_base_url, timeout=120, max_retries=2)
    return OpenAI(api_key=s.openai_api_key, timeout=90, max_retries=2)


# Content parts are built in Responses-API shape; _chat_content converts them for chat completions.
def image_part(path: str | Path, detail: str = "auto") -> dict:
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode()
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}", "detail": detail}


def text_part(text: str) -> dict:
    return {"type": "input_text", "text": text}


def _chat_content(content: list[dict]) -> list[dict]:
    out = []
    for p in content:
        if p["type"] == "input_text":
            out.append({"type": "text", "text": p["text"]})
        elif p["type"] == "input_image":
            out.append({"type": "image_url", "image_url": {"url": p["image_url"]}})
        else:
            raise ValueError(f"unsupported content part: {p['type']}")
    return out


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _parse(raw: str | None, schema: dict) -> tuple[dict | None, str | None]:
    """Returns (data, None) when raw is JSON matching schema, else (None, reason)."""
    from jsonschema import Draft202012Validator

    text = raw or ""
    m = _FENCE.match(text)  # open models often wrap JSON in a code fence
    if m:
        text = m.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"not valid JSON ({e.msg})"
    if not isinstance(data, dict):
        return None, "top-level value is not a JSON object"
    err = next(iter(Draft202012Validator(schema).iter_errors(data)), None)
    if err is not None:
        where = "/".join(str(x) for x in err.absolute_path) or "(root)"
        return None, f"schema mismatch at {where}: {err.message[:300]}"
    return data, None


def structured(db: Session | None, *, org_id: str | None, purpose: str, system: str, content: list[dict],
               schema: dict, name: str) -> dict:
    s = get_settings()
    model = model_name()
    if not ai_available():
        _log(db, org_id, purpose, None, "not_configured", 0, {}, {}, None)
        raise AINotConfigured()
    started = time.monotonic()
    req_summary = {"provider": s.ai_provider, "name": name, "parts": [p["type"] for p in content],
                   "text_chars": sum(len(p.get("text", "")) for p in content)}
    hf = s.ai_provider == "hf"
    messages = None
    if hf:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": _chat_content(content)}]
    attempts = 2 if hf else 1
    reason = None
    raw = None
    for attempt in range(1, attempts + 1):
        try:
            if hf:
                resp = _client().chat.completions.create(
                    model=model, messages=messages,
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": name, "schema": schema, "strict": True}},
                )
                raw = resp.choices[0].message.content
            else:
                resp = _client().responses.create(
                    model=model,
                    input=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                    text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
                )
                raw = resp.output_text
        except Exception as e:  # network, auth, rate limit, refusal
            _log(db, org_id, purpose, model, "error", _ms(started), req_summary | {"attempts": attempt}, {},
                 str(e)[:2000])
            raise AIError(f"AI request failed: {e.__class__.__name__}") from e
        data, reason = _parse(raw, schema)
        if data is not None:
            _log(db, org_id, purpose, model, "ok", _ms(started), req_summary | {"attempts": attempt},
                 {"keys": sorted(data)}, None)
            return data
        if hf and attempt < attempts:
            messages = messages + [
                {"role": "assistant", "content": raw or ""},
                {"role": "user", "content": f"Your reply was rejected: {reason}. "
                                            "Reply again with only a JSON object that matches the schema exactly."},
            ]
    _log(db, org_id, purpose, model, "invalid_output", _ms(started), req_summary | {"attempts": attempts},
         {"chars": len(raw or "")}, reason)
    raise AIInvalidOutput(f"AI returned output that does not match the expected schema: {reason}")


def text(db: Session | None, *, org_id: str | None, purpose: str, system: str, content: list[dict]) -> str:
    s = get_settings()
    model = model_name()
    if not ai_available():
        _log(db, org_id, purpose, None, "not_configured", 0, {}, {}, None)
        raise AINotConfigured()
    started = time.monotonic()
    try:
        if s.ai_provider == "hf":
            resp = _client().chat.completions.create(
                model=model, messages=[{"role": "system", "content": system},
                                       {"role": "user", "content": _chat_content(content)}])
            out = resp.choices[0].message.content or ""
        else:
            resp = _client().responses.create(model=model, input=[{"role": "system", "content": system},
                                                                   {"role": "user", "content": content}])
            out = resp.output_text
    except Exception as e:
        _log(db, org_id, purpose, model, "error", _ms(started), {"provider": s.ai_provider}, {}, str(e)[:2000])
        raise AIError(f"AI request failed: {e.__class__.__name__}") from e
    _log(db, org_id, purpose, model, "ok", _ms(started), {"provider": s.ai_provider}, {"chars": len(out)}, None)
    return out


@lru_cache
def _whisper(size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(size, device="auto", compute_type="int8")


def transcribe(db: Session | None, org_id: str | None, audio_path: Path) -> dict:
    """Returns {"text": str, "segments": [{"start","end","text"}]}; segments may be empty."""
    s = get_settings()
    backend = transcription_backend()
    if backend is None:
        _log(db, org_id, "transcription", None, "not_configured", 0, {}, {}, None)
        raise AINotConfigured("transcription is not configured: set SKILLOS_WHISPER_MODEL or "
                              "OPENAI_API_KEY and OPENAI_TRANSCRIPTION_MODEL")
    started = time.monotonic()
    if backend == "whisper":
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            _log(db, org_id, "transcription", f"whisper:{s.whisper_model}", "not_configured", 0, {}, {}, None)
            raise AINotConfigured("SKILLOS_WHISPER_MODEL is set but faster-whisper is not installed "
                                  "(pip install faster-whisper)") from None
        model = f"whisper:{s.whisper_model}"
        try:
            segments, _info = _whisper(s.whisper_model).transcribe(str(audio_path))
            segs = [{"start": g.start, "end": g.end, "text": g.text.strip()} for g in segments]
        except Exception as e:
            _log(db, org_id, "transcription", model, "error", _ms(started), {}, {}, str(e)[:2000])
            raise AIError(f"transcription failed: {e.__class__.__name__}") from e
        _log(db, org_id, "transcription", model, "ok", _ms(started), {}, {"segments": len(segs)}, None)
        return {"text": " ".join(g["text"] for g in segs), "segments": segs}

    try:
        with open(audio_path, "rb") as f:
            kwargs = {"model": s.openai_transcription_model, "file": f}
            if "whisper" in s.openai_transcription_model:
                kwargs |= {"response_format": "verbose_json", "timestamp_granularities": ["segment"]}
            r = _client_openai().audio.transcriptions.create(**kwargs)
    except Exception as e:
        _log(db, org_id, "transcription", s.openai_transcription_model, "error", _ms(started), {}, {}, str(e)[:2000])
        raise AIError(f"transcription failed: {e.__class__.__name__}") from e
    segs = [{"start": g.start, "end": g.end, "text": g.text} for g in (getattr(r, "segments", None) or [])]
    _log(db, org_id, "transcription", s.openai_transcription_model, "ok", _ms(started), {}, {"segments": len(segs)}, None)
    return {"text": r.text, "segments": segs}


def _client_openai():
    """OpenAI client regardless of the chat provider (used for OpenAI transcription)."""
    from openai import OpenAI

    return OpenAI(api_key=get_settings().openai_api_key, timeout=90, max_retries=2)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _log(db, org_id, purpose, model, status, latency, req, resp, error):
    if db is None:
        return
    db.add(AICallLog(org_id=org_id, purpose=purpose, model=model, status=status, latency_ms=latency,
                     request_summary=req, response_summary=resp, error=error))
    db.flush()
