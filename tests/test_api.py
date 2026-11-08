"""Tests for the mock API. Expected numbers are computed straight from the raw JSONL
(not through the API) so the API is checked against an independent reading of the data."""

import json
from pathlib import Path

import pytest

from highlighter_mock import HighlighterAPIError, MockHighlighterAPI

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = [json.loads(line) for line in (DATA / "observations.jsonl").read_text().splitlines()]


@pytest.fixture
def api(tmp_path):
    return MockHighlighterAPI(flags_path=tmp_path / "flags.jsonl")


def test_list_sites(api):
    r = api.list_sites()
    assert len(r["sites"]) == 12
    assert r["data_as_of"] == "2026-11-07T23:59:59Z"
    s12 = next(s for s in r["sites"] if s["id"] == "S12")
    assert s12["onboarded_at"] == "2026-09-01"


def test_unfiltered_total_matches_raw(api):
    assert api.query_observations(limit=1)["total_matching"] == len(RAW)


def test_october_high_hazards_match_raw(api):
    expected = [
        o for o in RAW
        if o["category"] == "hazard" and o["severity"] in ("high", "critical")
        and o["observed_at"].startswith("2026-10")
        and o["status"] in ("open", "acknowledged")
    ]
    r = api.query_observations(
        categories=["hazard"], severities=["high", "critical"],
        statuses=["open", "acknowledged"],
        observed_from="2026-10-01", observed_to="2026-11-01", limit=1000,
    )
    assert r["total_matching"] == len(expected)
    assert {o["id"] for o in r["observations"]} == {o["id"] for o in expected}


def test_date_range_is_half_open(api):
    # observed_to is exclusive: Oct + Nov queried separately must add up to the combined range.
    oct_ = api.query_observations(observed_from="2026-10-01", observed_to="2026-11-01", limit=1)
    nov = api.query_observations(observed_from="2026-11-01", observed_to="2026-12-01", limit=1)
    both = api.query_observations(observed_from="2026-10-01", observed_to="2026-12-01", limit=1)
    assert oct_["total_matching"] + nov["total_matching"] == both["total_matching"]


def test_pagination_covers_everything_once(api):
    seen, offset = [], 0
    while offset is not None:
        r = api.query_observations(site_ids=["S01"], limit=100, offset=offset)
        seen += [o["id"] for o in r["observations"]]
        offset = r["next_offset"]
    expected = [o["id"] for o in RAW if o["site_id"] == "S01"]
    assert seen == expected


def test_outage_gap_is_really_empty(api):
    r = api.query_observations(site_ids=["S06"], observed_from="2026-09-15",
                               observed_to="2026-11-01", limit=1)
    assert r["total_matching"] == 0


def test_default_fields_are_compact_and_fields_param_works(api):
    o = api.query_observations(limit=1)["observations"][0]
    assert "image_ref" not in o
    o = api.query_observations(limit=1, fields=["id", "image_ref"])["observations"][0]
    assert set(o) == {"id", "image_ref"}


@pytest.mark.parametrize("kwargs, msg", [
    ({"site_ids": ["S99"]}, "Unknown site_ids"),
    ({"severities": ["severe"]}, "Allowed"),
    ({"statuses": ["unresolved"]}, "Allowed"),
    ({"observed_from": "last month"}, "not a valid date"),
    ({"observed_from": "2026-11-01", "observed_to": "2026-10-01"}, "earlier"),
    ({"limit": 5000}, "limit"),
    ({"min_confidence": 5}, "min_confidence"),
])
def test_bad_requests_fail_loudly(api, kwargs, msg):
    with pytest.raises(HighlighterAPIError, match=msg):
        api.query_observations(**kwargs)


def test_flag_site_writes_and_lists(api):
    r = api.flag_site("S01", "Rising unresolved high-severity hazards", "high")
    assert r["status"] == "created"
    flags = api.list_flags("S01")["flags"]
    assert len(flags) == 1 and flags[0]["priority"] == "high"
    assert api.list_flags("S02")["flags"] == []


@pytest.mark.parametrize("args, msg", [
    (("S99", "x"), "Unknown site_id"),
    (("S01", "   "), "empty"),
    (("S01", "x", "urgent"), "Allowed"),
])
def test_flag_site_validation(api, args, msg):
    with pytest.raises(HighlighterAPIError, match=msg):
        api.flag_site(*args)
