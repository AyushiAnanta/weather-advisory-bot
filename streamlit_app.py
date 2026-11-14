import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

import streamlit as st
import yaml


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


if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid.uuid4().hex
if "messages" not in st.session_state:
    st.session_state.messages = []

if st.sidebar.button("New chat"):
    st.session_state.thread_id = uuid.uuid4().hex
    st.session_state.messages = []
    st.rerun()

st.title("Weather guidance")
if not st.session_state.messages:
    st.write("I only look up Indian cities, and advice comes only from written policies (SOPs).")
    st.subheader("Try an example")
    example_columns = st.columns(2)
    selected_example = None
    for index, example in enumerate(_load_examples()):
        if example_columns[index % 2].button(example, key=f"example-{index}", use_container_width=True):
            selected_example = example

    if selected_example is not None:
        user_message = selected_example
    else:
        user_message = st.chat_input("Ask about weather and an activity", max_chars=_max_chars())
else:
    user_message = st.chat_input("Ask about weather and an activity", max_chars=_max_chars())

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
                st.write("No policy applies to this question")
            elif result["reply_kind"] == "fallback":
                st.write(result["failure_reason"] or "Weather lookup unavailable")
            elif result["reply_kind"] == "rejected":
                st.write(result["reply_body"])
            else:
                st.write(result["failure_reason"] or result["reply_kind"])

            if result["trigger_values"]:
                st.table(result["trigger_values"])
            else:
                st.caption("No trigger values.")

            if result["forecast"] is not None:
                forecast = result["forecast"]
                st.write(
                    f"Forecast: {forecast['location']}, as of {forecast['as_of']} ({forecast['timezone']})"
                )
            if result["also_applies"]:
                st.write("Also applies: " + ", ".join(result["also_applies"]))

if user_message:
    st.session_state.messages.append({"role": "user", "content": user_message})
    service = st.session_state.get("_chat_service_override") or get_chat_service()
    response = service.ask(st.session_state.thread_id, user_message)
    st.session_state.messages.append({"role": "assistant", "result": response})
    st.rerun()
