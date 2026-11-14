import json
import os
from dataclasses import asdict
from typing import Any

from app.graph import ComposeInput


MODEL = "gpt-4o-mini"


def _client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _response_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def _response_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise ValueError("OpenAI response did not contain message content") from exc
    if not isinstance(content, str):
        raise ValueError("OpenAI response content was not text")
    return content


def real_understand(
    user_message: str,
    allowed_tags: list[str],
    session_summary: dict,
) -> dict:
    activity_values = list(dict.fromkeys(allowed_tags))
    schema = {
        "type": "object",
        "properties": {
            "city": {"type": ["string", "null"]},
            "activity_tag": {
                "type": ["string", "null"],
                "enum": [*activity_values, None],
            },
            "time_ref": {
                "type": ["string", "null"],
                "enum": ["this_evening", "tomorrow", None],
            },
            "is_followup": {"type": "boolean"},
        },
        "required": ["city", "activity_tag", "time_ref", "is_followup"],
        "additionalProperties": False,
    }
    system_prompt = (
        "Extract only what is stated in the user message. Never invent a city or activity. "
        "Use session_summary only to understand follow-up phrasing such as 'what about tomorrow instead'; "
        "never use it to invent a new city or activity on your own initiative. Return null when a city, "
        "activity, or time reference is not stated. An activity_tag must be one of the allowed tags. "
        "Set activity_tag only if the user's activity clearly is one of the allowed tags. If the activity "
        "is not on the list, or you would have to stretch a tag to fit it, return null. Never choose the "
        "nearest tag. A kite, cricket, fishing or any other activity not on the list is null. "
        'Set time_ref to "tomorrow" ONLY if the user\'s message explicitly refers to tomorrow or the next day. '
        'Set time_ref to "this_evening" ONLY if it explicitly refers to this evening or tonight. '
        'For "today", "now", "right now", or no time words at all, time_ref must be null. '
        "Guessing a time is wrong; null is the default."
    )
    user_content = json.dumps(
        {
            "user_message": user_message,
            "allowed_tags": allowed_tags,
            "session_summary": session_summary,
        },
        ensure_ascii=False,
    )
    response = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=_response_format("question_extraction", schema),
        temperature=0,
    )
    try:
        result = json.loads(_response_text(response))
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI returned malformed JSON for question extraction") from exc
    expected_keys = {"city", "activity_tag", "time_ref", "is_followup"}
    if not isinstance(result, dict) or set(result) != expected_keys:
        raise ValueError("OpenAI extraction did not match the required schema")
    if result["city"] is not None and not isinstance(result["city"], str):
        raise ValueError("city must be a string or null")
    if result["activity_tag"] is not None and result["activity_tag"] not in activity_values:
        raise ValueError("activity_tag is not in allowed_tags")
    if result["time_ref"] is not None and (
        not isinstance(result["time_ref"], str)
        or result["time_ref"] not in {"this_evening", "tomorrow"}
    ):
        raise ValueError("time_ref is not supported")
    if type(result["is_followup"]) is not bool:
        raise ValueError("is_followup must be a boolean")
    return result


def real_compose(compose_input: ComposeInput) -> str:
    evaluated_day = {
        "today": "today",
        "this_evening": "this evening",
        "tomorrow": "tomorrow",
    }.get(compose_input.evaluated_for, "today")
    system_prompt = (
        "Write 2-4 sentences based only on the given guidance, trigger values, and location. "
        "Never invent numbers. Never cite an SOP id that was not already given. Never claim "
        "certainty beyond what the facts support. Do not add facts, locations, or thresholds. "
        "All values and the advice are about evaluated_for only. Do not mention any other day. "
        "Do not predict, extend or compare other days. Do not say 'remain', 'continue', 'similar', "
        "'at least' or 'expected to stay'. "
        f"Say the value is the forecast value for {evaluated_day}. "
        "When stating any numeric value from the trigger values, copy the number exactly as given, "
        "character for character (e.g. if given 43.9, write 43.9 — never round to 44, never round "
        "to 40, never drop the decimal). Do not simplify, round, or approximate any number. If a "
        "number has a decimal, include it exactly."
    )
    user_content = json.dumps(asdict(compose_input), ensure_ascii=False)
    response = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
    )
    return _response_text(response)


def real_classify(classify_input: dict) -> str:
    rubric = classify_input.get("rubric", "")
    system_prompt = (
        "Use this SOP rubric to classify the supplied weather facts:\n"
        f"{rubric}\n"
        "Respond with exactly one word: suitable, marginal, or unsuitable. Return nothing else: "
        "no punctuation and no explanation."
    )
    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": ["suitable", "marginal", "unsuitable"]}
        },
        "required": ["label"],
        "additionalProperties": False,
    }
    response = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(classify_input, ensure_ascii=False)},
        ],
        response_format=_response_format("classifier_outcome", schema),
        temperature=0,
    )
    try:
        parsed = json.loads(_response_text(response))
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI returned malformed JSON for classifier outcome") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"label"} or not isinstance(parsed["label"], str):
        raise ValueError("OpenAI classifier response did not match the required schema")
    return parsed["label"].strip().lower()
