from datetime import datetime, timedelta


def resolve_eval_now(real_now: datetime, time_ref: str | None) -> datetime:
    if time_ref == "this_evening":
        return real_now.replace(hour=17, minute=0, second=0, microsecond=0)
    if time_ref == "tomorrow":
        return (real_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return real_now
