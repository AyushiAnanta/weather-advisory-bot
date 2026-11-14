from datetime import datetime

from app.time_view import resolve_eval_now


def test_this_evening_moves_time_to_seventeen_on_same_date():
    real_now = datetime.fromisoformat("2026-11-13T10:24:35")

    assert resolve_eval_now(real_now, "this_evening") == datetime.fromisoformat("2026-11-13T17:00:00")


def test_tomorrow_moves_to_midnight_on_next_date():
    real_now = datetime.fromisoformat("2026-11-13T22:24:35")

    assert resolve_eval_now(real_now, "tomorrow") == datetime.fromisoformat("2026-11-14T00:00:00")


def test_none_time_ref_returns_real_now_unchanged():
    real_now = datetime.fromisoformat("2026-11-13T10:24:35")

    assert resolve_eval_now(real_now, None) is real_now


def test_unrecognized_time_ref_returns_real_now_unchanged():
    real_now = datetime.fromisoformat("2026-11-13T10:24:35")

    assert resolve_eval_now(real_now, "sometime later") is real_now
