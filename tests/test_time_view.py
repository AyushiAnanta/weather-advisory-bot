from datetime import datetime

from app.matcher import evaluate_condition
from app.sop_loader import CurrentCondition, DailyCondition, HourlyCondition, Window
from app.time_view import resolve_eval_now, window_is_past


def hourly_test_condition(window):
    return HourlyCondition(
        source="hourly",
        field="temperature_2m",
        agg="min",
        window=window,
        op="<=",
        value=10,
    )


def test_window_is_past_for_today_hourly_window():
    condition = hourly_test_condition(Window(day="today", start_hour=5, end_hour=8))
    assert window_is_past(condition, datetime.fromisoformat("2026-11-13T12:45")) is True


def test_window_is_not_past_at_end_hour_or_before_window():
    condition = hourly_test_condition(Window(day="today", start_hour=5, end_hour=8))
    assert window_is_past(condition, datetime.fromisoformat("2026-11-13T08:30")) is False
    assert window_is_past(condition, datetime.fromisoformat("2026-11-13T04:00")) is False


def test_window_is_not_past_when_missing_or_tomorrow():
    no_window = hourly_test_condition(None)
    tomorrow = hourly_test_condition(Window(day="tomorrow", start_hour=5, end_hour=8))
    now = datetime.fromisoformat("2026-11-13T12:45")
    assert window_is_past(no_window, now) is False
    assert window_is_past(tomorrow, now) is False


def test_window_is_not_past_for_current_or_daily_condition():
    current = CurrentCondition(source="current", field="temperature_2m", op=">", value=10)
    daily = DailyCondition(source="daily", field="precipitation_sum", day="today", op=">", value=10)
    now = datetime.fromisoformat("2026-11-13T12:45")
    assert window_is_past(current, now) is False
    assert window_is_past(daily, now) is False


def test_past_window_consistency_with_hourly_evaluator():
    condition = hourly_test_condition(Window(day="today", start_hour=5, end_hour=8))
    now = datetime.fromisoformat("2026-11-13T12:45")
    facts = {
        "hourly": {
            "time": [f"2026-11-13T{hour:02}:00" for hour in range(5, 9)],
            "temperature_2m": [6, 7, 8, 9],
        }
    }

    assert window_is_past(condition, now) is True
    assert evaluate_condition(condition, facts, now) == (False, None)


def test_this_evening_moves_time_to_seventeen_on_same_date():
    real_now = datetime.fromisoformat("2026-11-13T10:24:35")

    assert resolve_eval_now(real_now, "this_evening") == datetime.fromisoformat("2026-11-13T17:00:00")


def test_this_evening_returns_later_of_real_time_and_seventeen():
    cases = [
        ("2026-11-13T10:00:00", "2026-11-13T17:00:00"),
        ("2026-11-13T17:00:00", "2026-11-13T17:00:00"),
        ("2026-11-13T20:30:00", "2026-11-13T20:30:00"),
    ]

    for real_text, expected_text in cases:
        assert resolve_eval_now(datetime.fromisoformat(real_text), "this_evening") == datetime.fromisoformat(expected_text)


def test_tomorrow_moves_to_midnight_on_next_date():
    real_now = datetime.fromisoformat("2026-11-13T22:24:35")

    assert resolve_eval_now(real_now, "tomorrow") == datetime.fromisoformat("2026-11-14T00:00:00")


def test_none_time_ref_returns_real_now_unchanged():
    real_now = datetime.fromisoformat("2026-11-13T10:24:35")

    assert resolve_eval_now(real_now, None) is real_now


def test_unrecognized_time_ref_returns_real_now_unchanged():
    real_now = datetime.fromisoformat("2026-11-13T10:24:35")

    assert resolve_eval_now(real_now, "sometime later") is real_now
