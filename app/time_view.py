from datetime import datetime, timedelta


def resolve_eval_now(real_now: datetime, time_ref: str | None) -> datetime:
    if time_ref == "this_evening":
        evening = real_now.replace(hour=17, minute=0, second=0, microsecond=0)
        return max(real_now, evening)
    if time_ref == "tomorrow":
        return (real_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return real_now


def facts_for_time_ref(facts: dict, time_ref: str | None) -> dict:
    if time_ref != "tomorrow":
        return facts

    eval_now = resolve_eval_now(datetime.fromisoformat(facts["now"]), time_ref)
    shifted = dict(facts)
    shifted["now"] = eval_now.isoformat()

    daily = facts.get("daily")
    if isinstance(daily, dict):
        shifted_daily = {
            key: value[1:] if isinstance(value, list) else value
            for key, value in daily.items()
        }
        shifted["daily"] = shifted_daily
    return shifted
