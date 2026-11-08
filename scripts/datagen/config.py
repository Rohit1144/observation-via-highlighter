"""Fixed settings and taxonomy for the mock dataset."""

from datetime import datetime, timezone
from pathlib import Path

SEED = 20261107
START = datetime(2026, 5, 1, tzinfo=timezone.utc)
# "Now" for the dataset. Fixed (not datetime.now()) so the data never changes under us.
# Anything not resolved by NOW is still unresolved.
NOW = datetime(2026, 11, 7, 23, 59, 59, tzinfo=timezone.utc)

OUT_DIR = Path(__file__).resolve().parents[2] / "data"

# Months covered, in order. Per-site trend lists in sites.py have one value per month.
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]

HAZARD_TYPES = [
    "missing_ppe", "unsecured_ladder", "standing_water", "fence_breach",
    "vegetation_encroachment", "blocked_exit", "trip_hazard", "smoke_detected",
    "oil_spill", "unauthorised_person",
]
ISSUE_TYPES = [
    "corrosion", "cracked_panel", "oil_leak", "damaged_fence", "graffiti",
    "insulator_damage", "debris", "lighting_failure",
]

SEVERITIES = ["low", "medium", "high", "critical"]
BASE_SEVERITY_WEIGHTS = {
    "hazard": [0.35, 0.35, 0.22, 0.08],
    "issue": [0.40, 0.40, 0.17, 0.03],
}
# Mean days to resolve, by severity, for a site with response_speed=1.0.
MEAN_RESOLVE_DAYS = {"low": 14.0, "medium": 7.0, "high": 3.0, "critical": 1.0}

# Detections below this confidence may be dismissed by a human as false positives.
LOW_CONFIDENCE = 0.55
DISMISS_PROB = 0.45
