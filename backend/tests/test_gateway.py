"""AI gateway: provider selection, Hugging Face chat path, schema checks, retries, transcription config.

The model client is replaced with a fake that records requests and returns scripted
replies, so no network access is needed.
"""

import json
from types import SimpleNamespace

import pytest

from app.ai import gateway
from app.core.config import get_settings

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "confidence"],
    "properties": {
        "status": {"type": "string", "enum": ["observed", "not_visible"]},
        "confidence": {"type": "number"},
    },
}
GOOD = {"status": "observed", "confidence": 0.9}


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.chat_calls, self.responses_calls = [], []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._responses)

    def _next(self):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def _chat(self, **kw):
        self.chat_calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._next()))])

    def _responses(self, **kw):
        self.responses_calls.append(kw)
        return SimpleNamespace(output_text=self._next())


@pytest.fixture
def env(monkeypatch):
    def set_env(**values):
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield set_env
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def hf(env, monkeypatch):
    env(SKILLOS_AI_PROVIDER="hf", HF_TOKEN="hf_test", SKILLOS_HF_MODEL="Qwen/Qwen2.5-VL-72B-Instruct")

    def install(replies):
        fake = FakeClient(replies)
        monkeypatch.setattr(gateway, "_client", lambda: fake)
        return fake

    return install


def call(content=None):
    return gateway.structured(None, org_id=None, purpose="observation", system="sys",
                              content=content or [gateway.text_part("hi")], schema=SCHEMA, name="obs")


def test_defaults_to_openai_and_reports_not_configured():
    assert gateway.provider() == "openai"
    assert not gateway.ai_available()
    with pytest.raises(gateway.AINotConfigured, match="OPENAI_API_KEY"):
        call()


def test_hf_not_configured_names_hf_settings(env):
    env(SKILLOS_AI_PROVIDER="hf")
    assert not gateway.ai_available()
    with pytest.raises(gateway.AINotConfigured, match="HF_TOKEN"):
        call()


def test_hf_configuration(hf):
    hf([])
    s = get_settings()
    assert gateway.ai_available()
    assert gateway.model_name() == "Qwen/Qwen2.5-VL-72B-Instruct"
    assert s.hf_base_url == "https://router.huggingface.co/v1"


def test_hf_sends_chat_request_with_schema_and_converted_parts(hf, tmp_path):
    fake = hf([json.dumps(GOOD)])
    img = tmp_path / "frame.jpg"
    img.write_bytes(b"\xff\xd8fake")
    assert call([gateway.text_part("look"), gateway.image_part(img)]) == GOOD

    (req,) = fake.chat_calls
    assert req["model"] == "Qwen/Qwen2.5-VL-72B-Instruct"
    assert req["response_format"]["type"] == "json_schema"
    assert req["response_format"]["json_schema"]["schema"] == SCHEMA
    system, user = req["messages"]
    assert system == {"role": "system", "content": "sys"}
    text, image = user["content"]
    assert text == {"type": "text", "text": "look"}
    assert image["type"] == "image_url" and image["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_hf_accepts_json_in_code_fence(hf):
    hf(["```json\n" + json.dumps(GOOD) + "\n```"])
    assert call() == GOOD


def test_hf_retries_once_with_reason_then_succeeds(hf):
    fake = hf([json.dumps({"status": "maybe", "confidence": 0.5}), json.dumps(GOOD)])
    assert call() == GOOD
    assert len(fake.chat_calls) == 2
    retry_msgs = fake.chat_calls[1]["messages"]
    assert retry_msgs[-2]["role"] == "assistant"
    assert "status" in retry_msgs[-1]["content"] and "rejected" in retry_msgs[-1]["content"]


def test_hf_gives_up_after_second_bad_reply(hf):
    fake = hf(["not json", json.dumps({"status": "observed"})])
    with pytest.raises(gateway.AIInvalidOutput, match="confidence"):
        call()
    assert len(fake.chat_calls) == 2


def test_hf_network_error_is_ai_error_without_retry(hf):
    fake = hf([RuntimeError("boom")])
    with pytest.raises(gateway.AIError, match="RuntimeError"):
        call()
    assert len(fake.chat_calls) == 1


def test_openai_reply_is_schema_checked_without_retry(env, monkeypatch):
    env(OPENAI_API_KEY="sk-test", OPENAI_MODEL="some-model")
    fake = FakeClient([json.dumps({"status": "observed", "confidence": 1, "extra": True})])
    monkeypatch.setattr(gateway, "_client", lambda: fake)
    with pytest.raises(gateway.AIInvalidOutput):
        call()
    assert len(fake.responses_calls) == 1 and not fake.chat_calls


def test_hf_text_uses_chat_completions(hf):
    fake = hf(["an explanation"])
    out = gateway.text(None, org_id=None, purpose="instruction", system="sys", content=[gateway.text_part("why?")])
    assert out == "an explanation"
    assert fake.chat_calls[0]["messages"][1]["content"] == [{"type": "text", "text": "why?"}]


def test_transcription_backend_selection(env, tmp_path):
    assert gateway.transcription_backend() is None
    with pytest.raises(gateway.AINotConfigured, match="transcription"):
        gateway.transcribe(None, None, tmp_path / "a.mp3")
    env(OPENAI_API_KEY="sk-test", OPENAI_TRANSCRIPTION_MODEL="whisper-1")
    assert gateway.transcription_backend() == "openai"
    env(SKILLOS_WHISPER_MODEL="small")
    assert gateway.transcription_backend() == "whisper"


def test_local_whisper_transcription(env, monkeypatch, tmp_path):
    env(SKILLOS_WHISPER_MODEL="small")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        with pytest.raises(gateway.AINotConfigured, match="faster-whisper"):
            gateway.transcribe(None, None, tmp_path / "a.mp3")
        import sys
        monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace())

    class FakeWhisper:
        def transcribe(self, path):
            segs = [SimpleNamespace(start=0.0, end=1.5, text=" Check polarity. "),
                    SimpleNamespace(start=1.5, end=3.0, text=" Connect the fuse.")]
            return iter(segs), None

    monkeypatch.setattr(gateway, "_whisper", lambda size: FakeWhisper())
    out = gateway.transcribe(None, None, tmp_path / "a.mp3")
    assert out["text"] == "Check polarity. Connect the fuse."
    assert out["segments"][1] == {"start": 1.5, "end": 3.0, "text": "Connect the fuse."}
