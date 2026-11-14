from app.messages import MESSAGE_KEYS, load_messages


def test_messages_config_has_each_required_non_empty_value():
    messages = load_messages()

    assert set(messages) == MESSAGE_KEYS
    assert all(isinstance(value, str) and value.strip() for value in messages.values())
