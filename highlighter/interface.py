"""The contract any Highlighter backend must meet.

The MCP server depends only on this. Today the backend is MockHighlighterAPI
(mock_api.py); making it real means adding e.g. HttpHighlighterAPI in http_api.py
with these same methods and passing it to build_server(). Nothing else changes.
"""

from __future__ import annotations

from typing import Any, Protocol

from .schema import DEFAULT_LIMIT


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
