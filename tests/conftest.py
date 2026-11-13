import requests
import pytest


@pytest.fixture(autouse=True)
def prevent_network_calls(monkeypatch):
    def fail_on_network(*args, **kwargs):
        raise AssertionError("network call in unit test")

    monkeypatch.setattr(requests, "get", fail_on_network)
