"""Generate the mock Highlighter dataset (data/sites.json, data/observations.jsonl).

Deterministic: the same SEED and NOW always produce byte-identical files, so the
dataset committed to git can be regenerated and checked.

Design notes live in docs/DATASET.md. In short: realistic noise (Poisson arrivals,
detector confidence, false positives, resolution delays) plus a few deliberately
planted stories so we can tell whether the agent finds real signal or makes it up.

Usage:  python scripts/generate_dataset.py
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261107
START = datetime(2026, 5, 1, tzinfo=timezone.utc)
# "Now" for the dataset. Fixed (not datetime.now()) so the data never changes under us.
# Anything not resolved by NOW is still unresolved.
NOW = datetime(2026, 11, 7, 23, 59, 59, tzinfo=timezone.utc)

OUT_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

HAZARD_TYPES = [
    "missing_ppe", "unsecured_ladder", "standing_water", "fence_breach",
    "vegetation_encroachment", "blocked_exit", "trip_hazard", "smoke_detected",
    "oil_spill", "unauthorised_person",
]
ISSUE_TYPES = [
    "corrosion", "cracked_panel", "oil_leak", "damaged_fence", "graffiti",
    "insulator_damage", "debris", "lighting_failure",
]
ASSET_TYPES = [
    "transformer", "vehicle", "scaffold", "shipping_container", "crane",
    "solar_array", "pump", "wind_turbine", "fuel_tank",
]

SEVERITIES = ["low", "medium", "high", "critical"]
BASE_SEVERITY_WEIGHTS = {
    "hazard": [0.35, 0.35, 0.22, 0.08],
    "issue": [0.40, 0.40, 0.17, 0.03],
}
# Mean days to resolve, by severity, for a site with response_speed=1.0.
MEAN_RESOLVE_DAYS = {"low": 14.0, "medium": 7.0, "high": 3.0, "critical": 1.0}

MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]


@dataclass
class SiteProfile:
    id: str
    name: str
    site_type: str
    region: str
    lat: float
    lon: float
    # Expected observations per day by category.
    rates: dict[str, float]
    # Asset types this site has (what the detector sees as "asset" observations).
    assets: list[str]
    sources: list[dict]
    # Per-month multipliers (index = MONTHS position). Length 7.
    hazard_rate_trend: list[float] = field(default_factory=lambda: [1.0] * 7)
    severity_bias_trend: list[float] = field(default_factory=lambda: [1.0] * 7)
    # Probability an observation eventually gets resolved, per month it was raised.
    resolve_prob_trend: list[float] = field(default_factory=lambda: [0.92] * 7)
    response_speed: float = 1.0  # >1 = slower to resolve
    onboarded: datetime = START
    outages: list[tuple[datetime, datetime]] = field(default_factory=list)
    drone_flight_weekday: int | None = None  # 0=Mon; drone sources only fly that day


def d(y: int, m: int, day: int) -> datetime:
    return datetime(y, m, day, tzinfo=timezone.utc)


def cams(site: str, n_cctv: int, n_fixed: int, drone: bool) -> list[dict]:
    out = [{"id": f"{site}-CCTV-{i+1:02d}", "type": "cctv"} for i in range(n_cctv)]
    out += [{"id": f"{site}-FIX-{i+1:02d}", "type": "fixed_camera"} for i in range(n_fixed)]
    if drone:
        out.append({"id": f"{site}-DRONE-01", "type": "drone"})
    return out


SITES: list[SiteProfile] = [
    # STORY: getting worse. More high-severity hazards each month AND slower to fix them.
    SiteProfile(
        "S01", "Northgate Substation", "substation", "North", -36.8105, 174.7420,
        {"hazard": 0.6, "issue": 0.45, "asset": 0.4}, ["transformer", "vehicle"],
        cams("S01", 3, 2, True), drone_flight_weekday=1,
        hazard_rate_trend=[1.0, 1.05, 1.15, 1.3, 1.55, 1.85, 1.95],
        severity_bias_trend=[1.0, 1.2, 1.5, 1.9, 2.4, 3.0, 3.1],
        resolve_prob_trend=[0.92, 0.88, 0.82, 0.72, 0.6, 0.45, 0.4],
        response_speed=1.6,
    ),
    # STORY: improving. Fewer and less severe hazards, fast response.
    SiteProfile(
        "S02", "Riverside Solar Farm", "solar_farm", "West", -37.7870, 175.2793,
        {"hazard": 0.6, "issue": 0.5, "asset": 0.5}, ["solar_array", "vehicle"],
        cams("S02", 2, 2, True), drone_flight_weekday=3,
        hazard_rate_trend=[1.6, 1.5, 1.3, 1.1, 0.9, 0.7, 0.65],
        severity_bias_trend=[1.8, 1.6, 1.4, 1.1, 0.9, 0.7, 0.7],
        resolve_prob_trend=[0.88, 0.9, 0.93, 0.95, 0.96, 0.97, 0.97],
        response_speed=0.8,
    ),
    # STORY: noisy. Highest volume of observations, but almost all low severity.
    SiteProfile(
        "S03", "Eastport Container Terminal", "port", "East", -36.8433, 174.7850,
        {"hazard": 1.6, "issue": 1.0, "asset": 1.4}, ["shipping_container", "crane", "vehicle"],
        cams("S03", 6, 3, False),
        severity_bias_trend=[0.35] * 7, response_speed=1.0,
    ),
    SiteProfile(
        "S04", "Hillcrest Rail Yard", "rail_yard", "South", -37.6878, 176.1651,
        {"hazard": 0.6, "issue": 0.6, "asset": 0.5}, ["vehicle", "scaffold"],
        cams("S04", 3, 1, True), drone_flight_weekday=4,
    ),
    # STORY: many hazards but fixed quickly, so few remain unresolved.
    SiteProfile(
        "S05", "Westfield Construction Site", "construction", "West", -36.8775, 174.6360,
        {"hazard": 1.3, "issue": 0.4, "asset": 0.8}, ["scaffold", "crane", "vehicle"],
        cams("S05", 2, 2, True), drone_flight_weekday=0,
        severity_bias_trend=[1.4] * 7, resolve_prob_trend=[0.98] * 7, response_speed=0.4,
    ),
    # TRAP: cameras offline 15 Sep - 31 Oct. Zero observations is a data gap, not "safe".
    SiteProfile(
        "S06", "Lakeside Water Treatment", "water_treatment", "Central", -38.6857, 176.0702,
        {"hazard": 0.5, "issue": 0.5, "asset": 0.3}, ["pump", "vehicle"],
        cams("S06", 2, 2, False),
        severity_bias_trend=[1.3] * 7, resolve_prob_trend=[0.85] * 7, response_speed=1.2,
        outages=[(d(2026, 9, 15), d(2026, 11, 1))],
    ),
    SiteProfile(
        "S07", "Kingsway Warehouse", "warehouse", "North", -36.9020, 174.8000,
        {"hazard": 0.4, "issue": 0.3, "asset": 0.4}, ["vehicle"],
        cams("S07", 4, 0, False), severity_bias_trend=[0.6] * 7,
    ),
    # Consistently high severity, but stable (not trending).
    SiteProfile(
        "S08", "Granite Ridge Quarry", "quarry", "South", -39.4928, 176.9120,
        {"hazard": 0.7, "issue": 0.4, "asset": 0.6}, ["vehicle", "crane"],
        cams("S08", 2, 2, True), drone_flight_weekday=2,
        severity_bias_trend=[1.9] * 7, resolve_prob_trend=[0.8] * 7, response_speed=1.4,
    ),
    # STORY: one-off spike of critical fuel incidents 10-20 Oct (handled by extra hazards below).
    SiteProfile(
        "S09", "Harbour Fuel Depot", "fuel_depot", "East", -36.8400, 174.7700,
        {"hazard": 0.45, "issue": 0.4, "asset": 0.4}, ["fuel_tank", "vehicle"],
        cams("S09", 3, 2, False), resolve_prob_trend=[0.95] * 7, response_speed=0.7,
    ),
    # Drone-only site: sparse, clustered on weekly flight days.
    SiteProfile(
        "S10", "Meadow Hill Wind Farm", "wind_farm", "Central", -40.3523, 175.6082,
        {"hazard": 0.25, "issue": 0.35, "asset": 0.3}, ["wind_turbine"],
        cams("S10", 0, 0, True), drone_flight_weekday=5,
    ),
    SiteProfile(
        "S11", "Central Logistics Depot", "depot", "Central", -37.7000, 176.1000,
        {"hazard": 0.5, "issue": 0.4, "asset": 0.6}, ["vehicle", "shipping_container"],
        cams("S11", 3, 1, False),
    ),
    # TRAP: onboarded 1 Sep. "Getting worse" from a zero baseline is not a real trend.
    SiteProfile(
        "S12", "Southbank Pumping Station", "pumping_station", "South", -41.2865, 174.7762,
        {"hazard": 0.55, "issue": 0.45, "asset": 0.3}, ["pump"],
        cams("S12", 2, 1, False), onboarded=d(2026, 9, 1),
        severity_bias_trend=[1.2] * 7,
    ),
]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

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


def severity_for(rng: random.Random, category: str, bias: float) -> str:
    if category == "asset":
        return "info"
    w = list(BASE_SEVERITY_WEIGHTS[category])
    # bias > 1 shifts weight from low/medium into high/critical.
    w[2] *= bias
    w[3] *= bias
    return rng.choices(SEVERITIES, weights=w)[0]


def in_outage(site: SiteProfile, ts: datetime) -> bool:
    return any(a <= ts < b for a, b in site.outages)


def available_sources(site: SiteProfile, day: datetime) -> list[dict]:
    srcs = []
    for s in site.sources:
        if s["type"] == "drone":
            if day.weekday() == site.drone_flight_weekday:
                srcs.append(s)
        else:
            srcs.append(s)
    return srcs


def make_observation(rng, site: SiteProfile, ts: datetime, category: str, source: dict,
                     obs_type: str | None = None, severity: str | None = None) -> dict:
    m = month_index(ts)
    if obs_type is None:
        obs_type = rng.choice(
            {"hazard": HAZARD_TYPES, "issue": ISSUE_TYPES, "asset": site.assets}[category]
        )
    if severity is None:
        severity = severity_for(rng, category, site.severity_bias_trend[m])

    # Detector confidence; drones fly closer so they're a bit more confident.
    conf = rng.betavariate(8, 2) if source["type"] == "drone" else rng.betavariate(6, 2.5)
    conf = round(min(max(conf, 0.30), 0.99), 2)

    status, resolved_at, acknowledged_at = "open", None, None
    if category == "asset":
        # Asset detections are inventory, not work items.
        status = "n/a"
    elif conf < 0.55 and rng.random() < 0.45:
        # Low-confidence detection reviewed and rejected by a human.
        status = "dismissed"
        resolved_at = ts + timedelta(hours=rng.uniform(2, 72))
        if resolved_at > NOW:
            status, resolved_at = "open", None
    else:
        if rng.random() < site.resolve_prob_trend[m]:
            mean = MEAN_RESOLVE_DAYS[severity] * site.response_speed
            delay = timedelta(days=rng.expovariate(1 / mean))
            if ts + delay <= NOW:
                status, resolved_at = "resolved", ts + delay
        if status == "open" and NOW - ts > timedelta(days=2) and rng.random() < 0.6:
            status = "acknowledged"
            acknowledged_at = ts + timedelta(hours=rng.uniform(4, 48))

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


def generate() -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    raw: list[dict] = []

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

    # STORY: Harbour Fuel Depot critical spike, 10-20 Oct. Mostly cleaned up by November.
    s09 = next(s for s in SITES if s.id == "S09")
    for _ in range(14):
        ts = d(2026, 10, 10) + timedelta(seconds=rng.randrange(10 * 86400))
        o = make_observation(rng, s09, ts, "hazard", rng.choice(s09.sources),
                             obs_type=rng.choice(["oil_spill", "smoke_detected"]),
                             severity=rng.choice(["high", "critical", "critical"]))
        o["confidence"] = max(o["confidence"], 0.8)
        if o["status"] == "dismissed":
            o["status"] = "open"
            o["resolved_at"] = None
        raw.append(o)

    raw.sort(key=lambda o: (o["observed_at"], o["site_id"]))
    observations = []
    for i, o in enumerate(raw, start=1):
        o = {"id": f"OBS-{i:05d}", **o}
        for k in ("observed_at", "acknowledged_at", "resolved_at"):
            if o[k] is not None:
                o[k] = o[k].replace(microsecond=0).isoformat().replace("+00:00", "Z")
        o["image_ref"] = f"s3://highlighter-mock-frames/{o['site_id']}/{o['id']}.jpg"
        observations.append(o)

    sites = [
        {
            "id": s.id, "name": s.name, "type": s.site_type, "region": s.region,
            "lat": s.lat, "lon": s.lon,
            "onboarded_at": s.onboarded.date().isoformat(),
            "sources": s.sources,
        }
        for s in SITES
    ]
    return sites, observations


def main() -> None:
    sites, observations = generate()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "sites.json").write_text(json.dumps(sites, indent=2) + "\n")
    with open(OUT_DIR / "observations.jsonl", "w") as f:
        for o in observations:
            f.write(json.dumps(o, separators=(",", ":")) + "\n")
    print(f"wrote {len(sites)} sites, {len(observations)} observations to {OUT_DIR}")


if __name__ == "__main__":
    main()
