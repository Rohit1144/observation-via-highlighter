"""How a single observation is sampled: type, severity, confidence and status."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from .config import (
    BASE_SEVERITY_WEIGHTS, DISMISS_PROB, HAZARD_TYPES, ISSUE_TYPES, LOW_CONFIDENCE,
    MEAN_RESOLVE_DAYS, MONTHS, NOW, SEVERITIES,
)
from .sites import SiteProfile


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's algorithm; fine for the small rates we use."""
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def month_index(ts: datetime) -> int:
    return MONTHS.index(ts.strftime("%Y-%m"))


def sample_severity(rng: random.Random, category: str, bias: float) -> str:
    if category == "asset":
        return "info"
    w = list(BASE_SEVERITY_WEIGHTS[category])
    # bias > 1 shifts weight from low/medium into high/critical.
    w[2] *= bias
    w[3] *= bias
    return rng.choices(SEVERITIES, weights=w)[0]


def sample_confidence(rng: random.Random, source_type: str) -> float:
    # Drones fly closer, so the detector is a bit more confident.
    conf = rng.betavariate(8, 2) if source_type == "drone" else rng.betavariate(6, 2.5)
    return round(min(max(conf, 0.30), 0.99), 2)


def sample_status(rng: random.Random, site: SiteProfile, ts: datetime, category: str,
                  severity: str, conf: float) -> tuple[str, datetime | None, datetime | None]:
    """Returns (status, acknowledged_at, resolved_at) as of NOW."""
    if category == "asset":
        return "n/a", None, None  # asset detections are inventory, not work items

    if conf < LOW_CONFIDENCE and rng.random() < DISMISS_PROB:
        # Low-confidence detection reviewed and rejected by a human.
        resolved_at = ts + timedelta(hours=rng.uniform(2, 72))
        if resolved_at <= NOW:
            return "dismissed", None, resolved_at
        return "open", None, None

    status, resolved_at, acknowledged_at = "open", None, None
    if rng.random() < site.resolve_prob_trend[month_index(ts)]:
        mean = MEAN_RESOLVE_DAYS[severity] * site.response_speed
        delay = timedelta(days=rng.expovariate(1 / mean))
        if ts + delay <= NOW:
            status, resolved_at = "resolved", ts + delay
    if status == "open" and NOW - ts > timedelta(days=2) and rng.random() < 0.6:
        status = "acknowledged"
        acknowledged_at = ts + timedelta(hours=rng.uniform(4, 48))
    return status, acknowledged_at, resolved_at


def make_observation(rng: random.Random, site: SiteProfile, ts: datetime, category: str,
                     source: dict, obs_type: str | None = None,
                     severity: str | None = None) -> dict:
    if obs_type is None:
        choices = {"hazard": HAZARD_TYPES, "issue": ISSUE_TYPES, "asset": site.assets}
        obs_type = rng.choice(choices[category])
    if severity is None:
        severity = sample_severity(rng, category, site.severity_bias_trend[month_index(ts)])
    conf = sample_confidence(rng, source["type"])
    status, acknowledged_at, resolved_at = sample_status(rng, site, ts, category, severity, conf)

    return {
        "site_id": site.id,
        "observed_at": ts,
        "source_id": source["id"],
        "source_type": source["type"],
        "category": category,
        "type": obs_type,
        "severity": severity,
        "confidence": conf,
        "status": status,
        "acknowledged_at": acknowledged_at,
        "resolved_at": resolved_at,
    }
