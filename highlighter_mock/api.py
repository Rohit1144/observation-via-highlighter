"""Mock Highlighter API.

`HighlighterAPI` is the interface the rest of the project depends on (the MCP server
wraps it; nothing else touches the data files). `MockHighlighterAPI` implements it
over the generated JSON files in data/. Making this real means writing a
`HttpHighlighterAPI` with the same methods that calls Highlighter's API instead;
the MCP server and agent don't change.

Design choices:
- Filtering only, no aggregation. Counting, trends and charts are the agent's job
  in the Code Interpreter sandbox, so the API returns rows, not answers.
- Paged results with `total_matching`, so the agent can tell when it has only part
  of the data instead of silently analysing a truncated sample.
- Strict validation with helpful messages (see validation.py).
- Every response carries `data_as_of`, so "last month" is anchored to the data, not
  to whatever date the model assumes.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .schema import (
    ALL_FIELDS, CATEGORIES, DEFAULT_DATA_DIR, DEFAULT_FIELDS, DEFAULT_FLAGS_PATH,
    DEFAULT_LIMIT, FLAG_PRIORITIES, MAX_LIMIT, MAX_REASON_LEN, SEVERITIES, STATUSES,
)
from .validation import HighlighterAPIError, check_allowed, parse_timestamp


class HighlighterAPI(Protocol):
    """What any Highlighter backend (mock or real) must provide."""

    def list_sites(self) -> dict[str, Any]: ...

    def get_site(self, site_id: str) -> dict[str, Any]: ...

    def query_observations(
        self,
        site_ids: list[str] | None = None,
        categories: list[str] | None = None,
        severities: list[str] | None = None,
        statuses: list[str] | None = None,
        types: list[str] | None = None,
        observed_from: str | None = None,
        observed_to: str | None = None,
        min_confidence: float | None = None,
        fields: list[str] | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]: ...

    def flag_site(self, site_id: str, reason: str, priority: str = "medium") -> dict[str, Any]: ...

    def list_flags(self, site_id: str | None = None) -> dict[str, Any]: ...


class MockHighlighterAPI:
    """In-memory implementation backed by data/*.json(l). Read-only except for flags."""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR, flags_path: Path | None = None):
        data_dir = Path(data_dir)
        self._sites: list[dict] = json.loads((data_dir / "sites.json").read_text())
        self._sites_by_id = {s["id"]: s for s in self._sites}
        self._metadata: dict = json.loads((data_dir / "metadata.json").read_text())
        self.data_as_of: str = self._metadata["data_as_of"]

        self._observations: list[dict] = []
        with open(data_dir / "observations.jsonl") as f:
            for line in f:
                o = json.loads(line)
                # Parse once up front so every query compares datetimes, not strings.
                o["_ts"] = parse_timestamp(o["observed_at"], "observed_at")
                self._observations.append(o)

        self._types = tuple(sorted({o["type"] for o in self._observations}))
        self._flags_path = Path(flags_path) if flags_path else DEFAULT_FLAGS_PATH

    # -- reads ---------------------------------------------------------------

    def list_sites(self) -> dict[str, Any]:
        sites = [
            {k: s[k] for k in ("id", "name", "type", "region", "onboarded_at")}
            | {"source_types": sorted({src["type"] for src in s["sources"]})}
            for s in self._sites
        ]
        return {"data_as_of": self.data_as_of, "data_start": self._metadata["data_start"],
                "sites": sites}

    def get_site(self, site_id: str) -> dict[str, Any]:
        site = self._sites_by_id.get(site_id)
        if site is None:
            raise HighlighterAPIError(
                f"Unknown site_id {site_id!r}. Known sites: {sorted(self._sites_by_id)}."
            )
        return {"data_as_of": self.data_as_of, "site": site}

    def query_observations(
        self,
        site_ids: list[str] | None = None,
        categories: list[str] | None = None,
        severities: list[str] | None = None,
        statuses: list[str] | None = None,
        types: list[str] | None = None,
        observed_from: str | None = None,
        observed_to: str | None = None,
        min_confidence: float | None = None,
        fields: list[str] | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Filter observations. `observed_from` is inclusive, `observed_to` exclusive,
        so a month is observed_from='2026-10-01', observed_to='2026-11-01'."""
        check_allowed("site_ids", site_ids, tuple(self._sites_by_id))
        check_allowed("categories", categories, CATEGORIES)
        check_allowed("severities", severities, SEVERITIES)
        check_allowed("statuses", statuses, STATUSES)
        check_allowed("types", types, self._types)
        check_allowed("fields", fields, ALL_FIELDS)
        if not 1 <= limit <= MAX_LIMIT:
            raise HighlighterAPIError(f"limit must be between 1 and {MAX_LIMIT}, got {limit}.")
        if offset < 0:
            raise HighlighterAPIError(f"offset must be >= 0, got {offset}.")
        if min_confidence is not None and not 0 <= min_confidence <= 1:
            raise HighlighterAPIError(f"min_confidence must be in [0, 1], got {min_confidence}.")

        start = parse_timestamp(observed_from, "observed_from") if observed_from else None
        end = parse_timestamp(observed_to, "observed_to") if observed_to else None
        if start and end and start >= end:
            raise HighlighterAPIError("observed_from must be earlier than observed_to.")

        sites, cats = set(site_ids or ()), set(categories or ())
        sevs, stats, typs = set(severities or ()), set(statuses or ()), set(types or ())

        matches = [
            o for o in self._observations
            if (not sites or o["site_id"] in sites)
            and (not cats or o["category"] in cats)
            and (not sevs or o["severity"] in sevs)
            and (not stats or o["status"] in stats)
            and (not typs or o["type"] in typs)
            and (start is None or o["_ts"] >= start)
            and (end is None or o["_ts"] < end)
            and (min_confidence is None or o["confidence"] >= min_confidence)
        ]

        keep = fields or DEFAULT_FIELDS
        page = [{k: o[k] for k in keep} for o in matches[offset:offset + limit]]
        next_offset = offset + len(page)
        return {
            "data_as_of": self.data_as_of,
            "total_matching": len(matches),
            "returned": len(page),
            "offset": offset,
            "next_offset": next_offset if next_offset < len(matches) else None,
            "observations": page,
        }

    # -- write ---------------------------------------------------------------

    def flag_site(self, site_id: str, reason: str, priority: str = "medium") -> dict[str, Any]:
        """Record a flag on a site. This is the one write action; the agent client must
        get human confirmation before calling it."""
        self.get_site(site_id)  # validates site_id
        check_allowed("priority", [priority], FLAG_PRIORITIES)
        reason = (reason or "").strip()
        if not reason:
            raise HighlighterAPIError("reason must not be empty.")
        if len(reason) > MAX_REASON_LEN:
            raise HighlighterAPIError(f"reason must be at most {MAX_REASON_LEN} characters.")

        flag = {
            "flag_id": f"FLAG-{uuid.uuid4().hex[:8]}",
            "site_id": site_id,
            "priority": priority,
            "reason": reason,
            # Real wall-clock time: this is when the action happened, not dataset time.
            "created_at": datetime.now(timezone.utc).replace(microsecond=0)
                          .isoformat().replace("+00:00", "Z"),
        }
        self._flags_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._flags_path, "a") as f:
            f.write(json.dumps(flag) + "\n")
        return {"status": "created", "flag": flag}

    def list_flags(self, site_id: str | None = None) -> dict[str, Any]:
        if site_id is not None:
            self.get_site(site_id)
        flags = []
        if self._flags_path.exists():
            flags = [json.loads(line) for line in self._flags_path.read_text().splitlines() if line]
        if site_id is not None:
            flags = [f for f in flags if f["site_id"] == site_id]
        return {"flags": flags}
