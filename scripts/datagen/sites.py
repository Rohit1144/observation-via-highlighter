"""The 12 mock sites. Each profile sets rates and trends; several carry a planted
story (a real pattern the agent should find) or a trap (a pattern that looks like
signal but isn't). See docs / the Notion "Dataset information" page."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import START


def d(y: int, m: int, day: int) -> datetime:
    return datetime(y, m, day, tzinfo=timezone.utc)


def cams(site: str, n_cctv: int, n_fixed: int, drone: bool) -> list[dict]:
    out = [{"id": f"{site}-CCTV-{i+1:02d}", "type": "cctv"} for i in range(n_cctv)]
    out += [{"id": f"{site}-FIX-{i+1:02d}", "type": "fixed_camera"} for i in range(n_fixed)]
    if drone:
        out.append({"id": f"{site}-DRONE-01", "type": "drone"})
    return out


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
    # Per-month multipliers (index = config.MONTHS position).
    hazard_rate_trend: list[float] = field(default_factory=lambda: [1.0] * 7)
    severity_bias_trend: list[float] = field(default_factory=lambda: [1.0] * 7)
    # Probability an observation eventually gets resolved, per month it was raised.
    resolve_prob_trend: list[float] = field(default_factory=lambda: [0.92] * 7)
    response_speed: float = 1.0  # >1 = slower to resolve
    onboarded: datetime = START
    outages: list[tuple[datetime, datetime]] = field(default_factory=list)
    drone_flight_weekday: int | None = None  # 0=Mon; drone sources only fly that day


@dataclass
class Incident:
    """A burst of extra hazards at one site, added on top of the normal arrivals."""
    site_id: str
    start: datetime
    days: int
    count: int
    types: list[str]
    severities: list[str]  # sampled uniformly; repeat a value to weight it
    min_confidence: float


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
    # STORY: one-off spike of critical fuel incidents 10-20 Oct (see INCIDENTS).
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

INCIDENTS: list[Incident] = [
    # STORY: Harbour Fuel Depot critical spike, 10-20 Oct. Mostly cleaned up by November.
    Incident("S09", d(2026, 10, 10), days=10, count=14,
             types=["oil_spill", "smoke_detected"],
             severities=["high", "critical", "critical"], min_confidence=0.8),
]
