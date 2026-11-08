"""Input checks for the API. Errors list the allowed values so a model that passes a
wrong filter is told how to fix it, instead of getting an empty result."""

from datetime import datetime, timezone


class HighlighterAPIError(ValueError):
    """Bad request to the API (unknown site, invalid filter value, bad date...)."""


def parse_timestamp(value: str, name: str) -> datetime:
    """Accept 'YYYY-MM-DD' or an ISO 8601 datetime; naive values are treated as UTC."""
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise HighlighterAPIError(
            f"{name}={value!r} is not a valid date. Use 'YYYY-MM-DD' or ISO 8601, "
            "e.g. '2026-10-01' or '2026-10-01T00:00:00Z'."
        ) from None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def check_allowed(name: str, values: list[str] | None, allowed: tuple[str, ...]) -> None:
    """Raise if any value isn't in `allowed`. None means 'no filter' and always passes."""
    if values is None:
        return
    bad = [v for v in values if v not in allowed]
    if bad:
        raise HighlighterAPIError(f"Unknown {name}: {bad}. Allowed: {list(allowed)}.")
