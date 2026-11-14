import json
import sys
from dataclasses import fields as dataclass_fields
from types import SimpleNamespace

import pytest

from app import llm
from app.graph import ComposeInput


def install_fake_openai(monkeypatch, content=None, error=None):
    requests = []
    keys = []

    class FakeOpenAI:
        def __init__(self, api_key):
            keys.append(api_key)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            requests.append(kwargs)
            if error is not None:
                raise error
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return requests, keys


def compose_input():
    return ComposeInput(
        primary_guidance="Use the reported facts.",
        primary_sop_id="wind-cycling-001",
        primary_severity="high",
        also_applies=[],
        trigger_values=[{"field": "wind_gusts_10m", "agg": "max", "actual": 45}],
        location_display="Sample Place, Sample Region, India",
        evaluated_for="today",
        previous_decision=None,
    )


def test_real_understand_decodes_well_formed_extraction(monkeypatch):
    requests, keys = install_fake_openai(
        monkeypatch,
        json.dumps(
            {"city": "Sample Place", "activity_tag": "cycling", "time_ref": "tomorrow", "is_followup": True}
        ),
    )

    result = llm.real_understand("What about tomorrow?", ["cycling", "picnic"], {"last_location_display": None})

    assert result == {
        "city": "Sample Place",
        "activity_tag": "cycling",
        "time_ref": "tomorrow",
        "is_followup": True,
    }
    assert keys == ["test-key"]
    assert requests[0]["model"] == llm.MODEL
    system_prompt = requests[0]["messages"][0]["content"]
    assert "never invent a city or activity" in system_prompt.lower()
    assert "session_summary only to understand follow-up phrasing" in system_prompt


def test_activity_tag_is_enum_constrained_to_allowed_tags(monkeypatch):
    requests, _ = install_fake_openai(
        monkeypatch,
        json.dumps(
            {"city": "Sample Place", "activity_tag": "running", "time_ref": None, "is_followup": False}
        ),
    )

    with pytest.raises(ValueError, match="activity_tag is not in allowed_tags"):
        llm.real_understand("Check outside play", ["cycling", "picnic"], {})

    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["activity_tag"]["enum"] == ["cycling", "picnic", None]
    assert schema["properties"]["activity_tag"]["type"] == ["string", "null"]


def test_malformed_understand_response_raises_value_error(monkeypatch):
    install_fake_openai(monkeypatch, "not-json")

    with pytest.raises(ValueError, match="malformed JSON"):
        llm.real_understand("Check weather", ["cycling"], {})


def test_understand_prompt_is_explicit_and_request_uses_zero_temperature(monkeypatch):
    requests, _ = install_fake_openai(
        monkeypatch,
        json.dumps({"city": None, "activity_tag": None, "time_ref": None, "is_followup": False}),
    )

    llm.real_understand("What should I do?", ["cycling"], {})

    assert requests[0]["temperature"] == 0
    prompt = requests[0]["messages"][0]["content"].lower()
    assert "null" in prompt
    assert "explicitly" in prompt
    assert (
        "set activity_tag only if the user's activity clearly is one of the allowed tags. if the activity "
        "is not on the list, or you would have to stretch a tag to fit it, return null. never choose the "
        "nearest tag. a kite, cricket, fishing or any other activity not on the list is null."
    ) in prompt


def test_understand_accepts_null_activity_tag(monkeypatch):
    requests, _ = install_fake_openai(
        monkeypatch,
        json.dumps({"city": "Mumbai", "activity_tag": None, "time_ref": None, "is_followup": False}),
    )

    result = llm.real_understand("Is it a good day to fly a kite in Mumbai?", ["cycling", "picnic"], {})

    assert result["activity_tag"] is None
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["activity_tag"]["type"] == ["string", "null"]
    assert schema["properties"]["activity_tag"]["enum"] == ["cycling", "picnic", None]


def test_understand_returns_model_time_ref_without_second_guessing(monkeypatch):
    expected = {
        "city": "Sample Place",
        "activity_tag": "cycling",
        "time_ref": "tomorrow",
        "is_followup": False,
    }
    install_fake_openai(monkeypatch, json.dumps(expected))

    result = llm.real_understand("Is it safe to cycle today?", ["cycling"], {})

    assert result == expected


@pytest.mark.parametrize("label", ["suitable", "marginal", "unsuitable"])
def test_real_classify_decodes_each_allowed_label(monkeypatch, label):
    requests, _ = install_fake_openai(monkeypatch, json.dumps({"label": label}))

    assert llm.real_classify({"rubric": "Rubric text.", "facts": []}) == label
    assert requests[0]["temperature"] == 0
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["label"]["enum"] == ["suitable", "marginal", "unsuitable"]
    assert "Rubric text." in requests[0]["messages"][0]["content"]


def test_real_classify_normalizes_whitespace_and_capitalization(monkeypatch):
    install_fake_openai(monkeypatch, json.dumps({"label": "  SUITABLE \n"}))

    assert llm.real_classify({"rubric": "Rubric text.", "facts": []}) == "suitable"


def test_real_compose_returns_text_without_user_message_field(monkeypatch):
    requests, _ = install_fake_openai(monkeypatch, "Use care based on the forecast.")

    result = llm.real_compose(compose_input())

    fields = {field.name for field in dataclass_fields(ComposeInput)}
    assert result == "Use care based on the forecast."
    assert requests[0]["temperature"] == 0
    assert not any("message" in name or "history" in name for name in fields)
    system_prompt = requests[0]["messages"][0]["content"]
    assert "Write 2-4 sentences" in system_prompt
    assert "never invent numbers" in system_prompt.lower()
    assert "forecast value" in system_prompt
    assert "All values and the advice are about evaluated_for only." in system_prompt
    assert "Do not mention any other day." in system_prompt
    assert "Do not predict, extend or compare other days." in system_prompt
    assert "Do not say 'remain', 'continue', 'similar', 'at least' or 'expected to stay'." in system_prompt
    assert "Say the value is the forecast value for today." in system_prompt
    assert '"evaluated_for": "today"' in requests[0]["messages"][1]["content"]
    assert "Sample Place" in requests[0]["messages"][1]["content"]


@pytest.mark.parametrize("function_name", ["understand", "compose", "classify"])
@pytest.mark.parametrize("error", [TimeoutError("simulated timeout"), PermissionError("simulated auth error")])
def test_api_exceptions_propagate_from_real_functions(monkeypatch, function_name, error):
    install_fake_openai(monkeypatch, error=error)
    calls = {
        "understand": lambda: llm.real_understand("Check weather", ["cycling"], {}),
        "compose": lambda: llm.real_compose(compose_input()),
        "classify": lambda: llm.real_classify({"rubric": "Rubric.", "facts": []}),
    }

    with pytest.raises(type(error)) as exc:
        calls[function_name]()
    assert exc.value is error


def test_api_key_is_checked_at_call_time(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        llm.real_understand("Check weather", ["cycling"], {})
