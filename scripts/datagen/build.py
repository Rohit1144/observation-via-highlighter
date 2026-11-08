"""The generation loop: walk day by day, sample arrivals per site, add incidents,
then assign ids and format timestamps."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from .config import NOW, SEED, START
from .observations import make_observation, month_index, poisson
from .sites import INCIDENTS, SITES, Incident, SiteProfile


def in_outage(site: SiteProfile, ts: datetime) -> bool:
    return any(a <= ts < b for a, b in site.outages)


def available_sources(site: SiteProfile, day: datetime) -> list[dict]:
    """Fixed cameras always; drones only on the site's flight day."""
    return [
        s for s in site.sources
        if s["type"] != "drone" or day.weekday() == site.drone_flight_weekday
    ]


def daily_arrivals(rng: random.Random) -> list[dict]:
    raw = []
    day = START
    while day <= NOW:
        for site in SITES:
            if day < site.onboarded:
                continue
            srcs = available_sources(site, day)
            if not srcs:
                continue
            m = month_index(day)
            # Drone-only sites see everything on flight day; scale so the weekly total matches.
            drone_only = all(s["type"] == "drone" for s in site.sources)
            scale = 7.0 if drone_only else 1.0
            for category, base in site.rates.items():
                lam = base * scale
                if category == "hazard":
                    lam *= site.hazard_rate_trend[m]
                for _ in range(poisson(rng, lam)):
                    ts = day + timedelta(seconds=rng.randrange(86400))
                    if ts > NOW or in_outage(site, ts):
                        continue
                    raw.append(make_observation(rng, site, ts, category, rng.choice(srcs)))
        day += timedelta(days=1)
    return raw


def incident_observations(rng: random.Random, inc: Incident) -> list[dict]:
    site = next(s for s in SITES if s.id == inc.site_id)
    out = []
    for _ in range(inc.count):
        ts = inc.start + timedelta(seconds=rng.randrange(inc.days * 86400))
        o = make_observation(rng, site, ts, "hazard", rng.choice(site.sources),
                             obs_type=rng.choice(inc.types),
                             severity=rng.choice(inc.severities))
        o["confidence"] = max(o["confidence"], inc.min_confidence)
        # High-confidence real incidents aren't dismissed as false positives.
        if o["status"] == "dismissed":
            o["status"] = "open"
            o["resolved_at"] = None
        out.append(o)
    return out


def _iso(ts: datetime | None) -> str | None:
    return None if ts is None else ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def finalise(raw: list[dict]) -> list[dict]:
    """Sort by time, assign sequential ids, format timestamps, add image refs."""
    raw.sort(key=lambda o: (o["observed_at"], o["site_id"]))
    observations = []
    for i, o in enumerate(raw, start=1):
        o = {"id": f"OBS-{i:05d}", **o}
        for k in ("observed_at", "acknowledged_at", "resolved_at"):
            o[k] = _iso(o[k])
        o["image_ref"] = f"s3://highlighter-mock-frames/{o['site_id']}/{o['id']}.jpg"
        observations.append(o)
    return observations


def site_records() -> list[dict]:
    return [
        {
            "id": s.id, "name": s.name, "type": s.site_type, "region": s.region,
            "lat": s.lat, "lon": s.lon,
            "onboarded_at": s.onboarded.date().isoformat(),
            "sources": s.sources,
        }
        for s in SITES
    ]


def generate() -> tuple[list[dict], list[dict], dict]:
    """Returns (sites, observations, metadata). Deterministic for a given SEED."""
    rng = random.Random(SEED)
    raw = daily_arrivals(rng)
    for inc in INCIDENTS:
        raw += incident_observations(rng, inc)
    observations = finalise(raw)
    metadata = {
        "data_as_of": _iso(NOW),
        "data_start": _iso(START),
        "seed": SEED,
        "observation_count": len(observations),
    }
    return site_records(), observations, metadata
