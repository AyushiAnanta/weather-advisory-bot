import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

import streamlit as st
import yaml
from app.chat_service import format_comparison


st.set_page_config(page_title="Weather guidance", page_icon="🌦️")

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        api_key = None
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key

if not api_key:
    st.error("Set OPENAI_API_KEY in your .env file or Streamlit secrets to start the chat.")
    st.stop()

from app.chat_service import build_default_service


@st.cache_resource
def get_chat_service():
    return build_default_service()


def _max_chars() -> int:
    try:
        return max(1, int(os.environ.get("CHAT_MAX_CHARS", "300")))
    except ValueError:
        return 300


def _load_examples() -> list[str]:
    examples_path = Path(__file__).parent / "config" / "examples.yaml"
    with examples_path.open(encoding="utf-8") as file:
        examples = yaml.safe_load(file)
    if not isinstance(examples, list) or any(not isinstance(item, str) for item in examples):
        raise ValueError("config/examples.yaml must contain a list of example questions")
    return examples


def _load_panel_messages() -> dict[str, str]:
    messages_path = Path(__file__).parent / "config" / "messages.yaml"
    with messages_path.open(encoding="utf-8") as file:
        messages = yaml.safe_load(file)
    return {
        key: messages[key]
        for key in ("why_clarify", "why_error", "why_rejected")
    }


if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid.uuid4().hex
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("Weather guidance")
with st.container():
    if st.button("New chat"):
        st.session_state.thread_id = uuid.uuid4().hex
        st.session_state.messages = []
        st.rerun()

if not st.session_state.messages:
    st.write("I only look up Indian cities, and advice comes only from written policies (SOPs).")
    st.subheader("Try an example")
    example_columns = st.columns(2)
    selected_example = None
    for index, example in enumerate(_load_examples()):
        if example_columns[index % 2].button(example, key=f"example-{index}", use_container_width=True):
            selected_example = example
else:
    selected_example = None

panel_messages = _load_panel_messages()
latest_assistant_index = max(
    (index for index, item in enumerate(st.session_state.messages) if item["role"] == "assistant"),
    default=-1,
)

for index, item in enumerate(st.session_state.messages):
    with st.chat_message(item["role"]):
        if item["role"] == "user":
            st.write(item["content"])
            continue

        result = item["result"]
        st.write(result["reply_body"])
        with st.expander("Why this answer?", expanded=index == latest_assistant_index):
            sop = result["sop"]
            if sop is not None:
                st.write(f"Policy: {sop['id']} ({sop['severity']}, {sop['category']})")
            elif result["reply_kind"] == "no_match":
                if result.get("no_match_reason") == "no_policy_covers":
                    st.write("No policy covers this question.")
                elif result.get("no_match_reason") == "classifier_inconclusive":
                    st.write("The classification step could not give a verified answer.")
                elif result.get("no_match_reason") == "not_triggered":
                    st.write("Policies checked:")
                    for policy in result["policies_checked"]:
                        st.write(f"{policy['id']} ({policy['severity']})")
                        if policy["comparisons"]:
                            st.text("\n".join(item["display"] for item in policy["comparisons"]))
            elif result["reply_kind"] == "clarify":
                st.write(panel_messages["why_clarify"])
            elif result["reply_kind"] == "error":
                st.write(panel_messages["why_error"])
            elif result["reply_kind"] == "rejected":
                st.write(panel_messages["why_rejected"])
            elif result["reply_kind"] == "fallback":
                st.write(result["failure_reason"] or "Weather lookup unavailable")
            else:
                st.write(result["failure_reason"] or result["reply_kind"])

            evaluated_label = {
                "today": "today",
                "this_evening": "this evening",
                "tomorrow": "tomorrow",
            }.get(result.get("evaluated_for"), "today")
            st.write(f"Evaluated for: {evaluated_label}")

            if result["trigger_values"]:
                st.text("\n".join(format_comparison(item, matched=True) for item in result["trigger_values"]))
            elif result["reply_kind"] != "no_match":
                st.caption("No trigger values.")

            if result["forecast"] is not None:
                forecast = result["forecast"]
                st.write(
                    f"Forecast: {forecast['location']}, as of {forecast['as_of']} ({forecast['timezone']}), for {evaluated_label}"
                )
            if result["also_applies"]:
                st.write("Also applies: " + ", ".join(result["also_applies"]))

user_message = selected_example or st.chat_input(
    "Ask about weather and an activity", max_chars=_max_chars()
)

if user_message:
    st.session_state.messages.append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.write(user_message)
    with st.chat_message("assistant"):
        with st.spinner("Checking the forecast and policies..."):
            response = get_chat_service().ask(st.session_state.thread_id, user_message)
        st.write(response["reply_body"])
    st.session_state.messages.append({"role": "assistant", "result": response})
    st.rerun()
